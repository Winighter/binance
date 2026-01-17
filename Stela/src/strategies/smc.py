import logging
from decimal import Decimal
from typing import List, Tuple
from .base_strategy import BaseStrategy
from ..strategies.trading_params import SWING_LOOKBACK

logger = logging.getLogger("STRATEGIES")

class SmartMoneyConcept(BaseStrategy):
    def __init__(self):
        super().__init__()

    def identify_swing_point(self, lookback: int = SWING_LOOKBACK) -> List:
        if lookback < 1:
            raise ValueError(f"lookback minimum value is 1. input value is {lookback}")

        highs = [Decimal(str(x)) for x in self.highs]
        lows = [Decimal(str(x)) for x in self.lows]

        # 2️⃣ 스윙 후보 찾기
        swing_candidates = []
        for i in range(lookback, len(lows) - lookback):
            if lows[i] == min(lows[i - lookback : i + lookback + 1]):
                swing_candidates.append(("LOW", i, lows[i]))

            if highs[i] == max(highs[i - lookback : i + lookback + 1]):
                swing_candidates.append(("HIGH", i, highs[i]))

        # 3️⃣ 시간순 정렬 및 필터링
        swing_candidates.sort(key=lambda x: x[1])

        filtered_swings = []
        for swing in swing_candidates:
            swing_type, idx, price = swing
            if not filtered_swings:
                filtered_swings.append(swing)
                continue

            last_type, last_idx, last_price = filtered_swings[-1]
            if swing_type == last_type:
                if swing_type == "HIGH" and price > last_price:
                    filtered_swings[-1] = swing
                elif swing_type == "LOW" and price < last_price:
                    filtered_swings[-1] = swing
            else:
                filtered_swings.append(swing)

        return filtered_swings

    def analyze(self):
        swing_points = self.identify_swing_point()
        return self.analyze_liquidity_sweep(swing_points)

    def analyze_liquidity_sweep(self, swing_point: List) -> Tuple:

        highs = [Decimal(str(x)) for x in self.highs]
        lows = [Decimal(str(x)) for x in self.lows]
        opens = [Decimal(str(x)) for x in self.opens]
        closes = [Decimal(str(x)) for x in self.closes]

        swing_low_dict = {}
        swing_high_dict = {}
        short_signal = {}
        long_signal = {}

        high_index = 0

        # ... (이하 로직은 기존과 동일) ...
        for i in range(1, len(swing_point)):
            sp_value = swing_point[i]
            sType = sp_value[0]
            sIndex = sp_value[1]

            if sType == "HIGH":
                if sIndex not in list(swing_high_dict.keys()):
                    swing_high_dict.update({sIndex: None})

                if swing_high_dict != {}:
                    for high_index in swing_high_dict:
                        if high_index < sIndex and swing_high_dict[high_index] == None and \
                            highs[high_index] < highs[sIndex]:
                            swing_high_dict.update({high_index:sIndex})

            elif sType == "LOW":
                if sIndex not in list(swing_low_dict.keys()):
                    swing_low_dict.update({sIndex: None})

                if swing_low_dict != {}:
                    for low_index in swing_low_dict:
                        if low_index < sIndex and swing_low_dict[low_index] == None and \
                            lows[low_index] > lows[sIndex]:
                            swing_low_dict.update({low_index:sIndex})

        # 신호 구성
        for key in list(swing_low_dict.keys()):
            value = swing_low_dict[key]
            if value:
                longSignalIndex = value+SWING_LOOKBACK
                if longSignalIndex not in list(long_signal.keys()):
                    long_signal.update({longSignalIndex:[lows[value], closes[longSignalIndex], None]})
                    # logger.info(f"[{len(lows)-key}-{len(lows)-longSignalIndex+SWING_LOOKBACK}] | SL: {lows[value]} | Entry: {closes[longSignalIndex]}")

        for key in list(swing_high_dict.keys()):
            value = swing_high_dict[key]
            if value:
                shortSignalIndex = value+SWING_LOOKBACK
                if shortSignalIndex not in list(short_signal.keys()):
                    short_signal.update({shortSignalIndex:[highs[value], closes[shortSignalIndex], None]})
                    # logger.info(f"[{len(lows)-key}-{len(lows)-shortSignalIndex+SWING_LOOKBACK}] | SL: {highs[value]} | Entry: {closes[shortSignalIndex]}")

        return long_signal, short_signal
