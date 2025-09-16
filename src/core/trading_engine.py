import logging
from decimal import Decimal
import settings as app_config
from binance.exceptions import BinanceAPIException
from ..shared.state_manager import PositionState
from ..shared.enums import OrderSide, PositionSide, EmaSignal
from ..shared.errors import MARGIN_INSUFFICIENT_CODE, BinanceClientException
from typing import List
from ..config import *
from decimal import Decimal, getcontext

logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, trading_manager, positions: PositionState, leverage,
                indicators, symbol: str, available_usdt: Decimal, open_prices:List[Decimal],
                high_prices:List[Decimal], low_prices:List[Decimal], close_prices:List[Decimal],
                ):
        self.symbol = symbol
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = positions
        self.indicators = indicators
        self.open_prices=open_prices
        self.high_prices=high_prices
        self.low_prices=low_prices
        self.close_prices=close_prices
        self.long_entry_price = Decimal(0)
        self.short_entry_price = Decimal(0)
        self.available_usdt = available_usdt
        self.leverage = leverage

        self.initialize_bot_state()

    def initialize_bot_state(self):
        try:
            # 1. 포지션 정보 조회
            positions_info = self.binance_client.futures_position_information(self.symbol)
            for pos in positions_info:

                if Decimal(pos['positionAmt']) != Decimal('0'):
                    position_side = pos['positionSide']
                    amount = Decimal(pos['positionAmt'])
                    entry_price = Decimal(pos['entryPrice'])

                    if position_side == PositionSide.LONG.value:
                        logger.info("Found an open LONG position during initialization.")
                        self.positions.long = entry_price
                        self.positions.long_amount = abs(amount)
                        self.long_entry_price = entry_price
                        # self.positions.long_stop_loss_half = False
                    elif position_side == PositionSide.SHORT.value:
                        logger.info("Found an open SHORT position during initialization.")
                        self.positions.short = entry_price
                        self.positions.short_amount = abs(amount)
                        self.short_entry_price = entry_price
                        # self.positions.short_stop_loss_half = False

            # 2. 열려 있는 주문 정보 조회 (손절매 주문)
            orders = self.binance_client.futures_get_all_orders()
            for order in orders:
                if order['type'] == 'STOP_MARKET' and order['status'] == 'NEW':
                    order_side = order['side']
                    position_side = order['positionSide']
                    
                    if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                        self.positions.long_stop_loss_order_id = order['orderId']
                        self.positions.long_stop_loss = Decimal(order['stopPrice'])
                        logger.info(f"Found existing long stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")
                    elif position_side == PositionSide.SHORT.value and order_side == OrderSide.BUY.value:
                        self.positions.short_stop_loss_order_id = order['orderId']
                        self.positions.short_stop_loss = Decimal(order['stopPrice'])
                        logger.info(f"Found existing short stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")

        except Exception as e:
            logger.error(f"Failed to initialize bot state from Binance: {e}", exc_info=True)

    def _verify_order_and_state(self) -> bool:
        try:
            position_info = self.binance_client.futures_position_information(symbol=self.symbol)
            
            if len(position_info) > 0 and (position_info[0]['positionSide'] == 'LONG' or position_info[0]['positionSide'] == 'SHORT'):
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

    def _get_stop_loss_price(self, position: str, price: Decimal, percent_rate = 0.025):
        if position not in ['LONG', 'SHORT']:
            raise ValueError(f"Invalud Value: {position}")
        sl_price = Decimal(str(0))
        if position == 'LONG':
            sl_price = price * Decimal(str((1 - (percent_rate / self.leverage))))
        elif position == 'SHORT':
            sl_price = price * Decimal(str((1 + (percent_rate / self.leverage))))
        return sl_price

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

    def _adjust_quantity_by_precision(self, symbol: str, quantity: Decimal) -> Decimal:
        precision = self._get_quantity_precision(symbol)
        if precision is not None:
            getcontext().prec = 28  # 높은 정밀도로 설정
            quantizer = Decimal('1e-{}'.format(precision))
            return quantity.quantize(quantizer)
        return quantity

    def process_stream_data(self, res):
        try:
            if not res:
                return
            # print(res)
            if 'stream' in res and 'data' in res:
                stream_name = res.get('stream')
                data = res.get('data')

                if stream_name == f"{self.symbol.lower()}@kline_{app_config.KLINE_INTERVAL}":
                    
                    kline_data = data.get('k')
                    if kline_data.get('x'):

                        open, high, low, close = self.update_candle_data(kline_data)

                        try:
                            ema_short_values = self.indicators.ema(self.close_prices, app_config.SHORT_PERIOD)
                            ema_middle_values = self.indicators.ema(self.close_prices, app_config.MIDDLE_PERIOD)
                            ema_long_values = self.indicators.ema(self.close_prices, app_config.LONG_PERIOD)

                            ema_short = ema_short_values[-1]
                            ema_middle = ema_middle_values[-1]
                            ema_long = ema_long_values[-1]

                            prev_ema_short = ema_short_values[-2]
                            prev_ema_middle = ema_middle_values[-2]
                            prev_ema_long = ema_long_values[-2]

                            prev_open_price = self.open_prices[-2]
                            prev_close_price = self.close_prices[-2]

                            pb_condition = abs(ema_middle - ema_long) < abs(open - close)

                            pbl_condtion = ema_short > ema_middle > ema_long # 정배열
                            pbl_condtion2 = ema_short <= open and prev_open_price >= prev_ema_long # 장기 이평선 훼손X
                            pbl_condtion3 = open < close and prev_open_price < prev_close_price and (max(high-close, open-low) <= (close-open))

                            pbs_condtion = ema_short < ema_middle < ema_long # 역배열
                            pbs_condtion2 = ema_short >= open and prev_open_price <= prev_ema_long # 장기 이평선 훼손X
                            pbs_condtion3 = open > close and prev_open_price > prev_close_price and (max(high-open, close-low) <= (open-close))

                            pbl_signal = EmaSignal.LONG_WAITING_SIGNAL
                            pbs_signal = EmaSignal.SHORT_WAITING_SIGNAL

                            # LONG CONDITION
                            if pb_condition and pbl_condtion and pbl_condtion2 and pbl_condtion3:
                                pbl_signal = EmaSignal.LONG_BUY

                            if open > close and open > ema_middle > close and ema_short > ema_middle:
                                pbl_signal = EmaSignal.LONG_SELL_HALF

                            if ema_short < ema_middle and prev_ema_short >= prev_ema_middle:
                                pbl_signal = EmaSignal.LONG_SELL_ALL

                            # SHORT CONDTION
                            if pb_condition and pbs_condtion and pbs_condtion2 and pbs_condtion3:
                                pbs_signal = EmaSignal.SHORT_BUY

                            if open < close and open < ema_middle < close and ema_short < ema_middle:
                                pbs_signal = EmaSignal.SHORT_SELL_HALF

                            if ema_short > ema_middle and prev_ema_short <= prev_ema_middle:
                                pbs_signal = EmaSignal.SHORT_SELL_ALL

                        except Exception as e:
                            logger.error(f"Error calculating indicator: {e}", exc_info=True)
                            return

                        if not app_config.TEST_MODE:
                            self.pullback_execute_trade(pbl_signal.value, pbs_signal.value, high, low, close)

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
                        self.positions.long_stop_loss_half = False
                        logger.info("Long stop-loss order has been filled. Resetting local state.")
                        self.positions = PositionState()

                    elif order_id == self.positions.short_stop_loss_order_id:
                        self.positions.short_stop_loss_half = False
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

    def update_candle_data(self, ohlcv_data):
        open = Decimal(str(ohlcv_data.get('o')))
        high = Decimal(str(ohlcv_data.get('h')))
        low = Decimal(str(ohlcv_data.get('l')))
        close = Decimal(str(ohlcv_data.get('c')))

        self.open_prices.append(open)
        self.high_prices.append(high)
        self.low_prices.append(low)
        self.close_prices.append(close)

        if len(self.close_prices) > KLINE_LIMIT:
            self.open_prices.pop(0)
            self.high_prices.pop(0)
            self.low_prices.pop(0)
            self.close_prices.pop(0)

        return open, high, low, close

    def update_balance(self):
        try:
            account_balance = self.binance_client.get_futures_balance()
            if account_balance:
                self.available_usdt = Decimal(next(item for item in account_balance if item["asset"] == app_config.FUTURES_TRADING_ASSET)["availableBalance"])
                logger.info(f"Balance successfully updated. Available balance: {self.available_usdt:.2f} USDT")
            else:
                logger.warning("Balance update failed: Could not fetch balance information.")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def get_position_quantity(self, price: Decimal):
        try:
            quantity = self.trading_manager.calculate_quantity(
                balance_usdt=self.available_usdt,
                price=Decimal(str(price)),
                symbol=self.symbol
            )
            if quantity == 0:
                return 0

            return quantity

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def create_buy_position(self, position:str, quantity: Decimal, current_price: Decimal, sl_price: Decimal):
        if position not in ['LONG', 'SHORT']:
            raise ValueError(f'Invalid value: {position}')
        if position == 'LONG':
            side = OrderSide.BUY
        elif position == 'SHORT':
            side = OrderSide.SELL
        try:
            order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            if order:
                sl_price = Decimal(str(sl_price))

                if (position == 'LONG' and sl_price < current_price) or (position == 'SHORT' and sl_price > current_price):
                    order_id = self.create_stop_market(
                        position=position,
                        symbol=self.symbol,
                        quantity=quantity,
                        sl_price=sl_price
                        )
                    if order_id:
                        if position == 'LONG':
                            self.positions.long = current_price
                            self.positions.long_amount = quantity
                            self.long_entry_price = Decimal(str(current_price))
                            self.positions.long_stop_loss = sl_price
                            self.positions.long_stop_loss_half = False
                            self.positions.long_stop_loss_order_id = order_id
                        elif position == 'SHORT':
                            self.positions.short = current_price
                            self.positions.short_amount = quantity
                            self.short_entry_price = Decimal(str(current_price))
                            self.positions.short_stop_loss = sl_price
                            self.positions.short_stop_loss_half = False
                            self.positions.short_stop_loss_order_id = order_id

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

    def create_sell_position(self, position: str, symbol: str, quantity: Decimal):
        if position not in ['LONG', 'SHORT']:
            raise ValueError(f'Invalid value: {position}')
        if position == 'LONG':
            side = OrderSide.SELL
        elif position == 'SHORT':
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
  
    def create_stop_market(self, position: str, symbol: str, quantity: Decimal, sl_price):

        if position not in ['LONG', 'SHORT']:
            raise ValueError(f'Invalid value: {position}')
        
        if position == 'LONG':
            side = OrderSide.SELL
        elif position == 'SHORT':
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
            logger.error(f"Failed to stop markey {position} position: {e.message} (Error code: {e.code})", exc_info=True)

    def pullback_execute_trade(self, long_signal, short_signal, high, low, close):

        if self.positions.long is not None and long_signal in ['LONG_SELL_HALF', 'LONG_SELL_ALL']:

            # 1. 기존 손절매 주문 취소 (공통)
            if self.positions.long_stop_loss_order_id:
                try:
                    self.trading_manager.cancel_order(
                        symbol=self.symbol,
                        order_id=self.positions.long_stop_loss_order_id
                    )
                    self.positions.long_stop_loss_order_id = None
                    sl_price = self.positions.long_stop_loss
                    self.positions.long_stop_loss = None
                except BinanceAPIException as e:
                    logger.error(f"Failed to cancel order: {e.message} (Error code: {e.code})", exc_info=True)

            if long_signal == 'LONG_SELL_HALF' and not self.positions.long_stop_loss_half:
                logger.info("SIGNAL: LONG_SELL_HALF, Closing long half position")
                try:
                    # 2. 포지션 절반 매도
                    half_quantity = self.positions.long_amount / 2
                    # 수량을 바이낸스 정밀도에 맞게 조정
                    adjusted_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=half_quantity
                    )
                    self.create_sell_position(
                        position='LONG',
                        symbol=self.symbol,
                        quantity=adjusted_half_quantity
                    )
                    # 3. 남은 수량으로 상태 업데이트
                    self.positions.long_amount -= half_quantity
                    remaining_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long_amount = remaining_half_quantity

                    # 4. 남은 수량에 대한 새로운 손절매 주문 생성
                    if self.positions.long_amount > 0:
                        if sl_price is None:
                            logger.error("Could not create a new stop-loss order because there is no existing stop-loss price.")
                            return
                        order_id = self.create_stop_market(
                            position='LONG',
                            symbol=self.symbol,
                            quantity=self.positions.long_amount,
                            sl_price=sl_price
                            )
                        if order_id:
                            self.positions.long_stop_loss_half = True
                            self.positions.long_stop_loss_order_id = order_id
                            logger.info(f"Successfully created a new stop-loss order. amount: {self.positions.long_amount}, price: {sl_price}")
                        else:
                            logger.error("Failed to create a new stop-loss order.")

                    logger.info(f"Half of the long position has been closed. Remaining quantity: {self.positions.long_amount}")

                except Exception as e:
                    logger.error(f"An error occurred while closing half of the long position: {e}", exc_info=True)

            elif long_signal == 'LONG_SELL_ALL':
                logger.info("SIGNAL: LONG_SELL_ALL, Closing long all position")
                try:
                    self.create_sell_position(
                        position='LONG',
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long = None
                    self.positions.long_amount = None
                    self.positions.long_stop_loss_half = False
                    logger.info("All long positions have been sold and the state has been reset.")
                except Exception as e:
                    logger.error(f"An error occurred while selling all long positions: {e}", exc_info=True)

        if self.positions.short is not None and short_signal in ['SHORT_SELL_HALF', 'SHORT_SELL_ALL']:

            if self.positions.short_stop_loss_order_id:
                try:
                    self.trading_manager.cancel_order(
                        symbol=self.symbol,
                        order_id=self.positions.short_stop_loss_order_id
                    )
                    self.positions.short_stop_loss_order_id = None
                    sl_price = self.positions.short_stop_loss
                    self.positions.short_stop_loss = None
                except BinanceAPIException as e:
                    logger.error(f"Failed to cancel order: {e.message} (Error code: {e.code})", exc_info=True)

            if short_signal == 'SHORT_SELL_HALF' and not self.positions.short_stop_loss_half:
                logger.info("SIGNAL: SHORT_SELL_HALF, Closing short half position")
                try:
                    # 2. 포지션 절반 매도
                    half_quantity = self.positions.short_amount / 2
                    # 수량을 바이낸스 정밀도에 맞게 조정
                    adjusted_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=half_quantity
                    )
                    self.create_sell_position(
                        position='SHORT',
                        symbol=self.symbol,
                        quantity=adjusted_half_quantity
                    )
                    # 3. 남은 수량으로 상태 업데이트
                    self.positions.short_amount -= half_quantity
                    remaining_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=self.positions.short_amount
                    )
                    self.positions.short_amount = remaining_half_quantity

                    # 4. 남은 수량에 대한 새로운 손절매 주문 생성
                    if self.positions.short_amount > 0:
                        if sl_price is None:
                            logger.error("Could not create a new stop-loss order because there is no existing stop-loss price.")
                            return
                        order_id = self.create_stop_market(
                            position='SHORT',
                            symbol=self.symbol,
                            quantity=self.positions.short_amount,
                            sl_price=sl_price
                            )
                        if order_id:
                            self.positions.short_stop_loss_half = True
                            self.positions.short_stop_loss_order_id = order_id
                            logger.info(f"Successfully created a new stop-loss order. amount: {self.positions.short_amount}, price: {sl_price}")
                        else:
                            logger.error("Failed to create a new stop-loss order.")

                    logger.info(f"Half of the short position has been closed. Remaining quantity: {self.positions.short_amount}")

                except Exception as e:
                    logger.error(f"An error occurred while closing half of the short position: {e}", exc_info=True)

            elif short_signal == 'SHORT_SELL_ALL':
                logger.info("SIGNAL: SHORT_SELL_ALL, Closing short all position")
                try:
                    self.create_sell_position(
                        position='SHORT',
                        symbol=self.symbol,
                        quantity=self.positions.short_amount
                    )
                    self.positions.short = None
                    self.positions.short_amount = None
                    self.positions.short_stop_loss_half = False
                    logger.info("All short positions have been sold and the state has been reset.")
                except Exception as e:
                    logger.error(f"An error occurred while selling all short positions: {e}", exc_info=True)

        # OPEN POSTION
        if self.positions.long is None and long_signal == 'LONG_BUY':
            quantity = self.get_position_quantity(price=close)
            sl = self._get_stop_loss_price('LONG', close)
            sl_price = max(sl, low)
            logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}")
            self.create_buy_position(position='LONG', quantity=quantity, current_price=close, sl_price=sl_price)

        if self.positions.short is None and short_signal == 'SHORT_BUY':
            quantity = self.get_position_quantity(price=close)
            sl = self._get_stop_loss_price('SHORT', close)
            sl_price = min(sl, high)
            logger.info(f"SIGNAL: Pullback generated a short position entry signal! Order quantity: {quantity:.4f}")
            self.create_buy_position(position='SHORT', quantity=quantity, current_price=close, sl_price=sl_price)