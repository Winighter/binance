from decimal import Decimal, getcontext
import pandas as pd
import numpy as np
import math

# Decimal 연산 정밀도 설정 (Pine Script의 float64 정밀도에 근접하게 설정)
# Decimal 연산을 사용하면 속도가 매우 느려질 수 있습니다.
getcontext().prec = 50 

# Pine Script Input 기본값 설정
OSC_PERIOD = 20

def calculate_trend_reversal_probability_decimal(
    high_prices: list[Decimal], 
    low_prices: list[Decimal], 
    close_prices: list[Decimal], 
    osc_period: int = OSC_PERIOD
) -> pd.DataFrame:
    """
    과거 -> 최신 순서의 Decimal 리스트를 입력으로 받아
    'Trend Reversal Probability' 지표 로직을 구현합니다.
    """
    def decimal_rma_manual(series: pd.Series, length: int) -> pd.Series:
        """
        Decimal Series를 입력받아 Decimal 기반의 RMA(Exponential Moving Average)를 계산합니다.
        (Pine Script의 ta.rma 로직)
        """
        results = [Decimal('NaN')] * len(series)
        
        # Decimal 타입의 length
        length_dec = Decimal(length)
        
        # 초기값 설정 (Pine Script의 ta.rma는 첫 length개의 단순 평균을 사용하지 않고,
        # 첫 NaN이 아닌 값부터 지수평균을 시작합니다.)
        
        # 첫 번째 NaN이 아닌 값 찾기
        first_non_nan_index = series.first_valid_index()
        if first_non_nan_index is None:
            return pd.Series(results)
        
        # 첫 NaN이 아닌 값을 RMA의 초기값으로 사용
        rma_prev = series.iloc[first_non_nan_index]
        results[first_non_nan_index] = rma_prev
        
        # 재귀 공식 적용
        for i in range(first_non_nan_index + 1, len(series)):
            current_value = series.iloc[i]
            
            if pd.isna(current_value):
                # 현재 값이 NaN이면 이전 RMA 값을 유지
                rma_current = rma_prev
            else:
                # RMA_t = (source_t + (length - 1) * RMA_{t-1}) / length
                rma_current = (current_value + (length_dec - Decimal(1)) * rma_prev) / length_dec
                
            results[i] = rma_current
            rma_prev = rma_current # 다음 반복을 위해 업데이트
                
        return pd.Series(results, index=series.index)

    # 1. 데이터프레임 구성 (Decimal 타입 유지)
    data = {
        'high': high_prices,
        'low': low_prices,
        'close': close_prices
    }
    df = pd.DataFrame(data)
    
    # 모든 연산을 Decimal로 유지하기 위해 DataFrame의 각 값을 Decimal로 강제 변환
    # (이미 입력이 Decimal 리스트이므로 필요 없을 수 있으나, 명시적으로 처리)
    for col in df.columns:
        df[col] = df[col].apply(Decimal)

    # 2. Amazing Oscillator Calculation (AO 계산)
    
    # midpointPrice = hl2
    df['midpointPrice'] = (df['high'] + df['low']) / Decimal(2)
    
    # ★ 성능 저하를 감수하고 Decimal 연산을 유지하는 '수동 롤링 평균' 구현
    def decimal_rolling_mean(series, window):
        results = [Decimal('NaN')] * (window - 1)
        for i in range(window - 1, len(series)):
            window_data = series.iloc[i-window+1 : i+1]
            results.append(sum(window_data) / Decimal(window))
        return results

    df['shortSMA'] = decimal_rolling_mean(df['midpointPrice'], 5)
    df['longSMA'] = decimal_rolling_mean(df['midpointPrice'], 34)
    
    df['amazingOsc'] = df['shortSMA'] - df['longSMA']
    
    # 3. Custom RSI-like Calculation (Custom RSI 계산)
    
    amazingOsc_change = df['amazingOsc'].diff()
    
    # RMA (Relative Moving Average) - Decimal을 위한 수동 EMA 구현
    alpha = Decimal(1) / Decimal(osc_period)
    
    # ★ Decimal('NaN')과 Decimal(0) 비교 시 InvalidOperation 방지 로직 (수정됨)
    def safe_max_zero(x):
        if pd.isna(x):
            return Decimal('NaN')
        return max(x, Decimal(0))

    def safe_min_zero(x):
        if pd.isna(x):
            return Decimal('NaN')
        return -min(x, Decimal(0))

    # rise, fall 계산
    df['change_up'] = amazingOsc_change.apply(safe_max_zero)
    df['change_down'] = amazingOsc_change.apply(safe_min_zero)

    # 계산의 일관성을 위해 다시 Decimal Series로 변환
    rise = decimal_rma_manual(df['change_up'], osc_period)
    fall = decimal_rma_manual(df['change_down'], osc_period)

    # customRSI 계산
    def calculate_custom_rsi_decimal(r, f):
        if r == Decimal('NaN') or f == Decimal('NaN'): return Decimal('NaN')
        if f == Decimal(0):
            return Decimal(50) 
        elif r == Decimal(0):
            return Decimal(-50)
        else:
            rs = r / f
            rsi = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))
            return rsi - Decimal(50)
            
    df['customRSI'] = np.vectorize(calculate_custom_rsi_decimal)(rise, fall)
    
    # 4. Trend Duration Analysis (추세 지속 시간 분석)
    
    # cross_signal은 부호가 바뀔 때 (0을 교차할 때)
    cross_signal = (df['customRSI'].shift(1) <= Decimal(0)) & (df['customRSI'] > Decimal(0)) | \
                   (df['customRSI'].shift(1) >= Decimal(0)) & (df['customRSI'] < Decimal(0))

    # cut (현재 추세 지속 시간) 계산 - 반복문 사용
    cut = []
    current_cut = 0
    for is_cross in cross_signal:
        if is_cross:
            current_cut = 0
        else:
            current_cut += 1
        cut.append(current_cut)
        
    df['cut'] = cut
    
    # durations, basis, stdev 계산 - 반복문 사용
    durations = []
    df['basis'] = Decimal('NaN')
    df['stdev'] = Decimal('NaN')
    
    for i in range(1, len(df)):
        if df['cut'].iloc[i] == 0 and df['cut'].iloc[i-1] != 0:
            durations.append(df['cut'].iloc[i-1])
            
        if durations:
            # Decimal 리스트의 평균과 표준편차 계산
            durations_array = np.array(durations, dtype=object) 
            
            # Decimal의 평균
            current_basis = sum(durations_array) / Decimal(len(durations_array))
            df.loc[df.index[i], 'basis'] = current_basis
            
            # Decimal의 표준편차 (수동 계산)
            variance = sum([(d - current_basis)**2 for d in durations_array]) / Decimal(len(durations_array))
            df.loc[df.index[i], 'stdev'] = variance.sqrt()

    # 5. Probability Calculation (확률 계산)
    
    # Z-score 계산 (DivisionByZero 방지 로직 적용됨)
    # 1. 안전한 분모 생성 (0 대신 1을 사용하여 나눗셈 오류 회피)
    safe_stdev = np.where(df['stdev'] == Decimal(0), Decimal(1), df['stdev'])

    # 2. 안전한 나눗셈 수행
    z_calculated = (df['cut'] - df['basis']) / safe_stdev

    # 3. stdev가 0이었던 위치는 NaN으로 최종 처리
    df['z'] = np.where(
        df['stdev'] == Decimal(0),
        Decimal('NaN'),
        z_calculated
    )
    
    # f_cdf 함수 (Decimal을 위한 수정)
    def f_cdf_decimal(z):
        # NaN 입력 시 안전하게 처리 (수정됨)
        if z is None or pd.isna(z) or z == Decimal('NaN'):
            return Decimal('NaN')

        # float로 변환하여 계산 후, 결과를 Decimal로 변환 (속도 및 복잡성 때문)
        z_float = float(z)
        
        # CDF 근사를 위한 상수 (Pine Script 원본 유지)
        a1 = 0.254829592; a2 = -0.284496736; a3 = 1.421413741
        a4 = -1.453152027; a5 = 1.061405429; p = 0.3275911

        sign = -1 if z_float < 0 else 1
        x = abs(z_float) / math.sqrt(2)
        t = 1 / (p * x + 1)
        erf_approx = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        
        result_float = 0.5 * (1 + sign * erf_approx)
        return Decimal(str(result_float))

    df['probability'] = df['z'].apply(f_cdf_decimal)
    
    return df