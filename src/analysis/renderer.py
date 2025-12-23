# renderer.py (최종 수정)
import matplotlib.pyplot as plt
import logging
from typing import List, Optional
from decimal import Decimal
import numpy as np 
import matplotlib
matplotlib.use('Agg')
import pandas as pd
import mplfinance as mpf
from datetime import datetime 

logger = logging.getLogger("RENDERER")

# plot_line_chart 함수는 생략 (위에 그대로 두시면 됩니다)

def plot_candlestick_chart(
    opens: List[Decimal], highs: List[Decimal], lows: List[Decimal], closes: List[Decimal], volumes: List[Decimal],
    time_data: Optional[List[int]] = None, 
    resistance_levels: Optional[List[Decimal]] = None, 
    support_levels: Optional[List[Decimal]] = None, 
    main_title: str = "Candlestick Chart", 
    filename: str = "candlestick_chart") -> None:
    """
    OHLCV 데이터를 받아 mplfinance를 사용해 캔들 차트를 생성하고, 
    저항선 및 지지선을 라인으로 오버레이한 후 PNG 파일로 저장합니다.
    - 파일 이름은 'candlestick_chart.png'로 고정됩니다.
    - X축의 시간 정보와 Price/Volume 라벨은 표시하지 않으며, 차트 폭을 넓히고 여백을 제거합니다.
    """
    
    resistance_levels = resistance_levels if resistance_levels is not None else []
    support_levels = support_levels if support_levels is not None else []
    
    if not closes:
        logger.warning(f"Cannot plot chart: closing price list is empty for {main_title}.")
        return

    # --- matplotlib RC 설정 임시 저장 및 X축 라벨 숨김 적용 ---
    original_rcParams = plt.rcParams.copy()
    
    # X축 눈금/라벨을 숨기는 표준 matplotlib RC 설정
    standard_hide_xaxis_rc = {
        'axes.labelcolor': 'none',        # X축 라벨 색상 숨김
        'xtick.color': 'none',            # X축 눈금 색상 숨김
        'xtick.labelcolor': 'none',       # X축 눈금 라벨 색상 숨김
    }
    
    try:
        data = {
            'Open': [float(d) for d in opens],
            'High': [float(d) for d in highs],
            'Low': [float(d) for d in lows],
            'Close': [float(d) for d in closes],
            'Volume': [float(d) for d in volumes],
        }
        
        df = pd.DataFrame(data)
        
        # DatetimeIndex 생성
        if time_data and len(time_data) == len(closes):
            df.index = pd.to_datetime(time_data, unit='ms')
        else:
            end_date = pd.Timestamp(datetime.now())
            start_date = end_date - pd.Timedelta(minutes=(len(closes) - 1))
            date_range = pd.date_range(start=start_date, periods=len(closes), freq='min')
            df.index = date_range

        # 오버레이 라인 설정 (생략)
        apds = []
        for i, level in enumerate(resistance_levels):
            apds.append(mpf.make_addplot([float(level)] * len(df), color='red', linestyle='-', linewidth=1.5, panel=0, label=f'Resistance {i+1}'))
        
        for i, level in enumerate(support_levels):
            apds.append(mpf.make_addplot([float(level)] * len(df), color='blue', linestyle='-', linewidth=1.5, panel=0, label=f'Support {i+1}'))

        # 파일 이름 고정
        output_filename = "candlestick_chart.png" 
        
        # X축 숨김을 위한 표준 RC 설정 적용
        plt.rcParams.update(standard_hide_xaxis_rc) 

        # 'yahoo' 스타일을 기반으로 X축 숨김 설정 오버라이드
        custom_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc=standard_hide_xaxis_rc)

        # --- 패널 비율 설정: Volume 라벨 숨김 및 패널 공간 최소화 목적 ---
        # 캔들 패널(0) 비율을 10으로, Volume 패널(1) 비율을 0.01 (거의 0)로 설정
        panel_ratios = [10, 0.01]
        
        # 캔들 차트 플롯
        mpf.plot(
            df, 
            type='candle', 
            volume=True, 
            title=main_title, 
            ylabel='',                # <--- Price 라벨 숨김
            style=custom_style, 
            addplot=apds, 
            savefig=dict(fname=output_filename, bbox_inches='tight'), # <--- **여백 제거 적용**
            figscale=2.0,             # <--- 차트 좌우 폭 확장 유지
            panel_ratios=panel_ratios # <--- Volume 패널 높이 극도로 낮춤
        )
        
        logger.info(f"Candlestick chart saved to {output_filename}")

    except Exception as e:
        logger.error(f"Error while plotting candlestick chart: {e}", exc_info=True)
    finally:
        # --- 원래의 matplotlib RC 설정으로 되돌리기 ---
        plt.rcParams.update(original_rcParams)