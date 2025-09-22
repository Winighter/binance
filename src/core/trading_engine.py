import logging
from decimal import Decimal
import settings as app_config
from binance.exceptions import BinanceAPIException
from ..shared.state_manager import PositionState
from ..shared.enums import OrderSide, PositionSide, LongSignal
from ..strategy.conditions import TradingStrategy
from ..shared.errors import MARGIN_INSUFFICIENT_CODE, BinanceClientException
from typing import List
from ..config import *
from decimal import Decimal, getcontext


logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, trading_manager, positions: PositionState, leverage,
                indicators, symbol: str, all_usdt: Decimal, available_usdt: Decimal, open_prices:List[Decimal],
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
        self.all_usdt = all_usdt
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

    def get_position_quantity(self, price: Decimal, stop_loss_price: Decimal):
        try:
            quantity = self.trading_manager.calculate_quantity_with_risk_management(
                price=price,
                symbol=self.symbol,
                balance_usdt=self.all_usdt,
                stop_loss_price=stop_loss_price,
                risk_percentage=app_config.MAX_RISK_RATIO,
            )
            # 2. 포지션 규모(총 가치) 계산
            position_value = quantity * price * self.leverage

            # 3. 포지션 비율 상한선(20%) 설정
            max_position_value = self.all_usdt * self.leverage * Decimal(str(app_config.MAX_POSITION_RATIO / 100))

            # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
            if not self.positions.long:
                if position_value > max_position_value:
                    # 현재 이용가능한 자산이 있는지 확인
                    if max_position_value < (self.available_usdt * self.leverage):
                        # 상한선에 맞게 새로운 수량 계산
                        new_quantity = max_position_value / price
                        # 5. 수량 정밀도에 맞게 조정
                        adjusted_quantity = self._adjust_quantity_by_precision(
                            symbol=self.symbol,
                            quantity=new_quantity
                        )
                        return adjusted_quantity
                
            elif self.positions.long:
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
                    if target_value > (self.available_usdt * self.leverage):
                        # 자산이 부족하면 이용가능한 자산 내에서만 구매
                        final_quantity = (self.available_usdt * self.leverage) / price

                    adjusted_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=final_quantity
                    )
                    
                    return adjusted_quantity


        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def process_stream_data(self, res):
        try:
            if not res:
                return
            if 'stream' in res and 'data' in res:
                stream_name = res.get('stream')
                data = res.get('data')

                if stream_name == f"{self.symbol.lower()}@kline_{app_config.KLINE_INTERVAL}":
                    
                    kline_data = data.get('k')
                    if kline_data.get('x'):

                        opens, highs, lows, closes, volumes = self.update_candle_data(kline_data)

                        try:
                            long_signal = TradingStrategy(opens, highs, lows, closes, volumes).long_signal
                            low = lows[-1]
                            close = closes[-1]

                            # 테스트용 신호 확인
                            if long_signal != LongSignal.NO_SIGNAL:
                                logger.info(f"Long Signal: {long_signal}")

                        except Exception as e:
                            logger.error(f"Failed to find signal. {e}", exc_info=True)
                            return

                        if not app_config.TEST_MODE:
                            self.pullback_execute_long_trade(long_signal, low, close)

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

        return self.open_prices, self.high_prices, \
            self.low_prices, self.close_prices, self.volume_prices

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
                # 손절매 주문 생성 전, 기존 포지션이 있을 경우 평균 단가 계산
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

                sl_price = Decimal(str(sl_price))
                if position in ['LONG', 'long'] and sl_price < self.positions.long_entry_price:
                    # 기존 손절매 주문이 있다면 취소
                    if self.positions.long_stop_loss_order_id:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.long_stop_loss_order_id
                        )
                    order_id = self.create_stop_market(
                        position=position,
                        symbol=self.symbol,
                        quantity=self.positions.long_amount, # 업데이트된 총 수량 사용
                        sl_price=sl_price
                        )
                    if order_id:
                        self.positions.long_stop_loss = sl_price
                        self.positions.long_stop_loss_order_id = order_id
                        logger.info(f"New stop-loss order placed with updated quantity and price.")

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

    def pullback_execute_long_trade(self, long_signal, low: Decimal, close: Decimal):

        if self.positions.long is not None and long_signal in [LongSignal.SCALING_OUT, LongSignal.OPEN_POSITION, LongSignal.TAKE_PROFIT, LongSignal.ADD_POSITION]:

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

            if long_signal in [LongSignal.SCALING_OUT, LongSignal.OPEN_POSITION]:
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
                    self.positions.long_amount -= adjusted_half_quantity
                    remaining_half_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long_amount = remaining_half_quantity

                    # 손익분기점
                    if self.positions.long_entry_price is None:
                        logger.error("Entry price is None")
                        return

                    # 4. 남은 수량에 대한 새로운 손절매 주문 생성
                    if self.positions.long_amount > 0:
                        sl_price = self.positions.long_entry_price # <- 수정된 부분
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

            elif long_signal == LongSignal.TAKE_PROFIT:
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
        if self.positions.long is None and long_signal == LongSignal.OPEN_POSITION:
            # 1. 리스크 관리 기반 수량 계산
            quantity = self.get_position_quantity(price=close, stop_loss_price=low)
            logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}")
            self.create_buy_position(position='LONG', quantity=quantity, current_price=close, sl_price=low)