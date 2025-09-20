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
                volume_prices:List[Decimal]
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
        self.volume_prices = volume_prices
        self.available_usdt = available_usdt
        self.leverage = leverage
        self.long_signal_pass = False

        self.initialize_bot_state()

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

            orders = self.binance_client.futures_get_all_orders()
            if orders:
                for order in orders:
                    if order['type'] == 'STOP_MARKET' and order['status'] == 'NEW':
                        order_side = order['side']
                        position_side = order['positionSide']
                        if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                            self.positions.long_stop_loss_order_id = order['orderId']
                            self.positions.long_stop_loss = Decimal(order['stopPrice'])
                            logger.info(f"Found existing long stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")
        except Exception as e:
            logger.error(f"Failed to initialize bot state from Binance: {e}", exc_info=True)

    def _verify_order_and_state(self) -> bool:
        try:
            position_info = self.binance_client.futures_position_information(symbol=self.symbol)
            
            if len(position_info) > 0 and position_info[0]['positionSide'] == 'LONG':
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

                        open, high, low, close, volume = self.update_candle_data(kline_data)

                        try:
                            # Candles 
                            close1 = self.close_prices[-2]
                            close2 = self.close_prices[-3]
                            open1 = self.open_prices[-2]
                            open2 = self.open_prices[-3]
                            high1 = self.high_prices[-2]
                            low1 = self.low_prices[-2]
                            close1 = self.close_prices[-2]
                            volume1 = self.volume_prices[-2]
                            volume2 = self.volume_prices[-3]

                            ### Indicators ###
                            # EMA
                            ema_short_values = self.indicators.ema(self.close_prices, app_config.SHORT_PERIOD)
                            ema_middle_values = self.indicators.ema(self.close_prices, app_config.MIDDLE_PERIOD)
                            ema_long_values = self.indicators.ema(self.close_prices, app_config.LONG_PERIOD)
                            ema_short0 = ema_short_values[-1]
                            ema_middle0 = ema_middle_values[-1]
                            ema_long0 = ema_long_values[-1]

                            # Keltner
                            kc_ma_values = self.indicators.ema(self.close_prices, app_config.MIDDLE_PERIOD)
                            kc_ma = Decimal(str(kc_ma_values[-1]))
                            atr_values = self.indicators.atr(self.high_prices, self.low_prices, self.close_prices)
                            rangema = Decimal(str(atr_values[-1]))
                            mult = Decimal('2.0')
                            upper = Decimal(str(kc_ma + rangema * mult))

                            # ATR
                            atr_values2 = self.indicators.atr(self.high_prices, self.low_prices, self.close_prices)
                            n2_atr = Decimal(str(atr_values2[-1]))
                            multi = Decimal('1.5')
                            atr_condition = (close - low) < (n2_atr * multi)

                            # Long Conditions
                            long_candle_condition = \
                                open < close and \
                                open1 < close1 and \
                                open2 < close2 and \
                                low > low1 and \
                                high > high1

                            long_volume_condition = volume == (max(volume, volume1, volume2))

                            long_ema1 = ema_short0 > ema_middle0 > ema_long0 # 정배열
                            long_ema2 = close > ema_short0
                            long_ema_condition = long_ema1 and long_ema2

                            long_keltner_breakout = close > upper

                            pbl_signal = EmaSignal.LONG_WAITING_SIGNAL

                            ### LONG CONDITION ###

                            # TAKE PROFIT ALL POSITION
                            # 전체 익절(Take Profit) 신호가 가장 높은 우선순위를 가집니다.
                            if self.positions.long and \
                                open > close and \
                                ema_short0 > ema_long0 and \
                                ema_middle0 > ema_long0 and \
                                open > ema_long0 > close:
                                pbl_signal = EmaSignal.LONG_TAKE_PROFIT

                            # SCAILING OUT POSITION
                            # 분할 익절
                            if self.positions.long and \
                                long_candle_condition and \
                                long_volume_condition and \
                                long_ema_condition and \
                                long_keltner_breakout:
                                if not self.long_signal_pass:
                                    logger.info(f"Long Signal is [TRUE], Checking... False -> True")
                                    self.long_signal_pass = True
                                    pbl_signal = EmaSignal.LONG_SCALING_OUT

                                elif self.long_signal_pass:
                                    logger.info(f"Long Signal is [TRUE], Checking... True -> False")
                                    self.long_signal_pass = False

                            # OPEN POSITION
                            # 새로운 포지션 진입
                            if self.positions.long is None and \
                                long_candle_condition and \
                                long_volume_condition and \
                                long_ema_condition and \
                                long_keltner_breakout and \
                                atr_condition:
                                pbl_signal = EmaSignal.LONG_OPENING_POSITION

                            if self.long_signal_pass and \
                                pbl_signal not in [EmaSignal.LONG_SCALING_OUT, EmaSignal.LONG_OPENING_POSITION]:
                                logger.info(f"Long Signal is [FALSE], Checking... True -> False")
                                self.long_signal_pass = False

                            # 테스트용 신호 확인
                            if pbl_signal != EmaSignal.LONG_WAITING_SIGNAL:
                                logger.info(f"Long Signal: {pbl_signal}")

                        except Exception as e:
                            logger.error(f"Error calculating indicator: {e}", exc_info=True)
                            return

                        if not app_config.TEST_MODE:
                            self.pullback_execute_trade(pbl_signal, low, close)

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
                        self.long_signal_pass = False
                        self.positions = PositionState()

                    elif position_side == PositionSide.LONG and self.positions.long:
                        logger.info(f"Position ({position_side}) liquidation confirmed. Proceeding to cancel the stop-loss order.")

                        if position_side == PositionSide.LONG and self.positions.long_stop_loss_order_id:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
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
        volume = Decimal(str(ohlcv_data.get('v')))

        self.open_prices.append(open)
        self.high_prices.append(high)
        self.low_prices.append(low)
        self.close_prices.append(close)
        self.volume_prices.append(volume)

        if len(self.close_prices) > KLINE_LIMIT:
            self.open_prices.pop(0)
            self.high_prices.pop(0)
            self.low_prices.pop(0)
            self.close_prices.pop(0)
            self.volume_prices.pop(0)

        return open, high, low, close, volume

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

    def get_position_quantity(self, price: Decimal, stop_loss_price: Decimal, risk_percentage: Decimal = 0.025):
        '''
        risk_percentage = 0.0025 ~ 0.01 = 0.25% ~ 1%
        '''
        try:
            quantity = self.trading_manager.calculate_quantity_with_risk_management(
                balance_usdt=self.available_usdt,
                price=Decimal(str(price)),
                stop_loss_price=Decimal(str(stop_loss_price)),
                risk_percentage=Decimal(str(risk_percentage)),
                leverage=Decimal(str(app_config.LEVERAGE)),
                symbol=self.symbol
            )
            if quantity == 0:
                return 0

            return quantity

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def create_buy_position(self, position:str, quantity: Decimal, current_price: Decimal, sl_price: Decimal):
        if position not in ['LONG', 'long']:
            raise ValueError(f'Invalid value: {position}')
        if position in ['LONG', 'long']:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            if order:
                sl_price = Decimal(str(sl_price))

                if position in ['LONG', 'long'] and sl_price < current_price:
                    order_id = self.create_stop_market(
                        position=position,
                        symbol=self.symbol,
                        quantity=quantity,
                        sl_price=sl_price
                        )
                    if order_id:
                        if position in ['LONG', 'long']:
                            self.positions.long = current_price
                            self.positions.long_amount = quantity
                            self.positions.long_entry_price = Decimal(str(current_price))
                            self.positions.long_stop_loss = sl_price
                            self.positions.long_stop_loss_order_id = order_id

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
        if position not in ['LONG', 'long']:
            raise ValueError(f'Invalid value: {position}')
        if position in ['LONG', 'long']:
            side = OrderSide.SELL
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

        if position not in ['LONG', 'long']:
            raise ValueError(f'Invalid value: {position}')
        
        if position == 'LONG':
            side = OrderSide.SELL
        elif position in ['LONG', 'long']:
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

    def pullback_execute_trade(self, long_signal, low, close):

        if self.positions.long is not None and long_signal in [EmaSignal.LONG_SCALING_OUT, EmaSignal.LONG_OPENING_POSITION, EmaSignal.LONG_TAKE_PROFIT]:

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

            if long_signal in [EmaSignal.LONG_SCALING_OUT, EmaSignal.LONG_OPENING_POSITION]:
                half_quantity = self.positions.long_amount / 3
                logger.info(f"SIGNAL: LONG_SCALING_OUT, Closing long half position")
                try:
                    # 2. 포지션 일부 매도
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

                    # 손익분기점
                    if self.positions.long_entry_price is None:
                        logger.error("Entry price is None")
                        return
                    if sl_price != self.positions.long_entry_price:
                        sl_price = self.positions.long_entry_price

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
                            self.positions.long_stop_loss = sl_price
                            self.positions.long_stop_loss_order_id = order_id
                            logger.info(f"Successfully created a new stop-loss order. amount: {self.positions.long_amount}, price: {sl_price}")
                        else:
                            logger.error("Failed to create a new stop-loss order.")

                    logger.info(f"Half of the long position has been closed. Remaining quantity: {self.positions.long_amount}")

                except Exception as e:
                    logger.error(f"An error occurred while closing half of the long position: {e}", exc_info=True)

            elif long_signal == EmaSignal.LONG_TAKE_PROFIT:
                logger.info(f"SIGNAL: {long_signal}, Closing long all position")
                try:
                    self.create_sell_position(
                        position='LONG',
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long = None
                    self.positions.long_amount = None
                    self.positions.long_entry_price = None
                    self.long_signal_pass = False
                    logger.info("All long positions have been sold and the state has been reset.")
                except Exception as e:
                    logger.error(f"An error occurred while selling all long positions: {e}", exc_info=True)

        # OPEN POSTION
        if self.positions.long is None and long_signal == EmaSignal.LONG_BUY:
            quantity = self.get_position_quantity(price=close, stop_loss_price=low)
            logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}")
            self.create_buy_position(position='LONG', quantity=quantity, current_price=close, sl_price=low)