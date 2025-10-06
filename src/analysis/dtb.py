import pandas as pd
import numpy as np
import ta
from ta.trend import wma_indicator
from decimal import Decimal, getcontext
from typing import List

# Decimal 정확도 설정 (선택 사항, 금융 계산 시 유용)
getcontext().prec = 28 

# (이전에 정의한 hma, wma, calculate_dtb, plot_dtb 함수는 그대로 사용한다고 가정합니다.)
# 편의를 위해 calculate_dtb 함수의 정의를 다시 포함합니다.

# --------------------------------------------------------------------------------------------------------------------
# 1. 계산 함수 (이전 코드와 동일)
# --------------------------------------------------------------------------------------------------------------------

# HMA 및 WMA 헬퍼 함수 (이전 코드에서 복사)
def wma(series, length):
    # [수정] ta.momentum.WMAIndicator 대신 ta.trend.wma_indicator를 사용합니다.
    # WMAIndicator 클래스가 없으므로, ta 라이브러리 내의 다른 WMA 계산 방식을 사용해야 합니다.
    # ta.trend.wma_indicator는 Pandas Series를 반환합니다.
    return wma_indicator(close=series, window=length, fillna=False)

def hma(series, length):
    half_len = int(length / 2)
    sqrt_len = int(np.sqrt(length))

    # 1. WMA 계산
    wma1 = wma(series, half_len)
    wma2 = wma(series, length)

    diff = 2 * wma1 - wma2
    # 최종 WMA 계산
    return wma(diff, sqrt_len)

def calculate_dtb(
    df: pd.DataFrame,
    length: int = 40,
    multi: float = 2.0,
    band_size: int = 2
) -> pd.DataFrame:
    """Pine Script의 Dynamic Trend Bands 지표를 계산합니다."""
    
    # Decimal 타입이 Pandas DataFrame으로 들어오면 자동으로 float으로 변환되거나 
    # Decimal 객체 그대로 유지될 수 있지만, TA 라이브러리는 float을 기대하므로
    # 계산 전에 안전을 위해 Series가 float 타입인지 확인합니다.
    df['Close'] = df['Close'].astype(float)
    df['High'] = df['High'].astype(float)
    df['Low'] = df['Low'].astype(float)

    # --- HMA Calculation (Double-Smoothed) ---
    inner_hma = hma(df['Close'], length - 10)
    df['Base'] = hma(inner_hma, length)

    # --- Volatility Bands Calculation ---
    df['ATR'] = ta.volatility.AverageTrueRange(
        high=df['High'], low=df['Low'], close=df['Close'], window=100, fillna=False
    ).average_true_range()
    df['Dist'] = df['ATR'] * multi
    df['Upper_Raw'] = df['Base'] + df['Dist']
    df['Lower_Raw'] = df['Base'] - df['Dist']

    # --- Band Plotting Conditions (Stepped/Dynamic Bands) ---
    df['Lower_Band'] = np.where(
        df['Lower_Raw'] >= df['Lower_Raw'].shift(band_size),
        df['Lower_Raw'].shift(band_size),
        np.nan
    )
    df['Lower_Band1'] = np.where(
        df['Lower_Raw'] >= df['Lower_Raw'].shift(band_size),
        df['Lower_Raw'],
        np.nan
    )
    df['Upper_Band'] = np.where(
        df['Upper_Raw'] <= df['Upper_Raw'].shift(band_size),
        df['Upper_Raw'].shift(band_size),
        np.nan
    )
    df['Upper_Band1'] = np.where(
        df['Upper_Raw'] <= df['Upper_Raw'].shift(band_size),
        df['Upper_Raw'],
        np.nan
    )
    
    # --- Momentum Shift Signal ---
    df['Momentum_Signal'] = 0 
    condition_up = (df['Upper_Band1'] <= df['Upper_Band1'].shift(2)) & (df['High'] > df['Upper_Band'])
    df.loc[condition_up, 'Momentum_Signal'] = 1
    condition_down = (df['Lower_Band'] >= df['Lower_Band'].shift(2)) & (df['Low'] < df['Lower_Band'])
    df.loc[condition_down, 'Momentum_Signal'] = 2

    return df.dropna(subset=['Base'])

# (plot_dtb 함수는 이전과 동일하며 생략합니다.)
# --------------------------------------------------------------------------------------------------------------------
# 2. Decimal 리스트 처리 및 플롯 함수
# --------------------------------------------------------------------------------------------------------------------

def process_and_get_dtb_data( # 함수 이름 변경 제안
    high: List[Decimal],
    low: List[Decimal],
    close: List[Decimal],
    length: int = 40,
    multi: float = 2.0,
    band_size: int = 2,
    # bars_col, filll 은 계산에 불필요하므로 제거 가능
) -> pd.DataFrame: # DataFrame을 반환하도록 수정
    """
    Decimal 리스트를 입력으로 받아 Dynamic Trend Bands를 계산하고 결과를 DataFrame으로 반환합니다.
    """
    if not (len(high) == len(low) == len(close)):
        raise ValueError("고가, 저가, 종가 리스트의 길이가 동일해야 합니다.")
    
    data = {
        'High': high,
        'Low': low,
        'Close': close
    }
    df = pd.DataFrame(data)
    
    df_calculated = calculate_dtb(df, length, multi, band_size)
    
    # 서버 환경이므로 print/plot 대신 데이터를 반환합니다.
    # print("계산 완료. 데이터의 마지막 몇 행:")
    # print(df_calculated.tail())
    
    return df_calculated # 계산된 DataFrame 반환