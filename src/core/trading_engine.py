import logging
from typing import List, Tuple, Deque, Dict
from decimal import Decimal
import settings as app_config
from collections import deque
from binance.exceptions import BinanceAPIException
from ..shared.state_manager import PositionState
from ..shared.enums import OrderSide, PositionSide, OrderSignal
from ..shared.errors import MARGIN_INSUFFICIENT_CODE, BinanceClientException
from ..config import *
from decimal import Decimal, getcontext
from ..api.binance_setup_manager import BinanceSetupManager
logger = logging.getLogger("TRADING_ENGINE")

class TradingEngine:

    def __init__(self, binance_client, trading_manager, positions:PositionState, leverage:Decimal,
                symbol: str, ohlc_prices:List[List[Decimal]]):
        self.symbol = symbol
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = positions
        self.open_prices = deque([item[0] for item in ohlc_prices], maxlen=KLINE_LIMIT)
        self.high_prices = deque([item[1] for item in ohlc_prices], maxlen=KLINE_LIMIT)
        self.low_prices = deque([item[2] for item in ohlc_prices], maxlen=KLINE_LIMIT)
        self.close_prices = deque([item[3] for item in ohlc_prices], maxlen=KLINE_LIMIT)
        self.leverage = Decimal(str(leverage))

        self.swing_high = Decimal('0')
        self.swing_low = Decimal('0')
        self.swing_high_prev = Decimal('0')
        self.swing_low_prev = Decimal('0')
        self.sh_msg = ""
        self.sl_msg = ""
        self.swing_turn = ""
        # ⭐️ ZigZag 상태 관리를 위한 변수 초기화 ⭐️
        self.trend = 1                  # 현재 추세: 1=상승, -1=하락 (Pine Script의 초기값)
        self.high_points_arr = []       # 확정된 스윙 하이 가격 배열
        self.high_index_arr = []        # 확정된 스윙 하이 인덱스 배열
        self.low_points_arr = []        # 확정된 스윙 로우 가격 배열
        self.low_index_arr = []         # 확정된 스윙 로우 인덱스 배열
        # 현재 진행 중인 추세의 최고/최저점 및 인덱스 추적 (핵심 수정)
        self.current_trend_high = Decimal('0')
        self.current_trend_high_index = 0
        self.current_trend_low = Decimal('0')
        self.current_trend_low_index = 0
        self.is_initialized_swing = False # 초기화 여부 플래그
        # ⭐️ 시장 구조 연속성 추적 변수 ⭐️

        self.is_high_rising = False    # 고점 상승 (HH) 여부. False면 LH/EH (하락/동일)
        self.is_low_rising = False     # 저점 상승 (HL) 여부. False면 LL/EL (하락/동일)
        # ----------------------------------------------
        self.high_msg = ""
        self.low_msg = ""
        self.high1_msg = ""
        self.low1_msg = ""
        self.high2_msg = ""
        self.low2_msg = ""
        self.first_stream_data = None
        self.balance = None
        self.available_balance = None

        self.initialize_bot_state()
        self.update_balance()
        self.identify_liquidity()
    #######################################################################################################################

    def analysis_fibonacci_retracement(self, start:Decimal, end:Decimal) -> Dict:
        '''
        Fibonacci Retracement Function
        Fibonacci Start : Start Price
        End : End Price
        '''
        fb_gap = abs(start - end)

        a = fb_gap * Decimal('0.5') # 0.5
        a_price = Decimal('0.0000')

        if start > end:
            a_price = a + end

        elif start < end:
            a_price = a + start

        result = {'0.5': a_price}

        return result

    def update_candle_data(self, ohlc_data) -> Tuple[Deque[Decimal], Deque[Decimal], Deque[Decimal], Deque[Decimal]]:
        """
        Appends the latest OHLC (Open, High, Low, Close) data to the price deques.

        The function leverages the 'maxlen' property of collections.deque to 
        automatically manage the fixed-size lookback window (FIFO structure), 
        ensuring O(1) time complexity for data updates.

        Args:
            ohlc_data (dict): A dictionary containing the latest OHLC data 
                            (keys 'o', 'h', 'l', 'c').

        Returns:
            tuple: A tuple containing the updated (open_prices, high_prices, 
                low_prices, close_prices) deques.
        """
        # Append the new OHLC values. 
        # Using Decimal conversion ensures high precision for financial calculations.
        # The maxlen property automatically removes the oldest element (popleft) upon append.
        self.open_prices.append(Decimal(str(ohlc_data.get('o'))))
        self.high_prices.append(Decimal(str(ohlc_data.get('h'))))
        self.low_prices.append(Decimal(str(ohlc_data.get('l'))))
        self.close_prices.append(Decimal(str(ohlc_data.get('c'))))

        # Lookback Window Management is now handled automatically by deque's maxlen.
        # The previous O(N) checking and pop(0) logic is safely removed.

        # Return the final, updated, and fixed-size candle deques for indicator calculation.
        return self.open_prices, self.high_prices, self.low_prices, self.close_prices

    def identify_supply_demand_zond(self) -> Tuple[list, list]:
        """
        Identifies potential Supply and Demand zones based on momentum candles.
        
        Zone Definition Criteria:
        1. The current candle (i) must be a Momentum Candle, meeting the MINIMUM_REQUIRED_RATIO.
        2. The Zone is defined by the high and low of the previous candle (i-1), which acts as the 'Base' candle.
        
        For Long (Demand Zone Creation - Rally): 
        1. The current candle (i) is bullish (open < close).
        2. The current close > previous close (close > prev_close).
        3. The Demand Zone is defined by the High ~ Low of the previous candle (i-1).
        
        For Short (Supply Zone Creation - Drop): 
        1. The current candle (i) is bearish (open > close).
        2. The current close < previous close (close < prev_close).
        3. The Supply Zone is defined by the High ~ Low of the previous candle (i-1).
        """
        open_prices = list(self.open_prices)
        high_prices = list(self.high_prices)
        low_prices = list(self.low_prices)
        close_prices = list(self.close_prices)

        demand_zones = []
        supply_zones = []

        ol = len(open_prices)

        # Momentum Candle
        for i in range(1, ol):

            open = open_prices[i]
            high = high_prices[i]
            low = low_prices[i]
            close = close_prices[i]

            prev_high = high_prices[i-1]
            prev_low = low_prices[i-1]
            prev_close = close_prices[i-1]

            candle = high - low # Candle Size
            body = abs(open - close) # Candle Body Ratio

            if candle == 0:
                body_ratio = 0
            else:
                body_ratio = float((body / candle) * 100)
                body_ratio = round(body_ratio, 2)

            # Momentum Basic Conditions
            if body_ratio >= app_config.MINIMUM_REQUIRED_RATIO:

                # Long Momentum Conditions
                if open < close and close > prev_close:
                    demand_zones.append([ol-i, prev_high, prev_low])

                # Short Momentum Conditinos
                elif open > close and close < prev_close:
                    supply_zones.append([ol-i, prev_high, prev_low])

        return demand_zones, supply_zones

    def retest_price(self, rt_price:Decimal, side:PositionSide, barIndex:int = 1) -> bool:

        open_prices = list(self.open_prices)
        high_prices = list(self.high_prices)
        low_prices = list(self.low_prices)
        # close_prices = list(self.close_prices)

        if type(side) != PositionSide:
            raise TypeError(f"side type is only 'PositionSide. current type: {type(side)}")
        
        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side value is [PositionSide.LONG or PositionSide.SHORT] current value: {side}")

        if not (KLINE_LIMIT-1 > barIndex > 0):
            raise ValueError(f"barIndex minimum value is 1 and maximum value is {KLINE_LIMIT-2}, but your input value: {barIndex}")

        bIndex = len(open_prices)-barIndex

        if side == PositionSide.LONG:

            if rt_price <= low_prices[bIndex] and rt_price > low_prices[bIndex-1]:
                for i in range(barIndex+1, len(open_prices)-1):
                    reverse_index = len(open_prices) - i - 1
                    low = low_prices[reverse_index]
                    if low > rt_price:
                        # logger.info(f"{reverse_index} {low} Long retest Confirm")
                        return True

        elif side == PositionSide.SHORT:

            if rt_price >= high_prices[bIndex] and rt_price < high_prices[bIndex-1]:
                for i in range(barIndex+1, len(open_prices)-1):
                    reverse_index = len(open_prices) - i - 1
                    high = high_prices[reverse_index]
                    if high < rt_price:
                        # logger.info(f"{reverse_index} {high} Short retest Confirm")
                        return True
        return False

    def analysis_liquidity_grab(self, swing_points: List, showGrabLogger:bool = False) -> Tuple:

        '''
        Docstring for analysis_liquidity_grab
        
        :param self: Description
        :param swing_points: Description
        :type swing_points: List
        :param showGrabLogger: Description
        :type showGrabLogger: bool
        '''

        opens = list(self.open_prices)
        highs = list(self.high_prices)
        lows = list(self.low_prices)
        closes = list(self.close_prices)

        swing_low_dict = {}
        swing_high_dict = {}

        short_signal: Tuple[OrderSignal, Decimal] = OrderSignal.NO_SIGNAL, Decimal('0')
        long_signal: Tuple[OrderSignal, Decimal] = OrderSignal.NO_SIGNAL, Decimal('0')

        for i in range(1, len(swing_points)):

            sp_value = swing_points[i]
            sType = sp_value[0]
            sIndex = sp_value[1]

            if sType == "HIGH":
                if sIndex not in swing_high_dict.keys():
                    swing_high_dict.update({sIndex: None})

                if swing_high_dict != {}:
                    for high_index in swing_high_dict:
                        if high_index < sIndex and swing_high_dict[high_index] == None:
                            if highs[high_index] < highs[sIndex] and highs[high_index] > highs[sIndex+1] and highs[high_index] > highs[sIndex-1]:
                                if opens[sIndex] < closes[sIndex]:
                                    # if (highs[sIndex] - closes[sIndex]) > (opens[sIndex] - lows[sIndex]):
                                        if closes[sIndex] < highs[high_index]:
                                            swing_high_dict.update({high_index:sIndex})

                                elif opens[sIndex] > closes[sIndex]:
                                    # if highs[sIndex] - opens[sIndex] > closes[sIndex] - lows[sIndex]:
                                        if opens[sIndex] < highs[high_index]:
                                            swing_high_dict.update({high_index:sIndex})

            elif sType == "LOW":
                if sIndex not in swing_low_dict.keys():
                    swing_low_dict.update({sIndex: None})

                if swing_low_dict != {}:
                    for low_index in swing_low_dict:
                        if low_index < sIndex and swing_low_dict[low_index] == None:
                            if lows[low_index] > lows[sIndex] and lows[low_index] < lows[sIndex+1] and lows[low_index] < lows[sIndex-1]:
                                if opens[sIndex] < closes[sIndex]:
                                    # if (highs[sIndex] - closes[sIndex]) < (opens[sIndex] - lows[sIndex]):
                                        if opens[sIndex] > lows[high_index]:
                                            swing_low_dict.update({low_index:sIndex})

                                elif opens[sIndex] > closes[sIndex]:
                                    # if highs[sIndex] - opens[sIndex] < closes[sIndex] - lows[sIndex]:
                                        if closes[sIndex] > lows[low_index]:
                                            swing_low_dict.update({low_index:sIndex})
        # Remove Wrong Signal
        for key in swing_low_dict:
            value = swing_low_dict[key]
            if value:
                for i in range(key,value):
                    low = lows[i]
                    grab_low = lows[key]
                    if key < i < value and low < grab_low:
                        swing_low_dict.update({key:None})
                        break
        for key in swing_high_dict:
            value = swing_high_dict[key]
            if value:
                for i in range(key,value):
                    high = highs[i]
                    grab_high = highs[key]
                    if key < i < value and high > grab_high:
                        swing_high_dict.update({key:None})
                        break

        if showGrabLogger:
            logger.info(f"")
        for key in swing_high_dict:
            value = swing_high_dict[key]
            if value:
                if len(lows)-value == 3:
                    short_signal = OrderSignal.OPEN_POSITION, highs[value]
                if showGrabLogger:
                    logger.info(f"HIGH [{len(lows)-key}-{len(lows)-value}] {highs[key]}-{highs[value]}")

        for key in swing_low_dict:
            value = swing_low_dict[key]
            if value:
                if len(lows)-value == 3:
                    long_signal = OrderSignal.OPEN_POSITION, lows[value]
                if showGrabLogger:
                    logger.info(f"LOW [{len(lows)-key}-{len(lows)-value}] {lows[key]}-{lows[value]}")
        if showGrabLogger:
            logger.info(f"")

        return long_signal, short_signal

    def identify_swing_points(self, lookback: int = 2) -> List:

        if lookback < 1:
            raise ValueError(f"lookback minimum value is 1. input value is {lookback}")

        highs = list(self.high_prices)
        lows = list(self.low_prices)

        # 1️⃣ 스윙 후보 저장 (type, index, price)
        swing_candidates = []

        for i in range(lookback, len(lows) - lookback):

            low_window = lows[i - lookback : i + lookback + 1]
            high_window = highs[i - lookback : i + lookback + 1]

            if lows[i] == min(low_window):
                swing_candidates.append(("LOW", i, lows[i]))

            if highs[i] == max(high_window):
                swing_candidates.append(("HIGH", i, highs[i]))

        # 2️⃣ 시간순 정렬
        swing_candidates.sort(key=lambda x: x[1])

        # 3️⃣ HIGH / LOW 교차 + 연속 필터링
        filtered_swings = []

        for swing in swing_candidates:
            swing_type, idx, price = swing

            if not filtered_swings:
                filtered_swings.append(swing)
                continue

            last_type, last_idx, last_price = filtered_swings[-1]

            # ✅ 같은 타입이 연속될 경우
            if swing_type == last_type:
                if swing_type == "HIGH" and price > last_price:
                    filtered_swings[-1] = swing  # 더 높은 HIGH로 교체
                elif swing_type == "LOW" and price < last_price:
                    filtered_swings[-1] = swing  # 더 낮은 LOW로 교체
                # 나머지는 무시
            else:
                # ✅ 타입이 다르면 그대로 추가 (교차)
                filtered_swings.append(swing)

        return filtered_swings

    def update_balance(self):
        try:
            self.balance, self.available_balance = BinanceSetupManager._fetch_balance(self)
            logger.info(f"Balance successfully updated. Balance: {self.balance:.2f} Available balance: {self.available_balance:.2f}")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def initialize_bot_state(self):
        try:
            positions_info = self.binance_client.futures_position_information(self.symbol)
            if positions_info:
                for pos in positions_info:
                    if Decimal(pos['positionAmt']) != Decimal('0'):
                        position_side = pos['positionSide']
                        amount = Decimal(pos['positionAmt'])
                        entry_price = Decimal(pos['entryPrice'])
                        if position_side == PositionSide.LONG.value:
                            logger.info("Found an open LONG position during initialization.")
                            self.positions.long = entry_price
                            self.positions.long_amount = abs(amount)
                            self.positions.long_entry_price = entry_price

                        elif position_side == PositionSide.SHORT.value:
                            logger.info("Found an open SHORT position during initialization.")
                            self.positions.short = entry_price
                            self.positions.short_amount = abs(amount)
                            self.positions.short_entry_price = entry_price

            orders = self.binance_client.futures_get_all_orders()
            if orders:
                for order in orders:
                    if order['status'] == 'NEW':
                        order_side = order['side']
                        position_side = order['positionSide']
                        if order['type'] == 'STOP_MARKET':
                            if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                                self.positions.long_stop_loss_order_id = order['orderId']
                                self.positions.long_stop_loss = Decimal(order['stopPrice'])
                                logger.info(f"Found existing long stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")

                            elif position_side == PositionSide.SHORT.value and order_side == OrderSide.BUY.value:
                                self.positions.short_stop_loss_order_id = order['orderId']
                                self.positions.short_stop_loss = Decimal(order['stopPrice'])
                                logger.info(f"Found existing short stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")

                        if order['type'] == 'TAKE_PROFIT_MARKET':
                            if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                                self.positions.long_take_profit_order_id = order['orderId']
                                self.positions.long_take_profit = Decimal(order['stopPrice'])
                                logger.info(f"Found existing long stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")

                            elif position_side == PositionSide.SHORT.value and order_side == OrderSide.BUY.value:
                                self.positions.short_take_profit_order_id = order['orderId']
                                self.positions.short_take_profit = Decimal(order['stopPrice'])
                                logger.info(f"Found existing short stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")

        except Exception as e:
            logger.error(f"Failed to initialize bot state from Binance: {e}", exc_info=True)

    def _verify_order_and_state(self) -> bool:
        try:
            position_info = self.binance_client.futures_position_information(symbol=self.symbol)

            if (len(position_info) > 0 and (position_info[0]['positionSide'] == PositionSide.LONG.value) or (position_info[0]['positionSide'] == PositionSide.SHORT.value)):
                logger.info("CONFIRMATION: A new position was successfully opened despite the API error.")
                self.initialize_bot_state() 
                return True

            open_orders = self.binance_client.futures_get_all_orders(symbol=self.symbol)
            if len(open_orders) > 0:
                logger.info(f"CONFIRMATION: There are {len(open_orders)} open orders. The order might still be processing.")
                return True

            logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely.")
            return False

        except BinanceClientException as e:
            logger.critical(f"FATAL: Failed to verify order status due to a critical API error. Error: {e}")
            return False
        
        except Exception as e:
            logger.critical(f"FATAL: Unexpected error during order verification: {e}", exc_info=True)
            return False

    #######################################################################################################################

    def _adjust_quantity_by_precision(self, symbol: str, quantity: Decimal) -> Decimal:
        precision = self._get_quantity_precision(symbol)
        if precision is not None:
            getcontext().prec = 28  # 높은 정밀도로 설정
            quantizer = Decimal('1e-{}'.format(precision))
            return quantity.quantize(quantizer)
        return quantity

    def _get_quantity_precision(self, symbol: str) -> int:
        try:
            symbol_info = self.binance_client.get_symbol_info(symbol=self.symbol)
            if symbol_info and 'filters' in symbol_info:
                for f in symbol_info['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = Decimal(f['stepSize'])
                        precision = max(0, -step_size.as_tuple().exponent)
                        return precision
        except Exception as e:
            logger.error(f"Failed to get quantity precision for {symbol}: {e}", exc_info=True)
        return 0

    def get_position_quantity(self, position:PositionSide, price: Decimal, stop_loss_price: Decimal):

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        try:
            # 1. 최대 허용 손실 5%에 해당하는 가격 계산
            MAX_LOSS_PERCENTAGE = Decimal('0.05')

            # 포지션 비율 상한선 설정
            price_leverage = self.leverage * price
            max_position_value = self.balance * self.leverage * Decimal(str(app_config.MAX_POSITION_RATIO / 100))

            if position == PositionSide.LONG:
                max_loss_price = price * (Decimal('1') - MAX_LOSS_PERCENTAGE)
                adjusted_sl_price = max(stop_loss_price, max_loss_price)

                if adjusted_sl_price != stop_loss_price:
                    logger.info(f"SL price adjusted: Original Long SL {stop_loss_price:.4f} was below 5% max loss price {max_loss_price:.4f}. New SL: {adjusted_sl_price:.4f}")

                quantity = self.trading_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.balance,
                    stop_loss_price=adjusted_sl_price,
                    position_side=PositionSide.LONG
                )
                logger.info(f"calculate_quantity_with_risk_management: {quantity}")
                # 2. 포지션 규모(총 가치) 계산
                position_value = quantity * price_leverage

                # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                if self.positions.long is None:
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.available_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = self._adjust_quantity_by_precision(
                                symbol=self.symbol,
                                quantity=new_quantity
                            )
                            return adjusted_quantity, adjusted_sl_price

                    adjusted_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=quantity # 리스크 관리 기반으로 계산된 원래 수량
                    )
                    return adjusted_quantity, adjusted_sl_price

                elif self.positions.long is not None:
                    current_position_value = Decimal('0')
                    # 2. 현재 보유 중인 포지션 가치 계산
                    if self.positions.long_amount and self.positions.long_entry_price:
                        current_position_value = self.positions.long_amount * self.positions.long_entry_price

                        # 4. 추가 매수 가능한 포지션 가치 계산
                        remaining_position_value = max_position_value - current_position_value

                        if remaining_position_value <= Decimal('0'):
                            logger.info("Cannot add to the position. The maximum position limit has been reached.")
                            return Decimal('0')

                        # 5. 리스크 기반 수량과 추가 매수 가능 수량 중 더 작은 값 선택
                        #    (가치 기반으로 변환하여 비교)
                        risk_based_value = quantity * price
                        
                        # 실제 매수할 포지션 가치
                        target_value = min(risk_based_value, remaining_position_value)


                        # 6. 최종 수량 계산 및 정밀도 조정
                        final_quantity = target_value / price
                        
                        # 현재 이용가능한 자산이 있는지 확인
                        if target_value > (self.available_balance * self.leverage):
                            # 자산이 부족하면 이용가능한 자산 내에서만 구매
                            final_quantity = (self.available_balance * self.leverage) / price

                        adjusted_quantity = self._adjust_quantity_by_precision(
                            symbol=self.symbol,
                            quantity=final_quantity
                        )
                        
                        return adjusted_quantity, price

            elif position == PositionSide.SHORT:
                max_loss_price = price * (Decimal('1') + MAX_LOSS_PERCENTAGE)
                adjusted_sl_price = min(stop_loss_price, max_loss_price)

                if adjusted_sl_price != stop_loss_price:
                    logger.info(f"SL price adjusted: Original Short SL {stop_loss_price:.4f} was below 5% max loss price {max_loss_price:.4f}. New SL: {adjusted_sl_price:.4f}")

                quantity = self.trading_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.balance,
                    stop_loss_price=adjusted_sl_price,
                    position_side=PositionSide.SHORT
                )
                # 2. 포지션 규모(총 가치) 계산
                position_value = quantity * price_leverage

                # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                if self.positions.short is None:
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.available_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = self._adjust_quantity_by_precision(
                                symbol=self.symbol,
                                quantity=new_quantity
                            )
                            return adjusted_quantity, adjusted_sl_price

                    adjusted_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=quantity # 리스크 관리 기반으로 계산된 원래 수량
                    )
                    return adjusted_quantity, adjusted_sl_price

                elif self.positions.short is not None:
                    current_position_value = Decimal('0')
                    # 2. 현재 보유 중인 포지션 가치 계산
                    if self.positions.short_amount and self.positions.short_entry_price:
                        current_position_value = self.positions.short_amount * self.positions.short_entry_price

                        # 4. 추가 매수 가능한 포지션 가치 계산
                        remaining_position_value = max_position_value - current_position_value

                        if remaining_position_value <= Decimal('0'):
                            logger.info("Cannot add to the position. The maximum position limit has been reached.")
                            return Decimal('0')

                        # 5. 리스크 기반 수량과 추가 매수 가능 수량 중 더 작은 값 선택
                        #    (가치 기반으로 변환하여 비교)
                        risk_based_value = quantity * price
                        
                        # 실제 매수할 포지션 가치
                        target_value = min(risk_based_value, remaining_position_value)

                        # 6. 최종 수량 계산 및 정밀도 조정
                        final_quantity = target_value / price

                        # 현재 이용가능한 자산이 있는지 확인
                        if target_value > (self.available_balance * self.leverage):
                            # 자산이 부족하면 이용가능한 자산 내에서만 구매
                            final_quantity = (self.available_balance * self.leverage) / price

                        adjusted_quantity = self._adjust_quantity_by_precision(
                            symbol=self.symbol,
                            quantity=final_quantity
                        )

                        return adjusted_quantity, price

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def _get_price_precision(self, symbol: str) -> int:
        """심볼의 가격 정밀도 (소수점 이하 최대 자릿수)를 가져옵니다."""
        try:
            # Note: The existing code seems to use a method that fetches symbol info, 
            # but I'll add the necessary logic here for price.
            symbol_info = self.binance_client.get_symbol_info(symbol=self.symbol)
            if symbol_info and 'filters' in symbol_info:
                for f in symbol_info['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        # tickSize는 가격이 가질 수 있는 최소 단위를 나타냅니다.
                        tick_size = Decimal(f['tickSize'])
                        # tickSize의 소수점 자릿수가 곧 가격 정밀도입니다.
                        precision = max(0, -tick_size.as_tuple().exponent)
                        return precision
        except Exception as e:
            logger.error(f"Failed to get price precision for {symbol}: {e}", exc_info=True)
        return 0 # 기본값은 0

    def identify_liquidity(self, showSwingPoint:bool = False):

        lows = list(self.low_prices)

        swing_points = self.identify_swing_points()

        if showSwingPoint:
            for type, idx, price in swing_points:
                logger.info(f"[{type}] {len(lows)-idx} - {price}")

        long_grab, short_grab = self.analysis_liquidity_grab(swing_points, False)

        long_sweep, short_sweep = self.analysis_liquidity_sweep(swing_points, False)

        return long_sweep, short_sweep

    def analysis_internal_liquidity_fvg(self, showFVG:bool = False):

        opens = list(self.open_prices)
        highs = list(self.high_prices)
        lows = list(self.low_prices)
        closes = list(self.close_prices)

        bullish_fvg = {}
        fvg_dict = {}

        for i in range(2, len(lows)):

            ri = len(lows)-(i)
            ri1 = len(lows)-(i-1)
            ri2 = len(lows)-(i-2)

            high2 = highs[i-2]
            low2 = lows[i-2]

            open1 = opens[i-1]
            high1 = highs[i-1]
            low1 = lows[i-1]
            close1 = closes[i-1]

            high = highs[i]
            low = lows[i]

            min_body_rate = 50

            body = abs(open1 - close1)
            body_rate = body / (high1-low1) * 100
            momentum_candle = body_rate >= min_body_rate

            # 3 Candle FVG
            # if momentum_candle:
            if open1 < close1 and high2 < low:
                fvg_dict.update({i-1:"LONG"})

            elif open1 > close1 and low2 > high:
                fvg_dict.update({i-1:"SHORT"})

        for fvg_idx in fvg_dict:

            fvg_type = fvg_dict[fvg_idx]

            check = {}

            if fvg_type == "LONG":
                if showFVG:
                    logger.info(f"Bullish FVG: {len(lows)-(fvg_idx)}")

                for i in range(fvg_idx+1, len(lows)):
                    fvg_price = lows[fvg_idx+1]
                    open = opens[i]
                    high = highs[i]
                    low = lows[i]
                    close = closes[i]

                    if fvg_idx not in check.keys():
                        if fvg_price > low:
                            check.update({fvg_idx: None})

                    elif fvg_idx in check.keys():
                        if check[fvg_idx] == None and open < close:
                            check.update({fvg_idx:i})
                            if showFVG:
                                logger.info(f"LONG FVG {fvg_price} {len(lows)-fvg_idx} {len(lows)-i}")
                            break

            elif fvg_type == "SHORT":
                if showFVG:
                    logger.info(f"Bearish FVG: {len(lows)-(fvg_idx)}")

    def analysis_liquidity_sweep(self, swing_points, showSweepLogger: bool = False):
        
        '''
        Docstring for analysis_liquidity_sweep
        
        :param self: Description

        BSL 종가가 스윙 고점을 뚫고 마감
        '''

        short_signal: Tuple[OrderSignal, Decimal] = OrderSignal.NO_SIGNAL, Decimal('0')
        long_signal: Tuple[OrderSignal, Decimal] = OrderSignal.NO_SIGNAL, Decimal('0')

        highs = list(self.high_prices)
        lows = list(self.low_prices)
        
        for i in range(6, len(swing_points)):
            sList = swing_points[i]
            sType = sList[0]
            sIndex = sList[1]
            sPrice = sList[2]

            sList1 = swing_points[i-1]
            sType1 = sList1[0]
            sIndex1 = sList1[1]
            sPrice1 = sList1[2]

            sList2 = swing_points[i-2]
            sType2 = sList2[0]
            sIndex2 = sList2[1]
            sPrice2 = sList2[2]

            sList3 = swing_points[i-3]
            sType3 = sList3[0]
            sIndex3 = sList3[1]
            sPrice3 = sList3[2]

            sList4 = swing_points[i-4]
            sType4 = sList4[0]
            sIndex4 = sList4[1]
            sPrice4 = sList4[2]


            sList5 = swing_points[i-5]
            sType5 = sList5[0]
            sIndex5 = sList5[1]
            sPrice5 = sList5[2]

            sList6 = swing_points[i-6]
            sType6 = sList6[0]
            sIndex6 = sList6[1]
            sPrice6 = sList6[2]

            if sType == "LOW":
                if sPrice < sPrice2 < sPrice1:
                    if len(lows)-sIndex == 3:
                        long_signal = OrderSignal.OPEN_POSITION, sPrice
                    if showSweepLogger:
                        logger.info(f"Sweep-Long {len(lows)-sIndex1}-{len(lows)-sIndex} {sPrice}")

            # if sType == "HIGH":
            #     if sPrice > sPrice2 > sPrice1:
            #         if len(lows)-sIndex == 3:
            #             short_signal = OrderSignal.OPEN_POSITION, sPrice
            #         if showSweepLogger:
            #             logger.info(f"Sweep-Short {len(lows)-sIndex1}-{len(lows)-sIndex} {sPrice}")

        return long_signal, short_signal

    def adjust_stop_loss_and_take_profit(self, side:PositionSide, entry:Decimal, stop_loss:Decimal, max_stop_loss_ratio:Decimal = Decimal('0.5')) -> Tuple[Decimal, Decimal]:

        '''
        Docstring for adjust_stop_loss_and_take_profit
        
        :param self: Description
        :param side: Description
        :type side: PositionSide
        :param entry: Description
        :type entry: Decimal
        :param stop_loss: Description
        :type stop_loss: Decimal
        :param max_stop_loss_ratio: Description
        :type max_stop_loss_ratio: Decimal
        '''

        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side parameter not in PositionSide, input parameter is {side}")

        price_precision = self._get_price_precision(symbol=self.symbol)
        if price_precision > 0:
            quantizer_str = '0.' + '0' * price_precision
        else:
            quantizer_str = '1'

        if side is PositionSide.LONG:
            max_sl_price = entry * (1 - max_stop_loss_ratio / 100)
            max_sl_price = max_sl_price.quantize(Decimal(quantizer_str))

            if stop_loss < max_sl_price:
                tp_price = entry + (entry - max_sl_price) * Decimal(str(app_config.RISK_REWARD_RAITO))
                tp_price = tp_price.quantize(Decimal(quantizer_str))         
                return max_sl_price, tp_price
            else:
                tp_price = entry + (entry - stop_loss) * Decimal(str(app_config.RISK_REWARD_RAITO))
                tp_price = tp_price.quantize(Decimal(quantizer_str))         
                return stop_loss, tp_price

        elif side is PositionSide.SHORT:
            max_sl_price = entry * (1 + max_stop_loss_ratio / 100)
            max_sl_price = max_sl_price.quantize(Decimal(quantizer_str))
            if stop_loss > max_sl_price:
                tp_price = entry - (max_sl_price - entry) * Decimal(str(app_config.RISK_REWARD_RAITO))
                tp_price = tp_price.quantize(Decimal(quantizer_str))
                return max_sl_price, tp_price
            else:
                tp_price = entry - (stop_loss - entry) * Decimal(str(app_config.RISK_REWARD_RAITO))
                tp_price = tp_price.quantize(Decimal(quantizer_str))
                return stop_loss, tp_price

    def process_stream_data(self, res):

        stream_name = res.get('stream', 'UNKNOWN_STREAM')
        try:
            if 'stream' in res and 'data' in res:
                stream_name = res.get('stream', 'Unknown Stream')
                stream_data = res.get('data')

                # Stream Data 2
                if stream_name == f'{self.symbol.lower()}@kline_{app_config.KLINE_INTERVAL2}':

                    # logger.info(f"{stream_data}")
                    pass

                # Stream Data 1
                elif stream_name == f"{self.symbol.lower()}@kline_{app_config.KLINE_INTERVAL}":

                    kline_data = stream_data.get('k')
                    if kline_data and kline_data.get('x'):

                        # First, Update Recent Candle
                        opens, highs, lows, closes = self.update_candle_data(kline_data)

                        # Second, Analysis Data and Get Signal
                        _long, _short = self.identify_liquidity()
                        long_signal, long_sl_price = _long
                        short_signal, short_sl_price = _short

                        if long_sl_price != Decimal('0'):
                            long_sl_price, long_tp_price = self.adjust_stop_loss_and_take_profit(PositionSide.LONG, closes[-1], long_sl_price)
                        if short_sl_price != Decimal('0'):
                            short_sl_price, short_tp_price = self.adjust_stop_loss_and_take_profit(PositionSide.SHORT, closes[-1], short_sl_price)

                        # Third, Start Order
                        if app_config.ENABLE_ORDER:
                            self.execute_trade(long_signal, short_signal, long_sl_price, short_sl_price, closes[-1])
                        else:
                            if long_signal is not OrderSignal.NO_SIGNAL:
                                logger.info(f"[LONG] {long_signal} Stop Loss: {long_sl_price} Take Profit: {long_tp_price}")

                            if short_signal is not OrderSignal.NO_SIGNAL:
                                logger.info(f"[SHORT] {short_signal} Stop Loss: {short_sl_price} Take Profit: {short_tp_price}")

        except Exception as e:
            logger.error(f"Unexpected error during data processing: {e}", exc_info=True)

    def process_user_data(self, user_data):
        try:
            event_type = user_data.get('e')
            if event_type == 'ORDER_TRADE_UPDATE':
                order_status = user_data['o'].get('X')
                position_side = user_data['o'].get('ps')
                order_id = user_data['o'].get('i')

                if order_status == 'FILLED':
                    if order_id == self.positions.long_stop_loss_order_id:
                        logger.info("Long stop-loss order has been filled. Resetting local state.")
                        self.positions = PositionState()

                    elif order_id == self.positions.short_stop_loss_order_id:
                        logger.info("Short stop-loss order has been filled. Resetting local state.")
                        self.positions = PositionState()

                    elif (position_side == PositionSide.LONG and self.positions.long) or (position_side == PositionSide.SHORT and self.positions.short):
                        logger.info(f"Position ({position_side}) liquidation confirmed. Proceeding to cancel the stop-loss order.")

                        if position_side == PositionSide.LONG and self.positions.long_stop_loss_order_id:
    
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
                            )
                        elif position_side == PositionSide.SHORT and self.positions.short_stop_loss_order_id:
    
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.short_stop_loss_order_id
                            )
                        self.update_balance()
                        self.positions = PositionState()
            
            if event_type == 'ACCOUNT_UPDATE':
                for position in user_data['a']['P']:
                    if position['s'] == self.symbol and Decimal(position['pa']) == 0:
                        logger.info("Account update confirmed position liquidation. Resetting local state.")
                        self.positions = PositionState()

        except Exception as e:
            logger.error(f"Unexpected error during user data processing: {e}", exc_info=True)

    def create_take_profit_market(self, position: PositionSide, symbol: str, quantity: Decimal, tp_price):

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        if position == PositionSide.LONG:
            side = OrderSide.SELL
        elif position in [PositionSide.SHORT]:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_take_profit_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_price=tp_price,
                positionSide=position,
            )
            return order.get('orderId', None)

        except BinanceAPIException as e:
            logger.error(f"Failed to stop market {position} position: {e.message} (Error code: {e.code})", exc_info=True)

    def create_stop_market(self, position: PositionSide, symbol: str, quantity: Decimal, sl_price):

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        if position == PositionSide.LONG:
            side = OrderSide.SELL
        elif position in [PositionSide.SHORT]:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_stop_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_price=sl_price,
                positionSide=position,
            )
            return order.get('orderId', None)

        except BinanceAPIException as e:
            logger.error(f"Failed to stop market {position} position: {e.message} (Error code: {e.code})", exc_info=True)

    def create_sell_position(self, position: PositionSide, symbol: str, quantity: Decimal):
        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        if position == PositionSide.LONG:
            side = OrderSide.SELL
        elif position == PositionSide.SHORT:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_market_order(
                symbol=symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            return order

        except BinanceAPIException as e:
            logger.error(f"Failed to close {position} position: {e.message} (Error code: {e.code})", exc_info=True)

    def create_buy_position(self, position:PositionSide, quantity: Decimal, current_price: Decimal, sl_price: Decimal, tp_price: Decimal = None):
        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        if position == PositionSide.LONG:
            side = OrderSide.BUY
        elif position == PositionSide.SHORT:
            side = OrderSide.SELL
        try:
            order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            if order:
                # 손절매 주문 생성 전, 기존 포지션이 있을 경우 평균 단가 계산
                if position == PositionSide.LONG:
                    if self.positions.long_amount:
                        # 기존 총 가치 = 기존 수량 * 기존 단가
                        old_total_value = self.positions.long_amount * self.positions.long_entry_price
                        # 새로운 총 가치 = 기존 총 가치 + 추가 매수 가치
                        new_total_value = old_total_value + (quantity * current_price)
                        # 새로운 총 수량
                        new_total_amount = self.positions.long_amount + quantity

                        # 평균 단가와 총 수량 업데이트
                        self.positions.long_entry_price = new_total_value / new_total_amount
                        self.positions.long_amount = new_total_amount
                        logger.info(f"Position added. New total quantity: {new_total_amount:.4f}, New average entry price: {self.positions.long_entry_price:.4f}")
                    else:
                        # 첫 진입 시 초기화
                        self.positions.long = current_price
                        self.positions.long_amount = quantity
                        self.positions.long_entry_price = Decimal(str(current_price))

                    if position == PositionSide.LONG and sl_price < self.positions.long_entry_price:
                        # 기존 손절매 주문이 있다면 취소
                        if self.positions.long_stop_loss_order_id:
    
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
                            )
                        sl_order_id = self.create_stop_market(
                            position=position,
                            symbol=self.symbol,
                            quantity=self.positions.long_amount, # 업데이트된 총 수량 사용
                            sl_price=sl_price
                            )
                        if sl_order_id:
                            self.positions.long_stop_loss = sl_price
                            self.positions.long_stop_loss_order_id = sl_order_id
                            logger.info(f"New long stop-loss order placed with updated quantity and price.")

                    if position == PositionSide.LONG and tp_price is not None:
                        if tp_price > self.positions.long_entry_price:
                            # 기존 손절매 주문이 있다면 취소
                            if self.positions.long_take_profit_order_id:
        
                                self.trading_manager.cancel_order(
                                    symbol=self.symbol,
                                    order_id=self.positions.long_take_profit_order_id
                                )
                            tp_order_id = self.create_stop_market(
                                position=position,
                                symbol=self.symbol,
                                quantity=self.positions.long_amount, # 업데이트된 총 수량 사용
                                sl_price=tp_price
                                )
                            if tp_order_id:
                                self.positions.long_take_profit = sl_price
                                self.positions.long_take_profit_order_id = tp_order_id
                                logger.info(f"New long take-profit order placed with updated quantity and price.")

                elif position == PositionSide.SHORT:
                    if self.positions.short_amount:
                        # 기존 총 가치 = 기존 수량 * 기존 단가
                        old_total_value = self.positions.short_amount * self.positions.short_entry_price
                        # 새로운 총 가치 = 기존 총 가치 + 추가 매수 가치
                        new_total_value = old_total_value + (quantity * current_price)
                        # 새로운 총 수량
                        new_total_amount = self.positions.short_amount + quantity

                        # 평균 단가와 총 수량 업데이트
                        self.positions.short_entry_price = new_total_value / new_total_amount
                        self.positions.short_amount = new_total_amount
                        logger.info(f"Position added. New total quantity: {new_total_amount:.4f}, New average entry price: {self.positions.short_entry_price:.4f}")
                    else:
                        # 첫 진입 시 초기화
                        self.positions.short = current_price
                        self.positions.short_amount = quantity
                        self.positions.short_entry_price = Decimal(str(current_price))

                    if position == PositionSide.SHORT and sl_price > self.positions.short_entry_price:
                        # 기존 손절매 주문이 있다면 취소
                        if self.positions.short_stop_loss_order_id:
    
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.short_stop_loss_order_id
                            )
                        order_id = self.create_stop_market(
                            position=position,
                            symbol=self.symbol,
                            quantity=self.positions.short_amount, # 업데이트된 총 수량 사용
                            sl_price=sl_price
                            )
                        if order_id:
                            self.positions.short_stop_loss = sl_price
                            self.positions.short_stop_loss_order_id = order_id
                            logger.info(f"New short stop-loss order placed with updated quantity and price.")

                    if position == PositionSide.SHORT and tp_price is not None:
                        if tp_price < self.positions.short_entry_price:
                            # 기존 손절매 주문이 있다면 취소
                            if self.positions.short_take_profit_order_id:
        
                                self.trading_manager.cancel_order(
                                    symbol=self.symbol,
                                    order_id=self.positions.short_take_profit_order_id
                                )
                            order_id = self.create_stop_market(
                                position=position,
                                symbol=self.symbol,
                                quantity=self.positions.short_amount, # 업데이트된 총 수량 사용
                                sl_price=tp_price
                                )
                            if order_id:
                                self.positions.short_take_profit = tp_price
                                self.positions.short_take_profit_order_id = order_id
                                logger.info(f"New short take-profit order placed with updated quantity and price.")

        except BinanceClientException as e:
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")
            order_status_verified = self._verify_order_and_state()
            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")
        except BinanceAPIException as e:
            if e.code == MARGIN_INSUFFICIENT_CODE:
                logger.critical(f"FATAL ERROR: Insufficient funds to create a {position} position. (Error code: {e.code})", exc_info=True)
            else:
                logger.error(f"Failed to open {position} position: {e.message} (Error code: {e.code})", exc_info=True)
            raise e

    def execute_trade(self, long_signal: OrderSignal, short_signal: OrderSignal, long_sl_price: Decimal, short_sl_price: Decimal, entry_price: Decimal):

        if long_signal in [OrderSignal.OPEN_POSITION, OrderSignal.CLOSE_POSITION, OrderSignal.UPDATE_STOP_LOSS, OrderSignal.UPDATE_TAKE_PROFIT]:

            # OPEN LONG POSTION
            if self.positions.long is None and long_signal == OrderSignal.OPEN_POSITION:
                quantity, sl_price = self.get_position_quantity(position=PositionSide.LONG, price=entry_price, stop_loss_price=long_sl_price)
                tp_price = entry_price + (entry_price - sl_price) * Decimal(str(app_config.RISK_REWARD_RAITO))
                price_precision = self._get_price_precision(symbol=self.symbol)
                if price_precision > 0:
                    quantizer_str = '0.' + '0' * price_precision
                else:
                    quantizer_str = '1'
                tp_price = tp_price.quantize(Decimal(quantizer_str))
                logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}, Order Stop Loss: {sl_price}, Take Profit: {tp_price}")
                self.create_buy_position(position=PositionSide.LONG, quantity=quantity, current_price=entry_price, sl_price=sl_price, tp_price=tp_price)

            # CLOSE LONG POSITION
            elif self.positions.long is not None and long_signal != OrderSignal.OPEN_POSITION:
                if self.positions.long_stop_loss_order_id:
                    try:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.long_stop_loss_order_id
                        )
                        sl_price = self.positions.long_stop_loss
                        self.positions.long_stop_loss = None
                        self.positions.long_stop_loss_order_id = None
                    except BinanceAPIException as e:
                        logger.error(f"Failed to cancel order: {e.message} (Error code: {e.code})", exc_info=True)

                if (long_signal == OrderSignal.UPDATE_STOP_LOSS) and (sl_price != long_sl_price):
                    logger.info(f"SIGNAL: {long_signal}, Updating long stop loss price {sl_price} -> {long_sl_price}")
                    order_id = self.create_stop_market(
                        position=PositionSide.LONG,
                        symbol=self.symbol,
                        quantity=self.positions.long_amount, # 업데이트된 총 수량 사용
                        sl_price=long_sl_price
                        )
                    if order_id:
                        self.positions.long_stop_loss = long_sl_price
                        self.positions.long_stop_loss_order_id = order_id
                        logger.info(f"New stop-loss order placed with updated quantity and price.")

                elif long_signal == OrderSignal.CLOSE_POSITION:
                    logger.info(f"SIGNAL: {long_signal}, Closing long all position")
                    try:
                        self.create_sell_position(
                            position=PositionSide.LONG,
                            symbol=self.symbol,
                            quantity=self.positions.long_amount
                        )
                        self.positions.long = None
                        self.positions.long_amount = None
                        self.positions.long_entry_price = None
                        logger.info("All long positions have been sold and the state has been reset.")
                    except Exception as e:
                        logger.error(f"An error occurred while selling all long positions: {e}", exc_info=True)

        if short_signal in [OrderSignal.OPEN_POSITION, OrderSignal.CLOSE_POSITION, OrderSignal.UPDATE_STOP_LOSS, OrderSignal.UPDATE_TAKE_PROFIT]:

            # OPEN SHORT POSTION
            if self.positions.short is None and short_signal == OrderSignal.OPEN_POSITION:
                quantity, sl_price = self.get_position_quantity(position=PositionSide.SHORT, price=entry_price, stop_loss_price=short_sl_price)
                tp_price = entry_price - (sl_price - entry_price) * Decimal(str(app_config.RISK_REWARD_RAITO))
                price_precision = self._get_price_precision(symbol=self.symbol)
                if price_precision > 0:
                    quantizer_str = '0.' + '0' * price_precision
                else:
                    quantizer_str = '1'
                tp_price = tp_price.quantize(Decimal(quantizer_str))
                logger.info(f"SIGNAL: Pullback generated a short position entry signal! Order quantity: {quantity:.4f}, Order Stop Loss: {sl_price} Take-Profit: {tp_price}")
                self.create_buy_position(position=PositionSide.SHORT, quantity=quantity, current_price=entry_price, sl_price=sl_price, tp_price=tp_price)

            # CLOSE SHORT POSITION
            if self.positions.short is not None and short_signal != OrderSignal.OPEN_POSITION:
                if self.positions.short_stop_loss_order_id:
                    try:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.short_stop_loss_order_id
                        )
                        sl_price = self.positions.short_stop_loss
                        self.positions.short_stop_loss = None
                        self.positions.short_stop_loss_order_id = None
                    except BinanceAPIException as e:
                        logger.error(f"Failed to cancel order: {e.message} (Error code: {e.code})", exc_info=True)

                if (short_signal == OrderSignal.UPDATE_STOP_LOSS) and (sl_price != short_sl_price):
                    logger.info(f"SIGNAL: {short_signal}, Updating short stop loss price {sl_price} -> {short_sl_price}")
                    order_id = self.create_stop_market(
                        position=PositionSide.SHORT,
                        symbol=self.symbol,
                        quantity=self.positions.short_amount, # 업데이트된 총 수량 사용
                        sl_price=short_sl_price
                        )
                    if order_id:
                        self.positions.short_stop_loss = short_sl_price
                        self.positions.short_stop_loss_order_id = order_id
                        logger.info(f"New stop-loss order placed with updated quantity and price.")

                if short_signal == OrderSignal.CLOSE_POSITION:
                    logger.info(f"SIGNAL: {short_signal}, Closing short all position")
                    try:
                        self.create_sell_position(
                            position=PositionSide.SHORT,
                            symbol=self.symbol,
                            quantity=self.positions.short_amount
                        )
                        self.positions.short = None
                        self.positions.short_amount = None
                        self.positions.short_entry_price = None
                        logger.info("All short positions have been sold and the state has been reset.")
                    except Exception as e:
                        logger.error(f"An error occurred while selling all short positions: {e}", exc_info=True)
