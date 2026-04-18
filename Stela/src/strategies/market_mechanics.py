import logging
from ..shared.typings import *
from .base_strategy import BaseStrategy
from .trading_params import SWING_LOOKBACK
from collections import defaultdict
import numpy as np
from ..shared.errors import *
from src.shared.utils import *
from ..shared.enums import PositionSide, OrderSignal, UserDataEventType, AssetType, UserDataEventReasonType


logger = logging.getLogger("STRATEGIES")

class MarketMechanics(BaseStrategy):

    def __init__(self):
        super().__init__()

    @staticmethod
    def analyze_premium_discount(start_price, end_price):
        '''
        Wait for price to pullback to Discount / Premium
        '''
        max_price = max(start_price, end_price)
        min_price = min(start_price, end_price)
        return min_price + ((max_price - min_price) * 0.5)

    @staticmethod
    def match_sub_candles(target_ts: int, lower_ts_list: np.ndarray, count: int = 4):
        try:
            # 이진 탐색으로 타겟 타임스탬프의 시작 인덱스 찾기
            idx = np.searchsorted(lower_ts_list, int(target_ts))
            
            # 인덱스 범위를 벗어나거나 타임스탬프가 정확히 일치하지 않는 경우 예외 처리
            if idx >= len(lower_ts_list) or lower_ts_list[idx] != target_ts:
                return None

            # 슬라이싱으로 필요한 '인덱스' 범위 계산
            end_idx = min(idx + count, len(lower_ts_list))
            indices = np.arange(idx, end_idx)

            # 요청한 count만큼의 데이터가 확보되지 않은 경우 (데이터 끝 부분)
            if len(indices) < count:
                return None

            # 가격 데이터(lower_data_list)를 zip으로 묶지 않고 인덱스 리스트만 반환
            return indices.tolist()

        except Exception as e:
            logger.error(f"Error in match_sub_candles: {e}")
            return None

    @staticmethod
    def identify_market_structure(highs:List, lows:List, closes:List, lookback:int):

        # Swing Points
        swing_points = MarketMechanics.identify_swing_points(highs, lows, lookback, False)

        # Swing Points & BOS
        result = MarketMechanics.identify_break_of_structure(closes, swing_points, lookback, False)

        return result

    @staticmethod
    def identify_swing_points(highs:List, lows:List, lookback:int, showLog:bool = False) -> List[Tuple]:
        '''
        완벽한 함수
        '''
        tl = len(lows)
        swing_points:List[Tuple] = []

        for i in range(lookback, tl - lookback):

            low = lows[i]
            high = highs[i]

            swing_lows = lows[i - lookback : i + lookback + 1]
            swing_highs = highs[i - lookback : i + lookback + 1]

            swing_low_index = int(np.argmin(swing_lows))
            swing_high_index = int(np.argmax(swing_highs))

            if lookback == swing_low_index:
                swing_points.append(('LOW', i, low))

            if lookback == swing_high_index:
                swing_points.append(('HIGH', i, high))

        if showLog:
            for side, index, price in swing_points:
                logger.info(f"[SP-{side}] {tl-index} {price}")

        return swing_points

    @staticmethod
    def identify_break_of_structure(closes:List, swing_points:List[Tuple], lookback:int, showLog:bool = False) -> List[Tuple]:
        '''
        완벽한 함수
        '''
        tl = len(closes)
        bos:List[Tuple] = []

        for side, index, price in swing_points:
            bos_index = None
            for i in range(index + lookback + 1, tl):
                close = closes[i]
                if (side == 'LOW' and price > close) or (side == 'HIGH' and price < close):
                    bos_index = i
                    break

            bos.append((side, index, price, bos_index))

        if showLog:
            for side, index, price, bos_index in bos:
                if bos_index:
                    bos_index = tl - bos_index
                logger.info(f"{side, tl-index, price, bos_index}")

        return bos

    @staticmethod
    def identify_swing_range(highs:List, lows:List, closes:List, showLog:bool = False, lookback:int = 3):

        # With BOS
        swing_points = MarketMechanics.identify_market_structure(highs, lows, closes, lookback)

        tl = len(lows)

        first = []
        second = []
        third = []
        four = []
        fives = []
        six = []
        eight = []

        grouped_results = defaultdict(list)
        grouped_results2 = defaultdict(list)

        swing_range:List[Tuple[str, int, int, int, int]] = []

        for side, index, price, bos_index in swing_points:

            if bos_index:

                for side2, index2, price2, bos_index2 in swing_points:

                    if side == side2 and bos_index <= index2:

                        first.append((side, index, index2))
                        break

        for side, index, end in first:

            for side2, index2, price2, bos_index2 in swing_points:

                if side != side2 and index < index2 < end:
                    second.append((side, index, index2, end))
        
        for side, index, start, end in second:

            for i in range(start + lookback + 1, end):

                high = highs[i]
                low = lows[i]

                if (side == 'HIGH' and lows[start] > low) or (side == 'LOW' and highs[start] < high):
                    break

                if i == end - 1:
                    grouped_results[(side, index, end)].append(start)
                    third.append((side, index, start, end))

        four = [(key[0], key[1], key[2], values) for key, values in grouped_results.items()]

        for side, index, end, start_values in four:

            if len(start_values) > 1:

                if side == 'HIGH':
                    swing_low_prices = [lows[i] for i in start_values]
                    swing_low_index = start_values[np.argmin(swing_low_prices)]
                    fives.append((side, index, swing_low_index, end))

                if side == 'LOW':
                    swing_high_prices = [highs[i] for i in start_values]
                    swing_high_index = start_values[np.argmax(swing_high_prices)]
                    fives.append((side, index, swing_high_index, end))

            elif len(start_values) == 1:
                fives.append((side, index, start_values[0], end))

        for side, index, start, end in fives:

            data = (side, start, end, end + lookback)

            if data not in six:
                six.append(data)
        
        for side, start, end, end_confirm in six:

            invalid_index = tl - 1

            for i in range(end + lookback + 1, tl):

                close = closes[i]

                if (side == 'HIGH' and lows[start] > close) or (side == 'LOW' and highs[start] < close) or \
                    (side == 'HIGH' and highs[end] < close) or (side == 'LOW' and lows[end] > close):
                    invalid_index = i
                    break

            grouped_results2[(side, end, end_confirm, invalid_index)].append(start)
        
        seven = [(key[0], key[1], key[2], key[3], values) for key, values in grouped_results2.items()]

        seven = sorted(seven, key=lambda x: x[2])

        for side, end, end_confirm, invalid_index, start_values in seven:

            if len(start_values) > 1:

                if side == 'HIGH':
                    swing_low_prices = [lows[i] for i in start_values]
                    swing_low_index = start_values[np.argmin(swing_low_prices)]
                    eight.append((side, swing_low_index, end, end_confirm, invalid_index))

                elif side == 'LOW':
                    swing_high_prices = [highs[i] for i in start_values]
                    swing_high_index = start_values[np.argmax(swing_high_prices)]
                    eight.append((side, swing_high_index, end, end_confirm, invalid_index))

            elif len(start_values) == 1:
                eight.append((side, start_values[0], end, end_confirm, invalid_index))

            else:
                logger.info(f"Invalid Start Length: {len(start_values)}")

        swing_range = sorted(eight, key=lambda x: x[2])

        if showLog:

            for side, start, end, end_confirm, invalid_index in swing_range:

                logger.info(f"[HTF {side}] Start: {tl-start}, End: {tl-end}, End Confirm: {tl-end_confirm}, Invalid: {tl-invalid_index}")

        return swing_range

    def analyze(self):

        '''
        Market Mechanics
        아래와 같은 핵심으로 구성되어 있다.
        - Mechanical Market Structure. ex) Swing Structure, Internal, Fractal...
        - Institutional Zones = POI ex) OB, Flip Zone, Sweep Zone, D & S Zone
        - LQ Concept ex) Inducement, Low Resistance LQ, High Resistance LQ, Push & Pull Inducement
        - Order Flow
        - Time: 거래하기 가장 좋은 시간 ex) Q Zone, London Q Zone or Newyork Q zone

        1. HTF 은 전반적인 혹은 전체적인 추세 방향 확인
        1-1. BOS 확인해서 스윙 고점-저점 찾아서 범위 찾기
        2. MTF 은 POI 찾기
        3. LTF 은 진입 모델을 찾고 진입 확인 등 진입에 관련된 것
        즉 결국엔 긴 상위 프레임부터 시작해야 한다.

        A+ Setup Filter
        
        '''

        htf_timestamps = self.htf_timestamps
        htf_opens = self.htf_opens
        htf_highs = self.htf_highs
        htf_lows = self.htf_lows
        htf_closes = self.htf_closes

        mtf_timestamps = self.mtf_timestamps
        mtf_opens = self.mtf_opens
        mtf_highs = self.mtf_highs
        mtf_lows = self.mtf_lows
        mtf_closes = self.mtf_closes

        ltf_timestamps = self.ltf_timestamps
        ltf_opens = self.ltf_opens
        ltf_highs = self.ltf_highs
        ltf_lows = self.ltf_lows
        ltf_closes = self.ltf_closes

        self.htf_timestamps = htf_timestamps
        self.mtf_highs = mtf_highs
        self.mtf_lows = mtf_lows
        self.mtf_timestamps = mtf_timestamps
        self.ltf_timestamps = ltf_timestamps
        self.htf_tl = len(htf_lows)
        self.mtf_tl = len(mtf_lows)

        # 타임스탬프로 캔들의 가장 처음과 끝의 시간
        # logger.info(f"HTF: {((htf_timestamps[-1] - htf_timestamps[0]) / 86400000):.2f} Days")
        # logger.info(f"MTF: {((mtf_timestamps[-1] - mtf_timestamps[0]) / 86400000):.2f} Days")
        # logger.info(f"LTF: {((ltf_timestamps[-1] - ltf_timestamps[0]) / 86400000):.2f} Days")
        # self.total_days = ((ltf_timestamps[-1] - ltf_timestamps[0]) / 86400000)

        # # 1. Trend Direction
        # swing_range = MarketMechanics.identify_swing_range(htf_highs, htf_lows, htf_closes, False)

        # 2. POI
        POIs = self.identify_points_of_interest(None, mtf_highs, mtf_lows, mtf_closes, False)

        signals = self.analyze_signal(ltf_opens, ltf_highs, ltf_lows, ltf_closes,  POIs, False)

        return signals

    def indentify_liquidity_sweep_poi(self, pois, highs, lows):

        liquidity_poi = []
        
        pois = sorted(pois, key=lambda x: x[1])

        for poi_side, poi_index, bos_index in pois:

            poi_high = highs[poi_index]
            poi_low  = lows[poi_index]

            available_lq_indexes = []

            for i in reversed(range(1, poi_index - 1)):

                low = lows[i]
                high = highs[i]

                if poi_side == 'DEMAND':

                    swing_lows = lows[i - 1 : i + 2]
                    swing_low_index = int(np.argmin(swing_lows))
                    
                    # Invalid LQ Index
                    if low < poi_low:
                        break

                    if poi_low < low < poi_high and swing_low_index == 1:
                        available_lq_indexes.append(i)

                if poi_side == 'SUPPLY':

                    swing_highs = highs[i - 1 : i + 2]
                    swing_high_index = int(np.argmax(swing_highs))

                    # Invalid LQ Index
                    if high > poi_high:
                        break

                    if poi_low < high < poi_high and swing_high_index == 1:
                        available_lq_indexes.append(i)
            
            if available_lq_indexes:
                lq_poi = (poi_side, poi_index, bos_index)
                if lq_poi not in liquidity_poi:
                    liquidity_poi.append(lq_poi)

        liquidity_poi = sorted(liquidity_poi, key= lambda x: x[2])

        return liquidity_poi

    def identify_points_of_interest(self, swing_range, highs, lows, closes, showLog:bool = False, lookback:int = 1):

        '''
        High Probability Zone

        0. BOS (Break of Structure)
        1. Unmitigated
        3. 
        '''
        # 1. Depth : 가격이 POI에서 완전히 벗어난경우 유효한 POI로 보지 않는다.
        # 2. Premium / Discount : POI와 해당 POI에 가격이 포함됬을때 종가 모두 적절한 P/D 에 위치한 경우
        tl = len(lows)

        POIs = []
        ms_poi = []

        market_structure = MarketMechanics.identify_market_structure(highs, lows, closes, lookback)

        for side, index, _, bos_index in market_structure:

            if bos_index:

                match side:

                    case 'HIGH':
                        swing_lows = lows[index : bos_index + 1]
                        min_val = np.min(swing_lows)
                        indices = np.where(swing_lows == min_val)[0]
                        swing_low_index = indices[-1]
                        poi_index = index + swing_low_index

                    case 'LOW':
                        swing_highs = highs[index : bos_index + 1]
                        max_val = np.max(swing_highs)
                        indices = np.where(swing_highs == max_val)[0]
                        swing_high_index = indices[-1]
                        poi_index = index + swing_high_index

                if index < poi_index < bos_index:

                    match side:

                        case 'HIGH':
                            data = ('DEMAND', poi_index, bos_index)
                            ms_poi.append(data)

                        case 'LOW':
                            data = ('SUPPLY', poi_index, bos_index)
                            ms_poi.append(data)

        # Sort ms_poi
        ms_poi = sorted(ms_poi, key=lambda x: x[2])

        # liquidity_poi = self.indentify_liquidity_sweep_poi(ms_poi, highs, lows)

        # MTF CONDITION (Mitigate)
        for poi_side, poi_index, bos_index in ms_poi:

            poi_high = highs[poi_index]
            poi_low = lows[poi_index]

            mitigation_check = False
            mitigation_index = None
            invalid_index = tl - 1

            for i in range(poi_index + 1, tl):

                current_high = highs[i]
                current_low = lows[i]
                current_close = closes[i]

                match poi_side:

                    case 'DEMAND':

                        if mitigation_check:
                            
                            if not mitigation_index and poi_high > current_low:
                                if bos_index <= i:
                                    mitigation_index = i

                        elif not mitigation_check:

                            if bos_index <= i and poi_high < current_close:
                                mitigation_check = True

                        if lows[poi_index] > current_low:
                            invalid_index = i
                            break

                    case 'SUPPLY':

                        if mitigation_check:

                            if not mitigation_index and poi_low < current_high:
                                if bos_index <= i:
                                    mitigation_index = i

                        elif not mitigation_check:

                            if bos_index <= i and poi_low > current_close:
                                mitigation_check = True
                        
                        if highs[poi_index] < current_high:
                            invalid_index = i
                            break

            if mitigation_index:
                data = (poi_side, poi_index, mitigation_index, invalid_index)
                if data not in POIs:
                    POIs.append(data)

        # Sorted
        POIs = sorted(POIs, key=lambda x: x[2])

        if showLog:
            for poi_side, poi_index, poi_miti_index, poi_invalid_idx in POIs:
                logger.info(f"[{poi_side}] {tl-poi_index} {tl - poi_miti_index} {tl-poi_invalid_idx}")

        return POIs

    def analyze_liquidity_sweep(self, highs, lows, lookback = 1, showLog:bool = False):

        tl = len(lows)
        result = []
        swing_point = self.identify_swing_points(highs, lows, lookback)

        for side, index, price in swing_point:

            for i in range(index + lookback + 1, tl):

                low = lows[i]
                high = highs[i]

                if (side == 'LOW' and price > low) or (side == 'HIGH' and price < high):

                    result.append((side, index, i))
                    break

        # result = sorted(result, key= lambda x : x[2])

        if showLog:
            for side, index, i in result:
                logger.info(f"[LQ-SWEEP {side}] {tl-index} -> {tl-i}")

        return result

    def analyze_signal(self, opens, highs, lows, closes, POIs:List, showLog:bool = False, lookback:int = 2) -> List[Tuple]:
        '''
        Entry Criteria
        1. MTF POI Respect (MTF POI Bounce Confirm) : O
        2. During Killzone (London, New york, Overlap) 진입 : O | 세션이라도 주말은 실제로 휴장이라서 거래량이 줄어드는 경우가 있지만 추후에 확인하는 걸로 지금 당장 중요 X
        3. Premium / Discount 진입 : X
        4. 유동성 스윕 (처음엔 선택이라 생각했지만 확인해본 결과 절대적으로 필수임을 확인함) : X
        '''
        tl = len(lows)

        if type(lookback) is not int:
            raise TypeError(f'lookback parameter is not int, Current lookback type: {type(lookback).__name__}')

        execute_signals:List[Tuple] = []
        grouped_results = defaultdict(list)

        lq_sweep_data = self.analyze_liquidity_sweep(highs, lows)

        l_poi_side, l_poi_index, l_poi_mitigate_value, l_poi_invalid_idx = POIs[-1]

        logger.info(f"[{l_poi_side}] Index: {self.mtf_tl-l_poi_index}, Miti: {self.mtf_tl-l_poi_mitigate_value}, Invalid: {self.mtf_tl-l_poi_invalid_idx}")

        for poi_side, poi_index, poi_mitigate_value, poi_invalid_idx in POIs:

            check_value = False

            poi_mitigated_ltf_index = MarketMechanics.match_sub_candles(self.mtf_timestamps[poi_mitigate_value], self.ltf_timestamps, 12)[-1]
            invalid_ltf_idx = MarketMechanics.match_sub_candles(self.mtf_timestamps[poi_invalid_idx], self.ltf_timestamps, 12)[-1]

            poi_high = self.mtf_highs[poi_index]
            poi_low = self.mtf_lows[poi_index]

            # logger.info(f"[{poi_side}] POI: {self.mtf_tl-poi_index} Miti: {self.mtf_tl-poi_mitigate_value} Invalid: {self.mtf_tl-poi_invalid_idx}")

            for lq_side, av_lq, sweep_lq in lq_sweep_data:

                if poi_mitigated_ltf_index <= sweep_lq <= invalid_ltf_idx:

                    is_session = 'Asia' != get_session_label(self.ltf_timestamps[sweep_lq])[0]

                    if is_session:

                        if (poi_side == 'DEMAND' and lq_side == 'LOW'):
                            
                            if not check_value and poi_high > lows[sweep_lq]:
                                check_value = True

                            long_data = (PositionSide.LONG, sweep_lq, closes[sweep_lq], poi_low, None, check_value)
                            if showLog:
                                logger.info(f"[{poi_side} {self.mtf_tl-poi_index}] Miti: {self.mtf_tl-poi_mitigate_value}, Invalid: {self.mtf_tl-poi_invalid_idx} | "
                                        f'[LQ-SWEEP] LTF Miti: {tl-poi_mitigated_ltf_index} LQ: {tl-av_lq}, Sweep: {tl-sweep_lq}'
                                        )

                            if long_data not in execute_signals:
                                execute_signals.append(long_data)
                            break

                        if (poi_side == 'SUPPLY' and lq_side == 'HIGH'):

                            if not check_value and poi_low > highs[sweep_lq]:
                                check_value = True

                            short_data = (PositionSide.SHORT, sweep_lq, closes[sweep_lq], poi_high, None, check_value)
                            if showLog:
                                logger.info(f"[{poi_side} {self.mtf_tl-poi_index}] Miti: {self.mtf_tl-poi_mitigate_value}, Invalid: {self.mtf_tl-poi_invalid_idx} | "
                                        f'[LQ-SWEEP] LTF Miti: {tl-poi_mitigated_ltf_index} LQ: {tl-av_lq}, Sweep: {tl-sweep_lq}'
                                        )
                            if short_data not in execute_signals:
                                execute_signals.append(short_data)
                            break

        execute_signals = sorted(execute_signals, key=lambda x: x[1])

        execute_signals2 = []

        # 최적의 POI 손절가로 맞추기
        for side, index, entry, stop_loss, take_profit, check_value in execute_signals:

            grouped_results[(side, index, check_value)].append(stop_loss)

        four = [(key[0], key[1], values, key[2]) for key, values in grouped_results.items()]

        for side, signal_index, stop_loss_values, check_value in four:
            # 1.
            # new_stop_loss = stop_loss_values[0]

            # 2.
            if len(stop_loss_values) > 1:
                new_stop_loss = min(stop_loss_values) if side.value == 'LONG' else max(stop_loss_values)
            else:
                new_stop_loss = stop_loss_values[0]

            execute_signals2.append((side, signal_index, closes[signal_index], new_stop_loss, None, check_value))

        # if showLog:
        #     # logger.info(f"{(len(execute_signals2) / self.total_days):.2f}") # 일 평균 거래 신호 횟수

        #     for side, index, entry, stop_loss, take_profit, check_value in execute_signals2:

        #         logger.info(f"[{side.value} SIGNAL] {tl-index} | Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")

        return execute_signals2