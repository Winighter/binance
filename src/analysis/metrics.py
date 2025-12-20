import logging
from decimal import Decimal, getcontext
import math

logger = logging.getLogger("METRICS")

getcontext().prec = 50


class Metrics():

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
