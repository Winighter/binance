import logging
from decimal import Decimal
import settings as app_config
from binance.exceptions import BinanceAPIException
from ..shared.state_manager import PositionState
from ..shared.enums import OrderSide, PositionSide, TradingMode
from ..shared.errors import MARGIN_INSUFFICIENT_CODE, BinanceClientException
from typing import List
from ..config import *
from decimal import Decimal, getcontext

logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, trading_manager, positions: PositionState, 
                indicators, strategy, symbol: str, available_usdt: Decimal, open_prices:List[Decimal],
                high_prices:List[Decimal], low_prices:List[Decimal], close_prices:List[Decimal]):
        
        self.cnt_test = 0
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = positions
        self.indicators = indicators
        self.strategy = strategy
        self.symbol = symbol
        self.open_prices=open_prices
        self.high_prices=high_prices
        self.low_prices=low_prices
        self.close_prices=close_prices
        self.long_entry_price = Decimal(0)
        self.short_entry_price = Decimal(0)
        self.available_usdt = available_usdt

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
                    elif position_side == PositionSide.SHORT.value:
                        logger.info("Found an open SHORT position during initialization.")
                        self.positions.short = entry_price
                        self.positions.short_amount = abs(amount)
                        self.short_entry_price = entry_price

            # 2. 열려 있는 주문 정보 조회 (손절매 주문)
            orders = self.binance_client.futures_get_all_orders()
            for order in orders:
                if order['type'] == 'STOP_MARKET' and order['status'] == 'NEW':
                    order_side = order['side']
                    position_side = order['positionSide']
                    
                    if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                        self.positions.long_stop_loss_order_id = order['orderId']
                        self.positions.long_stop_loss = Decimal(order['stopPrice'])
                        logger.info(f"Found existing long stop-loss order {order['orderId']} during initialization.")
                    elif position_side == PositionSide.SHORT.value and order_side == OrderSide.BUY.value:
                        self.positions.short_stop_loss_order_id = order['orderId']
                        self.positions.short_stop_loss = Decimal(order['stopPrice'])
                        logger.info(f"Found existing short stop-loss order {order['orderId']} during initialization.")

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

                            pb_condtion = ema_short > ema_middle > ema_long # 정배열
                            pb_condtion2 = ema_short <= open and prev_open_price >= prev_ema_long # 장기 이평선 훼손X
                            pb_condtion3 = open < close and prev_open_price < prev_close_price and (max(high-close, open-low) <= (close-open))

                            pb_signal = 0
                            if pb_condtion and pb_condtion2 and pb_condtion3:
                                pb_signal = 1

                            if open > close and open > ema_short > close and ema_short > ema_middle:
                                pb_signal = -1

                            if ema_short < ema_middle and prev_ema_short >= prev_ema_middle:
                                pb_signal = -2

                            # if self.cnt_test == -1:
                            #     self.cnt_test = -2

                            # if self.cnt_test == 1:
                            #     self.cnt_test = -1

                            # if self.cnt_test == 0:
                            #     self.cnt_test = 1

                            # pb_signal = self.cnt_test

                        except Exception as e:
                            logger.error(f"Error calculating indicator: {e}", exc_info=True)
                            return
                        if not app_config.TEST_MODE:
                            self.pullback_execute_trade(pb_signal, high, low, close)

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

            if event_type == 'TRADE_LITE':
                symbol = user_data.get('s')
                order_quantity = user_data.get('q')
                order_price = user_data.get('p')
                client_order_id = user_data.get('c')
                side = user_data.get('S')
                last_executed_price = user_data.get('L')
                last_executed_quantity = user_data.get('l')
                order_id = user_data.get('i')

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

    def create_long_position(self, quantity: Decimal, current_price: Decimal, sl_price: Decimal):
        try:
            long_order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                positionSide=PositionSide.LONG,
                quantity=quantity
            )
            if long_order:
                self.positions.long = current_price
                self.positions.long_amount = quantity
                self.long_entry_price = Decimal(str(current_price))

                sl_price = Decimal(str(sl_price))

                self.positions.long_stop_loss = sl_price

                if sl_price < current_price:
                    stop_loss_order = self.trading_manager.create_stop_market_order(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        quantity=quantity,
                        stop_price=sl_price,
                        positionSide=PositionSide.LONG,
                    )
                    if stop_loss_order:
                        self.positions.long_stop_loss_order_id = stop_loss_order['orderId']

        except BinanceClientException as e:
            # 🚨 _safe_api_call이 최종 실패 예외를 던졌을 때 이 부분이 실행됩니다.
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")
            # 🚨 체결 확인 함수를 **여기서** 호출해야 합니다.
            order_status_verified = self._verify_order_and_state()

            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")

        except BinanceAPIException as e:
            if e.code == MARGIN_INSUFFICIENT_CODE:
                logger.critical(f"FATAL ERROR: Insufficient funds to create a long position. (Error code: {e.code})", exc_info=True)
            else:
                logger.error(f"Failed to open long position: {e.message} (Error code: {e.code})", exc_info=True)
            raise e

    def create_short_position(self, quantity: Decimal, current_price: Decimal, sl_price: Decimal):
        try:
            short_order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                positionSide=PositionSide.SHORT,
                quantity=quantity
            )
            if short_order:

                self.positions.short = current_price
                self.positions.short_amount = quantity
                self.short_entry_price = Decimal(str(current_price))
                sl_price = Decimal(sl_price)
                self.positions.short_stop_loss = sl_price

                if sl_price > current_price:
                    stop_loss_order = self.trading_manager.create_stop_market_order(
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        quantity=quantity,
                        stop_price=sl_price,
                        positionSide=PositionSide.SHORT,
                    )
                    if stop_loss_order:
                        self.positions.short_stop_loss_order_id = stop_loss_order['orderId']

        except BinanceClientException as e:
            # 🚨 _safe_api_call이 최종 실패 예외를 던졌을 때 이 부분이 실행됩니다.
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")

            # 🚨 체결 확인 함수를 **여기서** 호출해야 합니다.
            order_status_verified = self._verify_order_and_state()

            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")

        except BinanceAPIException as e:
            if e.code == MARGIN_INSUFFICIENT_CODE:
                logger.critical(f"FATAL ERROR: Insufficient funds to create a short position. (Error code: {e.code})", exc_info=True)
            else:
                logger.error(f"Failed to open long position: {e.message} (Error code: {e.code})", exc_info=True)
            raise e

    def pullback_execute_trade(self, signal, high, low, close):

        if signal != 0:
            logger.info(f'{signal}')

        if self.positions.long is not None:
            if signal == -1:
                logger.info("SIGNAL: signal 1, Closing long half position")
                try:
                    logger.info(f"{self.positions.long_stop_loss_order_id}, {self.positions.long_stop_loss} {self.positions.long_amount}")
                    # 1. 기존 손절매 주문 취소
                    if self.positions.long_stop_loss_order_id:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.long_stop_loss_order_id
                        )
                        self.positions.long_stop_loss_order_id = None
                        # self.positions.long_stop_loss = None
                    # 2. 포지션 절반 매도
                    half_quantity = self.positions.long_amount / 2
                    # 수량을 바이낸스 정밀도에 맞게 조정
                    adjusted_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=half_quantity
                    )
                    sell_order = self.trading_manager.create_market_order(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        positionSide=PositionSide.LONG,
                        quantity=adjusted_half_quantity
                    )
                    if not sell_order:
                        logger.error("Failed to create a sell order for half of the long position. The next logic will not be executed.")
                        return

                    # 2. 남은 수량으로 상태 업데이트
                    self.positions.long_amount -= half_quantity
                    adjusted2_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long_amount = adjusted2_half_quantity

                    # 4. 남은 수량에 대한 새로운 손절매 주문 생성
                    sl_price = self.positions.long_stop_loss
                    if self.positions.long_amount > 0:
                        if sl_price is None:
                            logger.error("Could not create a new stop-loss order because there is no existing stop-loss price.")
                            return

                        stop_loss_order = self.trading_manager.create_stop_market_order(
                            symbol=self.symbol,
                            side=OrderSide.SELL,
                            quantity=self.positions.long_amount,
                            stop_price=sl_price,
                            positionSide=PositionSide.LONG,
                        )
                        if stop_loss_order:
                            self.positions.long_stop_loss_order_id = stop_loss_order['orderId']
                            logger.info(f"Successfully created a new stop-loss order. amount: {self.positions.long_amount}, price: {sl_price}")
                        else:
                            logger.error("Failed to create a new stop-loss order.")
                    
                    # if self.positions.long_amount <= 0:
                    #     self.positions.long = None
                    #     self.positions.long_amount = None
                    #     logger.info("롱 포지션 전량 매도 및 상태 초기화 완료.")

                    logger.info(f"Half of the long position has been closed. Remaining quantity: {self.positions.long_amount}")

                except Exception as e:
                    logger.error(f"An error occurred while closing half of the long position: {e}", exc_info=True)

            elif signal == -2:
                logger.info("SIGNAL: signal 2, Closing long all position")
                try:
                    if self.positions.long_stop_loss_order_id:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.long_stop_loss_order_id
                        )
                        self.positions.long_stop_loss_order_id = None
                        self.positions.long_stop_loss = None

                    self.trading_manager.create_market_order(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        positionSide=PositionSide.LONG,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long = None
                    self.positions.long_amount = None
                    logger.info("All long positions have been sold and the state has been reset.")
                except Exception as e:
                    logger.error(f"An error occurred while selling all long positions: {e}", exc_info=True)

        if self.positions.long is None and signal == 1:
            quantity = self.get_position_quantity(price=close)
            if quantity > 0:
                logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}")
                self.create_long_position(quantity=quantity, current_price=close, sl_price=low)