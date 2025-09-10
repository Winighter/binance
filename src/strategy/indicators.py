import pandas as pd
from decimal import Decimal, getcontext, ROUND_HALF_UP
import pandas_ta as ta


# getcontext().prec 값은 충분히 크게 설정
getcontext().prec = 28

class Indicators():

    _ROUND_PRECISION = 4

    @staticmethod
    def rma(_src: list, _length: int, _array: int = 0):

        rma_values = []
        alpha = Decimal(str(round(1 / _length, Indicators._ROUND_PRECISION + 2)))

        if len(_src) < _length:
            raise ValueError(f"Insufficient data for RMA calculation. Expected at least {_length} data points, but got {len(_src)}.")

        time_src_reversed = _src[_length-1::-1]
        
        current_rma = round(sum(time_src_reversed) / _length, Indicators._ROUND_PRECISION)
        rma_values.append(current_rma)

        for i in range(len(_src) - _length -1, -1, -1):
            current_rma = alpha * _src[i] + (1 - alpha) * current_rma
            rma_values.append(round(current_rma, Indicators._ROUND_PRECISION))

        result = rma_values[::-1]

        if _array is not None:
            if len(result) > _array:
                return result[_array]
            else:
                raise ValueError(f"Invalid _array index for RMA. Result list has {len(result)} elements, but index {_array} was requested.")
        return result

    @staticmethod
    def atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int = 14):

        if not highs:
            return pd.Series([], dtype=object)

        input_decimal_places = 0
        high_str = str(highs[0])
        if '.' in high_str:
            input_decimal_places = len(high_str.split('.')[-1])

        data = pd.DataFrame({
            'High': highs,
            'Low': lows,
            'Close': closes
        })

        tr1 = data['High'] - data['Low']
        tr2 = abs(data['High'] - data['Close'].shift(1))
        tr3 = abs(data['Low'] - data['Close'].shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        alpha = Decimal(str(1)) / Decimal(str(period))
        atr_values = [Decimal(str(true_range.iloc[0:period].mean()))]

        for i in range(period, len(true_range)):
            current_atr = alpha * true_range.iloc[i] + (Decimal(str(1)) - alpha) * atr_values[-1]
            atr_values.append(current_atr)

        quantizer = Decimal('1e-' + str(input_decimal_places))
        rounded_atr_values = [x.quantize(quantizer, rounding=ROUND_HALF_UP) for x in atr_values]

        return pd.Series(rounded_atr_values, index=true_range.index[period-1:])

    @staticmethod
    def supertrend(_high: list[Decimal], _low: list[Decimal], _close: list[Decimal], _atr: list[Decimal], _atr_length: int = 14, _multiplier: float = 4.0, _array: int = 0):
        """
        파인스크립트 SuperTrend 로직을 기반으로 SuperTrend 지표를 계산합니다.
        가장 최근 데이터가 인덱스 0에, 오래된 데이터는 그 뒤에 위치한다고 가정합니다.

        Args:
            _high (list): 고가 리스트. (가장 최근 데이터가 인덱스 0)
            _low (list): 저가 리스트. (가장 최근 데이터가 인덱스 0)
            _close (list): 종가 리스트. (가장 최근 데이터가 인덱스 0)
            _atr_length (int, optional): ATR 계산에 사용될 기간. 파인스크립트 기본값인 14를 따릅니다.
            _multiplier (float, optional): ATR에 곱해져 밴드 폭을 결정하는 승수. 파인스크립트 기본값인 4.0을 따릅니다.
            _array (int, optional): 정수일 경우, 해당 인덱스(0은 가장 최근 SuperTrend)의 값을 반환합니다.
                                    None일 경우, SuperTrend 값의 전체 리스트를 반환합니다. 기본값은 0.

        Returns:
            list 또는 float: _array가 None이면 SuperTrend 값의 리스트, 아니면 단일 SuperTrend 값.

        Raises:
            ValueError: 입력 리스트의 길이가 다르거나, 계산을 위한 데이터가 부족하거나, _array 인덱스가 유효하지 않을 경우 발생합니다.
        """
        _multiplier = Decimal(str(_multiplier))

        # 1. 입력 유효성 검사 🛡️
        # 모든 가격 데이터 리스트의 길이가 동일한지 확인합니다.
        if not (len(_high) == len(_low) == len(_close)):
            raise ValueError(f"SuperTrend 계산을 위한 입력 리스트의 길이가 동일해야 합니다. "
                             f"고가: {len(_high)}, 저가: {len(_low)}, 종가: {len(_close)}.")

        # SuperTrend 계산에 필요한 최소 데이터 길이를 확인합니다.
        # ATR 계산에 _atr_length 만큼의 데이터가 필요하고, 이전 종가(`close[1]`) 참조를 위해 최소 _atr_length + 1개의 데이터가 필요합니다.
        min_data_needed = _atr_length + 1
        if len(_high) < min_data_needed:
            raise ValueError(f"SuperTrend 계산을 위한 데이터가 부족합니다. 최소 {min_data_needed}개의 데이터 포인트가 필요하지만, {len(_high)}개를 받았습니다.")
        
        # hl2 계산후 리스트 집어넣기
        hl2_list = []
        for i in range(len(_high)):
            hl2 = Decimal(str((_high[i] + _low[i]) / 2))
            hl2_list.append(round(hl2, 4))

        hl2_list = hl2_list[-len(_atr):]
        _close = _close[-len(_atr):]
        _atr = _atr[:len(_atr)]

        up_list = []
        dn_list = []
        supertrend_list = []
        trend = [0] * len(_atr)  # 추세 리스트를 0으로 초기화
        signal = [0] * len(_atr) # 신호 리스트를 0으로 초기화

        for i in range(len(_atr)):
            src = hl2_list[i]
            close = _close[i]
            atr = _atr[i]
            up = Decimal(str(src - (_multiplier * atr)))
            dn = Decimal(str(src + (_multiplier * atr)))
            # 'up' 및 'dn'에 대한 Pine Script 로직 적용
            if i > 0:
                up1 = up_list[-1]
                if _close[i-1] > up1:
                    up = max(up, up1)
                
                dn1 = dn_list[-1]
                if _close[i-1] < dn1:
                    dn = min(dn, dn1)
            
            up_list.append(up)
            dn_list.append(dn)

        # 2. 슈퍼트렌드와 추세 계산
        for i in range(len(_atr)):
            current_close = _close[i]
            current_up = up_list[i]
            current_dn = dn_list[i]

            if i == 0:
                # 첫 번째 데이터 포인트의 초기 슈퍼트렌드 값 및 추세 설정
                if current_close < current_dn:
                    supertrend_list.append(current_dn)
                    trend[i] = -1  # 하락 추세
                else:
                    supertrend_list.append(current_up)
                    trend[i] = 1   # 상승 추세
            else:
                prev_supertrend = supertrend_list[i-1]
                prev_trend = trend[i-1]

                # 매수 신호: 이전 추세가 하락(-1)에서 상승(1)으로 전환
                if prev_trend == -1 and current_close > prev_supertrend:
                    trend[i] = 1
                    signal[i] = 1
                    supertrend_list.append(current_up)
                
                # 매도 신호: 이전 추세가 상승(1)에서 하락(-1)으로 전환
                elif prev_trend == 1 and current_close < prev_supertrend:
                    trend[i] = -1
                    signal[i] = -1
                    supertrend_list.append(current_dn)
                
                # 추세가 유지될 때
                else:
                    trend[i] = prev_trend
                    if prev_trend == 1:
                        supertrend_list.append(max(current_up, prev_supertrend))
                    else:
                        supertrend_list.append(min(current_dn, prev_supertrend))

        return signal, supertrend_list

    @staticmethod
    def ema(prices: list[Decimal], period: int) -> list[Decimal]:
        """
        주어진 Decimal 타입 가격 리스트에 대한 EMA(지수 이동 평균)를 계산합니다.
        
        Args:
            prices: 0인덱스가 가장 오래된 가격이고, 마지막 인덱스가 가장 최신 가격인 Decimal 타입 리스트.
            period: EMA를 계산할 기간.
            
        Returns:
            EMA 값이 담긴 Decimal 타입 리스트.
            EMA 값이 계산된 시점부터의 값을 반환하며, 처음 (period - 1)개는 NaN 또는 None으로 처리될 수 있습니다.
            이 함수는 계산 가능한 시점부터의 EMA 값만 반환합니다.
        """
        if not prices or len(prices) < period:
            return []

        # EMA 계산을 위한 승수(multiplier)
        # 2 / (period + 1)
        # Decimal 타입 연산을 위해 Decimal로 변환
        multiplier = Decimal('2') / (Decimal(period) + Decimal('1'))
        
        # 첫 EMA 값은 SMA(단순 이동 평균)
        # prices[0] 부터 prices[period-1] 까지의 평균
        ema_list = []
        
        # 첫 EMA 값 (SMA) 계산
        # sum() 함수는 Decimal 타입을 처리
        first_ema = sum(prices[0:period]) / Decimal(period)
        ema_list.append(first_ema)
        
        # 두 번째 EMA 값부터 계산
        # EMA = (현재 가격 - 이전 EMA) * multiplier + 이전 EMA
        for i in range(period, len(prices)):
            current_price = prices[i]
            prev_ema = ema_list[-1]  # 리스트의 마지막 값이 이전 EMA
            
            # EMA 공식 적용
            current_ema = (current_price - prev_ema) * multiplier + prev_ema
            ema_list.append(current_ema)
            
        return ema_list