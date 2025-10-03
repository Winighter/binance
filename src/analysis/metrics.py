import logging
from decimal import Decimal, getcontext
import numpy as np
import math

logger = logging.getLogger("METRICS")

getcontext().prec = 50


class Metrics():

    @staticmethod
    def ema(prices: list[Decimal], period: int) -> list[Decimal]:

        if not prices or len(prices) < period:
            return []

        multiplier = Decimal('2') / (Decimal(period) + Decimal('1'))
        ema_list = []
        first_ema = sum(prices[0:period]) / Decimal(period)
        ema_list.append(first_ema)

        for i in range(period, len(prices)):
            current_price = prices[i]
            prev_ema = ema_list[-1]
            current_ema = (current_price - prev_ema) * multiplier + prev_ema
            ema_list.append(current_ema)

        return ema_list

    @staticmethod
    def atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int = 14) -> list[Decimal]:
        if not highs or not lows or not closes or len(highs) != len(lows) or len(highs) != len(closes) or len(highs) < period:
            return []

        true_ranges = []
        for i in range(len(highs)):
            h_l = highs[i] - lows[i]
            if i > 0:
                h_c_prev = abs(highs[i] - closes[i-1])
                l_c_prev = abs(lows[i] - closes[i-1])
                true_range = max(h_l, h_c_prev, l_c_prev)
            else:
                true_range = h_l
            true_ranges.append(true_range)
        
        # 첫 번째 ATR은 True Range의 단순 평균(SMA)
        atr_list = [sum(true_ranges[:period]) / Decimal(period)]

        # 이후 ATR은 지수 이동 평균(EMA)을 사용하여 계산
        for i in range(period, len(true_ranges)):
            current_atr = (atr_list[-1] * (period - 1) + true_ranges[i]) / Decimal(period)
            atr_list.append(current_atr)

        return atr_list
    
    @staticmethod
    def keltner_channels(kc_ema: Decimal, atr_value: Decimal, kc_multiplier: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        basis = kc_ema
        upper = basis + atr_value * kc_multiplier
        lower = basis - atr_value * kc_multiplier
        return upper, basis, lower

    # ----------------------------------------------------------------------
    # 💡 Trend Reversal Probability 함수 새로 작성
    # ----------------------------------------------------------------------
    @staticmethod
    def trend_reversal_probability(high_list, low_list, close_list, osc_period=20):
        """
        Pine Script의 'Trend Reversal Probability' 지표 로직을 파이썬으로 구현합니다.
        CustomRSI 및 Duration 계산 로직의 정확도를 높였습니다.
        """

        # 1. 데이터를 Decimal 타입으로 변환 (0 인덱스: 가장 오래된 과거, N-1 인덱스: 최신)
        H = [Decimal(str(x)) for x in high_list]
        L = [Decimal(str(x)) for x in low_list]
        C = [Decimal(str(x)) for x in close_list]
        N = len(H)
        
        # AO(34)와 RMA(osc_period)를 위해 최소 기간 확인
        min_required_bars = max(34, osc_period)
        if N < min_required_bars + 1:
            return Decimal('0.5'), Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'), 'GRAY', Decimal('0')


        # --- 보조 함수: Pine Script 시리즈 로직을 따르는 순방향 계산 함수 ---
        
        # Pine Script의 ta.rma (Wilder's Smoothing) 함수
        def rma_calc(source_series, length):
            S = len(source_series) 
            rma_list = []
            
            # 초기 length-1개는 0으로 채움 (Pine Script의 na/0 처리)
            for _ in range(length - 1):
                rma_list.append(Decimal('0'))
            
            if S >= length:
                # 첫 SMA 계산 (length 기간의 단순 평균)
                initial_data = source_series[0:length]
                initial_sma = sum(initial_data) / Decimal(length)
                rma_list.append(initial_sma)
                
                # 이후 RMA 계산
                for i in range(length, S):
                    current_source = source_series[i] 
                    prev_rma = rma_list[-1]
                    # RMA 공식: (prev_rma * (length - 1) + current_source) / length
                    current_rma = (prev_rma * (Decimal(length) - 1) + current_source) / Decimal(length)
                    rma_list.append(current_rma)
            
            return rma_list

        # AO 계산에 필요한 SMA 함수
        def sma_calc(source_series, length):
            S = len(source_series)
            sma_results = []
            
            # 초기 length-1개는 0으로 채움
            for _ in range(length - 1):
                sma_results.append(Decimal('0'))

            for i in range(length - 1, S):
                # 현재 막대를 포함하여 이전 length 기간의 데이터
                current_data = source_series[i - length + 1 : i + 1]
                sma_value = sum(current_data) / Decimal(length)
                sma_results.append(sma_value)
            return sma_results


        # --- Amazing Oscillator Calculation ---
        midpoint_price = [(h + l) / Decimal('2') for h, l in zip(H, L)]
        short_sma_series = sma_calc(midpoint_price, 5)
        long_sma_series = sma_calc(midpoint_price, 34)
        
        # AO 계산
        ao_series = [s - l for s, l in zip(short_sma_series, long_sma_series)]
        
        # ta.change(amazingOsc) 계산
        ao_change = [Decimal('0')]
        for i in range(1, N):
            ao_change.append(ao_series[i] - ao_series[i-1])

        # RMA 입력 데이터는 AO가 유효해지는 시점 (34번째 바)부터 사용해야 정확도가 높아짐
        # Pine Script의 RMA는 na를 건너뛰지만, 여기서 명시적으로 0을 처리하는 것이 Decimal 환경에서 안전함.
        # min_required_bars의 영향으로 rma_calc에서 이미 0으로 채워진 상태
        rma_start_index = 34 - 1 
        # math.max(ta.change(amazingOsc), 0)
        rise_source = [max(c, Decimal('0')) for c in ao_change] 
        # -math.min(ta.change(amazingOsc), 0)
        fall_source = [-min(c, Decimal('0')) for c in ao_change]

        # ta.rma(source, osc_period)
        rise_rma_series = rma_calc(rise_source, osc_period)
        fall_rma_series = rma_calc(fall_source, osc_period)
        
        # CustomRSI 계산
        custom_rsi_series = []
        for rise, fall in zip(rise_rma_series, fall_rma_series):
            
            if rise == Decimal('0') and fall == Decimal('0'):
                rsi_val = Decimal('50') 
            elif fall == Decimal('0'):
                rsi_val = Decimal('100')
            elif rise == Decimal('0'):
                rsi_val = Decimal('0')
            else:
                # 100 - (100 / (1 + rise / fall))
                rsi_val = Decimal('100') - (Decimal('100') / (Decimal('1') + rise / fall))
            
            custom_rsi = rsi_val - Decimal('50')
            custom_rsi_series.append(custom_rsi)


        # --- Duration Calculation (ta.barssince 시뮬레이션) ---
        
        # Decimal 기반 통계 함수
        def decimal_mean(data_list):
            if not data_list: return Decimal('0')
            return sum(data_list) / Decimal(str(len(data_list)))

        # 🚨 수정된 표준 편차 함수: 표본 표준 편차 (N-1로 나눔) 사용
        def decimal_stdev(data_list, mean_value):
            list_len = len(data_list)
            # 데이터가 2개 미만일 경우 0 반환
            if list_len < 2: return Decimal('0')
            
            squared_diff_sum = sum([(d - mean_value) ** 2 for d in data_list])
            # ❗ 모집단(N) 대신 표본(N-1)으로 나눔
            variance = squared_diff_sum / Decimal(str(list_len - 1)) 
            return variance.sqrt()

        
        durations = [] # 추세 지속 기간 리스트
        cut_series = [] # ta.barssince 결과 (크로스 이후 막대 수)
        
        # CustomRSI가 유효해지는 최소 인덱스 (AO 34 + RMA osc_period)
        min_valid_index = rma_start_index + osc_period
        
        for i in range(N):
            current_rsi = custom_rsi_series[i]
            prev_rsi = custom_rsi_series[i-1] if i > 0 else Decimal('0')

            # ta.cross(customRSI, 0)
            is_cross = (current_rsi >= Decimal('0') and prev_rsi < Decimal('0')) or \
                       (current_rsi <= Decimal('0') and prev_rsi > Decimal('0'))

            prev_cut = cut_series[-1] if cut_series else Decimal('0')
            
            current_cut = Decimal('0')
            if is_cross:
                current_cut = Decimal('0') # 크로스 발생 -> 리셋
            elif i < min_valid_index:
                current_cut = Decimal('0') # RSI 무효 기간
            else:
                current_cut = prev_cut + Decimal('1') # 크로스가 없으면 1 증가
            
            cut_series.append(current_cut)

            # Pine Script: if cut == 0 and cut != cut[1]: durations.unshift(cut[1])
            # current_cut == 0 (크로스) 이고 prev_cut > 0 (이전 추세가 있었음) 일 때
            if current_cut == Decimal('0') and prev_cut > Decimal('0'):
                durations.insert(0, prev_cut) 
                
        # --- Probability Calculation ---

        latest_cut = cut_series[-1] 
        
        if len(durations) < 2: 
            return Decimal('0.5'), latest_cut, Decimal('0'), Decimal('0'), custom_rsi_series[-1], 'GRAY', Decimal('0')

        # 🚨 수정된 decimal_stdev 함수 사용
        basis = decimal_mean(durations)
        stdev = decimal_stdev(durations, basis)
        
        # --- f_cdf (Cumulative Distribution Function) ---
        def f_cdf(z):
            a1 = Decimal('0.254829592')
            a2 = Decimal('-0.284496736')
            a3 = Decimal('1.421413741')
            a4 = Decimal('-1.453152027')
            a5 = Decimal('1.061405429')
            p = Decimal('0.3275911')
            
            sign = Decimal('-1') if z < Decimal('0') else Decimal('1')
            SQRT_TWO = Decimal('2').sqrt() 
            x = abs(z) / SQRT_TWO
            t = Decimal('1') / (Decimal('1') + p * x)
            
            x_squared_float = float(x ** 2)
            erf_approx = Decimal('1') - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Decimal(str(math.exp(-x_squared_float)))

            return Decimal('0.5') * (Decimal('1') + sign * erf_approx)

        if stdev == Decimal('0'):
            probability = Decimal('1') if latest_cut >= basis else Decimal('0')
        else:
            z = (latest_cut - basis) / stdev
            probability = f_cdf(z)

        # --- 캔들 색상 및 투명도 계산 ---
        
        latest_custom_rsi = custom_rsi_series[-1]
        prev_custom_rsi = custom_rsi_series[-2] if len(custom_rsi_series) >= 2 else Decimal('0')

        up_color_hex = '#00ffbb'
        down_color_hex = '#ff1100'

        if latest_custom_rsi > Decimal('0'):
            bar_color = up_color_hex
        else:
            bar_color = down_color_hex

        # 가속 조건
        is_accelerating = (latest_custom_rsi > Decimal('0') and latest_custom_rsi > prev_custom_rsi) or \
                          (latest_custom_rsi < Decimal('0') and latest_custom_rsi < prev_custom_rsi)

        if is_accelerating:
            opacity = Decimal('30') # 밝은 색 (가속)
        else:
            opacity = Decimal('80') # 어두운 색 (감속/조정)
        
        # 🚨 디버그 로깅 추가 (이전 응답에서 누락된 경우)
        logger.info(f"--- Reversal Probability Debug ---")
        logger.info(f"Latest Cut (Duration): {latest_cut}")
        logger.info(f"Basis (Avg Duration): {basis}")
        logger.info(f"StDev (N-1): {stdev}")
        logger.info(f"Z-Score: {(latest_cut - basis) / stdev if stdev > 0 else 'N/A'}")
        logger.info(f"Final Probability: {probability}")
        logger.info(f"Durations Array (Latest is index 0): {durations}")
        logger.info(f"----------------------------------")
        
        return probability, latest_cut, basis, stdev, latest_custom_rsi, bar_color, opacity
