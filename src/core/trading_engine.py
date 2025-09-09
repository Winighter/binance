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

        # 봇 재실행 시 상태 동기화 로직 추가
        self.initialize_bot_state()

    def initialize_bot_state(self):
        """
        봇 재시작 시 Binance 계좌 상태와 로컬 상태를 동기화합니다.
        """
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
        """API 호출 실패 후, 포지션 및 주문 상태를 확인하는 헬퍼 함수."""
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

    def process_stream_data(self, res):
        """
        웹소켓으로부터 수신된 캔들 데이터를 처리하고 전략 신호를 생성합니다.
        
        주의: 이 메서드는 오직 데이터 업데이트와 신호 생성 역할만 담당합니다.
              실제 거래 실행 로직은 execute_trade() 메서드에서 처리합니다.
        """
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
                            if len(self.close_prices) >= app_config.ATR_LENGTH + 1:

                                atr_list = self.indicators.atr(self.high_prices, self.low_prices, self.close_prices, app_config.ATR_LENGTH).tolist()
                                atr_value = atr_list[-1]

                                ema_short_values = self.indicators.ema(self.close_prices, app_config.SHORT_PERIOD)
                                ema_long_values = self.indicators.ema(self.close_prices, app_config.LONG_PERIOD)

                                ema_signal = 0
                                if ema_short_values[-1] > ema_long_values[-1] and ema_short_values[-2] <= ema_long_values[-2]:
                                    ema_signal = 1
                                if ema_short_values[-1] < ema_long_values[-1] and ema_short_values[-2] >= ema_long_values[-2]:
                                    ema_signal = -1

                                supertrend_signal, supertrend_value = self.indicators.supertrend(
                                    self.high_prices,
                                    self.low_prices,
                                    self.close_prices,
                                    atr_list,
                                    app_config.SUPERTREND_ATR_LENGTH,
                                    app_config.SUPERTREND_MULTIPLIER,
                                )

                        except Exception as e:
                            logger.error(f"Error calculating indicator: {e}", exc_info=True)
                            return
                        if not app_config.TEST_MODE:

                            self.ema_cross_execute_trade(ema_signal, atr_value, close)

                            # self.supertrend_execute_trade(supertrend_signal[-1], supertrend_value[-1], atr_value, close)

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

    def create_long_position(self, quantity: Decimal, current_price: Decimal, atr_value: Decimal, supertrend_value: Decimal = None):
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

                self.positions.long_atr_stop_loss = self.long_entry_price - (Decimal(str(atr_value)) * Decimal(str(app_config.ATR_MULTIPLIER)))
                
                if supertrend_value is not None:
                    stop_loss_price = max(supertrend_value, self.positions.long_atr_stop_loss)
                else:
                    stop_loss_price = self.positions.long_atr_stop_loss

                self.positions.long_stop_loss = stop_loss_price

                if stop_loss_price < current_price:
                    stop_loss_order = self.trading_manager.create_stop_market_order(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        quantity=quantity,
                        stop_price=stop_loss_price,
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

    def create_short_position(self, quantity: Decimal, current_price: Decimal, atr_value: Decimal, supertrend_value: Decimal = None):
        if not quantity:
            return
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
                self.positions.short_atr_stop_loss = self.short_entry_price + (Decimal(str(atr_value)) * Decimal(str(app_config.ATR_MULTIPLIER)))
                if supertrend_value is not None:
                    stop_loss_price = min(supertrend_value, self.positions.short_atr_stop_loss)
                else:
                    stop_loss_price = self.positions.short_atr_stop_loss
                self.positions.short_stop_loss = stop_loss_price
                
                if stop_loss_price > current_price:
                    stop_loss_order = self.trading_manager.create_stop_market_order(
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        quantity=quantity,
                        stop_price=stop_loss_price,
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

    def ema_cross_execute_trade(self, ema_signal, atr_value, close_price):

        if ema_signal is not 0:
            logger.info(f'ema_signal: {ema_signal}')

        if self.positions.long is not None:
            if ema_signal == -1:
                logger.info("SIGNAL: EMA signal turned bearish! Closing long position and entering a short...")
                self.trading_manager.create_market_order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    positionSide=PositionSide.LONG,
                    quantity=self.positions.long_amount
                )
                self.positions.long = None
                self.positions.long_amount = None
                try:
                    quantity = self.get_position_quantity(price=close_price)
                    if quantity > 0:
                        self.create_short_position(quantity=quantity, current_price=close_price, atr_value=atr_value)
                except Exception as e:
                    logger.error(f"Error initiating short position after liquidating long position: {e}", exc_info=True)
            else:
                new_stop_loss = self.positions.long_atr_stop_loss

                if self.positions.long_stop_loss != new_stop_loss:
                    if self.positions.long_stop_loss_order_id:
                        try:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to cancel long stop-loss order {self.positions.long_stop_loss_order_id}: {e}")
                    self.positions.long_stop_loss = new_stop_loss
                    if new_stop_loss < close_price:
                        stop_loss_order = self.trading_manager.create_stop_market_order(
                            symbol=self.symbol,
                            side=OrderSide.SELL,
                            positionSide=PositionSide.LONG,
                            quantity=self.positions.long_amount,
                            stop_price=new_stop_loss
                        )
                        if stop_loss_order:
                            self.positions.long_stop_loss_order_id = stop_loss_order['orderId']
                            logger.info(f"Long position stop-loss updated to {new_stop_loss}")

        elif self.positions.short is not None:
            if ema_signal == 1:
                logger.info("SIGNAL: EMA signal has switched to an uptrend! Liquidating short and initiating a long entry...")
                self.trading_manager.create_market_order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    positionSide=PositionSide.SHORT,
                    quantity=self.positions.short_amount
                )
                self.positions.short = None
                self.positions.short_amount = None
                try:
                    quantity = self.get_position_quantity(price=close_price)
                    if quantity > 0:
                        self.create_long_position(quantity=quantity, current_price=close_price, atr_value=atr_value)
                except Exception as e:
                    logger.error(f"Error initiating long position after liquidating the short position: {e}", exc_info=True)
            else:
                new_stop_loss = self.positions.short_atr_stop_loss
                if self.positions.short_stop_loss != new_stop_loss:
                    if self.positions.short_stop_loss_order_id:
                        try:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.short_stop_loss_order_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to cancel short stop-loss order {self.positions.short_stop_loss_order_id}: {e}")
                    self.positions.short_stop_loss = new_stop_loss
                    if new_stop_loss > close_price:
                        stop_loss_order = self.trading_manager.create_stop_market_order(
                            symbol=self.symbol,
                            side=OrderSide.BUY,
                            positionSide=PositionSide.SHORT,
                            quantity=self.positions.short_amount,
                            stop_price=new_stop_loss
                        )
                        if stop_loss_order:
                            self.positions.short_stop_loss_order_id = stop_loss_order['orderId']
                            logger.info(f"Short position stop-loss updated to {new_stop_loss}")
        
        if self.positions.long is None and ema_signal == 1:

            quantity = self.get_position_quantity(price=close_price)
            if quantity > 0:
                logger.info(f"SIGNAL: EMA generated a long position entry signal! Order quantity: {quantity:.4f}")
                self.create_long_position(quantity=quantity, current_price=close_price, atr_value=atr_value)

        if self.positions.short is None and ema_signal == -1:

            quantity = self.get_position_quantity(price=close_price)
            if quantity > 0:
                logger.info(f"SIGNAL: EMA generated a short position entry signal! Order quantity: {quantity:.4f}")
                self.create_short_position(quantity=quantity, current_price=close_price, atr_value=atr_value)

    def supertrend_execute_trade(self, supertrend_signal, supertrend_value, atr_value, close_price):

        if self.positions.long is not None:
            if supertrend_signal == -1:
                logger.info("SIGNAL: Supertrend signal turned bearish! Closing long position and entering a short...")
                self.trading_manager.create_market_order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    positionSide=PositionSide.LONG,
                    quantity=self.positions.long_amount
                )
                self.positions.long = None
                self.positions.long_amount = None
                try:
                    quantity = self.get_position_quantity(price=close_price)
                    if quantity > 0:
                        self.create_short_position(quantity=quantity, current_price=close_price, atr_value=atr_value, supertrend_value=supertrend_value)
                except Exception as e:
                    logger.error(f"Error initiating short position after liquidating long position: {e}", exc_info=True)
            else:
                new_stop_loss = max(supertrend_value, self.positions.long_atr_stop_loss)

                if self.positions.long_stop_loss != new_stop_loss:
                    if self.positions.long_stop_loss_order_id:
                        try:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to cancel long stop-loss order {self.positions.long_stop_loss_order_id}: {e}")
                    self.positions.long_stop_loss = new_stop_loss
                    if new_stop_loss < close_price:
                        stop_loss_order = self.trading_manager.create_stop_market_order(
                            symbol=self.symbol,
                            side=OrderSide.SELL,
                            positionSide=PositionSide.LONG,
                            quantity=self.positions.long_amount,
                            stop_price=new_stop_loss
                        )
                        if stop_loss_order:
                            self.positions.long_stop_loss_order_id = stop_loss_order['orderId']
                            logger.info(f"Long position stop-loss updated to {new_stop_loss}")

        elif self.positions.short is not None:
            if supertrend_signal == 1:
                logger.info("SIGNAL: Supertrend signal has switched to an uptrend! Liquidating short and initiating a long entry...")
                self.trading_manager.create_market_order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    positionSide=PositionSide.SHORT,
                    quantity=self.positions.short_amount
                )
                self.positions.short = None
                self.positions.short_amount = None
                try:
                    quantity = self.get_position_quantity(price=close_price)
                    if quantity > 0:
                        self.create_long_position(quantity=quantity, current_price=close_price, atr_value=atr_value, supertrend_value=supertrend_value)
                except Exception as e:
                    logger.error(f"Error initiating long position after liquidating the short position: {e}", exc_info=True)
            else:
                new_stop_loss = min(supertrend_value, self.positions.short_atr_stop_loss)
                if self.positions.short_stop_loss != new_stop_loss:
                    if self.positions.short_stop_loss_order_id:
                        try:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.short_stop_loss_order_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to cancel short stop-loss order {self.positions.short_stop_loss_order_id}: {e}")
                    self.positions.short_stop_loss = new_stop_loss
                    if new_stop_loss > close_price:
                        stop_loss_order = self.trading_manager.create_stop_market_order(
                            symbol=self.symbol,
                            side=OrderSide.BUY,
                            positionSide=PositionSide.SHORT,
                            quantity=self.positions.short_amount,
                            stop_price=new_stop_loss
                        )
                        if stop_loss_order:
                            self.positions.short_stop_loss_order_id = stop_loss_order['orderId']
                            logger.info(f"Short position stop-loss updated to {new_stop_loss}")
        
        if self.positions.long is None and supertrend_signal == 1:
            
            quantity = self.get_position_quantity(price=close_price)
            if quantity > 0:
                logger.info(f"SIGNAL: Supertrend generated a long position entry signal! Order quantity: {quantity:.4f}")
                self.create_long_position(quantity=quantity, current_price=close_price, atr_value=atr_value, supertrend_value=supertrend_value)

        if self.positions.short is None and supertrend_signal == -1:

            quantity = self.get_position_quantity(price=close_price)
            if quantity > 0:
                logger.info(f"SIGNAL: Supertrend generated a short position entry signal! Order quantity: {quantity:.4f}")
                self.create_short_position(quantity=quantity, current_price=close_price, atr_value=atr_value, supertrend_value=supertrend_value)