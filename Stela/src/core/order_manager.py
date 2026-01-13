import logging
from binance.exceptions import BinanceAPIException
from ..shared.enums import Side, PositionSide, AlgoOrderType, OrderType
from ..shared.errors import ErrorManager, BinanceFatalError, BinanceRetryableError, BinanceStateError, BinanceClientException
from decimal import Decimal, getcontext
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from ..shared.msg import get_logger
from ..strategies.trading_params import MAX_RISK_RATIO
from src.shared.utils import *
from settings import ENABLE_ORDER


logger = logging.getLogger("ORDER_MANAGER")


getcontext().prec = 20

logger = get_logger("ORDER_MANAGER")

class OrderManager:
    def __init__(self, binance_client, setup_data, market_data, symbol):

        self.client = binance_client
        self.market_data = market_data
        self.symbol = symbol
        self.positions = self.market_data.positions

        self.stepSize = Decimal(setup_data.get('stepSize'))
        self.tickSize = Decimal(setup_data.get('tickSize'))
        self.minQty = Decimal(setup_data.get('minQty'))
        self.notional = Decimal(setup_data.get('notional'))

        self._symbol_info_cache: Dict[str, Dict[str, Any]] = {}
        self._leverage_cache: Dict[str, Decimal] = {}
        self._leverage_cache_time: Dict[str, datetime] = {}
        self._leverage_cache_timeout = timedelta(hours=1)

        self.initialize_bot_state()

    def get_leverage(self, symbol: str) -> Decimal:
        now = datetime.now()
        if symbol in self._leverage_cache and (now - self._leverage_cache_time.get(symbol, now)).total_seconds() < self._leverage_cache_timeout.total_seconds():
            return self._leverage_cache[symbol]
        try:
            positions = self.client.futures_position_information()
            leverage = Decimal('1')
            for pos in positions:
                if pos['symbol'] == symbol:
                    leverage = Decimal(pos['leverage'])
                    break
            self._leverage_cache[symbol] = leverage
            self._leverage_cache_time[symbol] = now
            return leverage
        except BinanceAPIException as e:
            logger.warning(f"Failed to fetch position information from Binance. Using default leverage of 1: {e}")
            return Decimal('1')

    def calculate_quantity_with_risk_management(
        self, 
        price: Decimal, 
        symbol: str,
        balance_usdt: Decimal,
        stop_loss_price: Decimal,
        position_side:PositionSide,
        risk_percentage: Decimal = MAX_RISK_RATIO,
    ) -> Decimal:
        """
        쿠라마기 자금 관리 원칙에 따라 매수 가능한 코인 수량을 계산합니다.
        (레버리지 변수 추가 버전)

        Args:
            balance_usdt (Decimal): 현재 계좌 잔고.
            price (Decimal): 진입 가격 (현재 시장 가격).
            stop_loss_price (Decimal): 손절매 가격.
            risk_percentage (Decimal): 계좌 잔고 대비 감수할 위험 비율 (예: 0.01 = 1%).
            leverage (Decimal): 레버리지 배수 (기본값: 1).
            symbol (str): 거래 심볼 (수량 정밀도 계산을 위해 필요).

        Returns:
            Decimal: 리스크 관리 원칙에 따라 계산된 매수 수량.
        """
        price = Decimal(str(price))
        balance_usdt = Decimal(str(balance_usdt))
        stop_loss_price = Decimal(str(stop_loss_price))
        risk_percentage = Decimal(str(risk_percentage))

        # position_side를 문자열로 통일
        if position_side not in [PositionSide.LONG, PositionSide.SHORT]:
            logger.error(f"Invalid position_side: {position_side}. Must be 'LONG' or 'SHORT'.")
            return Decimal('0')

        # 1. 최대 손실 금액 계산 (총 자산 기준)
        max_loss_amount = balance_usdt * (risk_percentage / 100) # 손절 시 usdt 금액

        # 2. 단위당 예상 손실 금액 계산 및 유효성 검사
        if position_side == PositionSide.LONG:
            # 롱 포지션: (진입가 - 손절가). 손절가는 진입가보다 낮아야 함.
            if stop_loss_price > price:
                logger.warning(f"LONG position stop loss price ({stop_loss_price}) is >= entry price ({price}). Returning 0 quantity.")
                return Decimal('0')
            loss_per_unit = price - stop_loss_price

        elif position_side == PositionSide.SHORT:
            # 숏 포지션: (손절가 - 진입가). 손절가는 진입가보다 높아야 함.
            if stop_loss_price < price:
                logger.warning(f"SHORT position stop loss price ({stop_loss_price}) is <= entry price ({price}). Returning 0 quantity.")
                return Decimal('0')
            loss_per_unit = stop_loss_price - price
        else:
            # 상단에서 이미 처리되었으나, 혹시 모를 경우를 대비
            return Decimal('0')

        # 3. 총 포지션 가치 계산
        quantity = max_loss_amount / loss_per_unit

        adjusted_quantity = round_step_size(quantity, self.stepSize) # 최대 손실 수량 (MAX_RISK_RATIO)

        # 3. [추가] 최소 수량(minQty) 검증
        # 계산된 수량이 최소 수량보다 작으면 주문을 내지 않거나 최소 수량으로 맞춤
        if adjusted_quantity < self.minQty:
            logger.info(f"[{symbol}] 주문 거부: 수량 미달 ({adjusted_quantity} < {self.minQty})")
            return Decimal('0')

        total_notional = adjusted_quantity * Decimal(str(price))
        if total_notional < self.notional:
            logger.info(f"[{symbol}] 주문 거부: 주문 금액 미달 ({total_notional:.2f} < {self.notional} USDT)")
            return Decimal('0')

        return adjusted_quantity

    def create_market_order(self, symbol: str, side: Side, type: OrderType, positionSide: PositionSide, quantity: Decimal) -> Optional[dict]:

        if side not in [Side.BUY, Side.SELL]:
            raise ValueError(f"Invalid side: {side}. Must be one of {['BUY', 'SELL']}")
        
        if positionSide not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"Invalid positionSide: {positionSide}. Must be one of {['BOTH', 'LONG', 'SHORT']}")
        try:
            # logger.info(f"Submitting MARKET order. Symbol: {symbol}, Side: {side}, Quantity: {quantity}")
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=type,
                quantity=quantity,
                positionSide=positionSide
            )
            # logger.info(f"MARKET order submitted. Order ID: {order['orderId']}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Error creating market order: {e}", exc_info=True)
            raise

    def initialize_bot_state(self, showLog:bool = True):

        if self.positions.long_amount == None and self.positions.long_entry_price == None:

            open_id = [self.positions.long_stop_loss_order_id, self.positions.long_take_profit_order_id]

            for id in open_id:
                if id != None and ENABLE_ORDER:
                    if showLog:
                        logger.info(f"{self.symbol} Long Position Not open, cancel Long Exit Order. ID: {id}")
                    self.cancel_algo_order(self.symbol, id)

        if self.positions.short_amount == None and self.positions.short_entry_price == None:

            open_id = [self.positions.short_stop_loss_order_id, self.positions.short_take_profit_order_id]

            for id in open_id:
                if id != None and ENABLE_ORDER:
                    if showLog:
                        logger.info(f"{self.symbol} Short Position Not open, cancel Short Exit Order. ID: {id}")
                    self.cancel_algo_order(self.symbol, id)

    def _verify_order_and_state(self) -> bool:
        try:
            position_info = self.client.futures_position_information(symbol=self.symbol)

            if (len(position_info) > 0 and (position_info[0]['positionSide'] == PositionSide.LONG.value) or (position_info[0]['positionSide'] == PositionSide.SHORT.value)):
                logger.info("CONFIRMATION: A new position was successfully opened despite the API error.")
                self.initialize_bot_state()
                return True

            open_orders = self.client.futures_get_all_orders(symbol=self.symbol)
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
    
    def create_algo_exit_order(self, symbol:str, positionSide:PositionSide, type:AlgoOrderType, amount:Decimal, tp:Decimal) -> Tuple[Decimal, str]:

        match positionSide:
            case PositionSide.LONG:
                side = Side.SELL
            case PositionSide.SHORT:
                side = Side.BUY
        try:
            order = self.client.futures_create_algo_order(
                symbol=symbol,
                side=side,
                positionSide=positionSide,
                type=type,
                quantity=amount,
                triggerPrice=tp,
            )
            return order.get('triggerPrice'), order.get('clientAlgoId')

        except Exception as e:
            logger.warning(f"Failed to position close order : {e}")

    def cancel_algo_order(self, symbol:str, order_id:str):
        try:
            self.client.futures_cancel_algo_order(
                symbol=symbol,
                clientAlgoId=order_id
            )
            #logger.info(f"Successfully cancelled stop-market algo order: {order_id}")
        except Exception as e:
            # 이미 취소되었거나 존재하지 않을 경우 발생하는 에러(-2011 등)를 잡아서 로그 출력
            logger.warning(f"Failed to cancel order {order_id}: {e}")

    def create_buy_position(self, position:PositionSide, quantity: Decimal, current_price: Decimal, sl_price: Decimal, tp_price: Decimal = None):
        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        if position == PositionSide.LONG:
            side = Side.BUY
        elif position == PositionSide.SHORT:
            side = Side.SELL
        try:
            order = self.create_market_order(
                symbol=self.symbol,
                side=side,
                type=OrderType.MARKET,
                quantity=quantity,
                positionSide=position,
            )
            if order:
                # 손절매 주문 생성 전, 기존 포지션이 있을 경우 평균 단가 계산
                if position == PositionSide.LONG:
                    # 추가 매수시 평균 단가 계산
                    if self.positions.long_amount:
                        old_total_value = self.positions.long_amount * self.positions.long_entry_price
                        new_total_value = old_total_value + (quantity * current_price)
                        new_total_amount = Decimal(str(self.positions.long_amount + quantity))
                        self.positions.long_entry_price = Decimal(str(new_total_value / new_total_amount))
                        self.positions.long_amount = new_total_amount
                        # logger.info(f"Long Position added. New total quantity: {new_total_amount:.4f}, New average entry price: {self.positions.long_entry_price:.4f}")
                    else:
                        # 첫 진입 시
                        self.positions.long_amount = quantity
                        self.positions.long_entry_price = current_price

                    if sl_price < self.positions.long_entry_price:
                        # 기존 손절매 주문이 있다면 취소
                        if self.positions.long_stop_loss_order_id:
                            self.cancel_algo_order(self.symbol, order_id=self.positions.long_stop_loss_order_id)

                        tp, algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.STOP_MARKET,
                            amount=quantity,
                            tp=sl_price,
                        )
                        self.positions.long_stop_loss = tp
                        self.positions.long_stop_loss_order_id = algoId
                        # logger.info(f"New long stop-loss order placed with updated quantity and price. {tp} {algoId}")

                    if tp_price and tp_price > self.positions.long_entry_price:
                        # 기존 손절매 주문이 있다면 취소
                        if self.positions.long_take_profit_order_id:
                            self.cancel_algo_order(self.symbol, order_id=self.positions.long_take_profit_order_id)

                        tp, algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.TAKE_PROFIT_MARKET,
                            amount=quantity,
                            tp=tp_price,
                        )
                        self.positions.long_take_profit = tp
                        self.positions.long_take_profit_order_id = algoId
                        # logger.info(f"New long take-profit order placed with updated quantity and price. {tp} {algoId}")

                elif position == PositionSide.SHORT:
                    # 추가 매수시 평균 단가 계산
                    if self.positions.short_amount:
                        old_total_value = self.positions.short_amount * self.positions.short_entry_price
                        new_total_value = old_total_value + (quantity * current_price)
                        new_total_amount = self.positions.short_amount + quantity
                        self.positions.short_entry_price = new_total_value / new_total_amount
                        self.positions.short_amount = new_total_amount
                        # logger.info(f"Short Position added. New total quantity: {new_total_amount:.4f}, New average entry price: {self.positions.short_entry_price:.4f}")
                    else:
                        # 첫 진입 시 초기화
                        self.positions.short_amount = quantity
                        self.positions.short_entry_price = Decimal(str(current_price))

                    # Short Stop Loss Order
                    if sl_price and self.positions.short_entry_price and sl_price > self.positions.short_entry_price:
                        # 기존 손절매 주문이 있다면 취소
                        if self.positions.short_stop_loss_order_id:
                            self.cancel_algo_order(self.symbol, order_id=self.positions.short_stop_loss_order_id)
                        tp, algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.STOP_MARKET,
                            amount=quantity,
                            tp=sl_price,
                        )
                        self.positions.short_stop_loss = tp
                        self.positions.short_stop_loss_order_id = algoId
                        # logger.info(f"New short stop-loss order placed with updated quantity and price. {tp} {algoId}")

                    # Short Take Profit Order
                    if tp_price and self.positions.short_entry_price and tp_price < self.positions.short_entry_price:
                        # 기존 익절매 주문이 있다면 취소
                        if self.positions.short_take_profit_order_id:
                            self.cancel_algo_order(self.symbol, self.positions.short_take_profit_order_id)
                        tp, algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.TAKE_PROFIT_MARKET,
                            amount=quantity,
                            tp=tp_price,
                        )
                        self.positions.short_take_profit = tp
                        self.positions.short_take_profit_order_id = algoId
                        # logger.info(f"New short take-profit order placed with updated quantity and price. {tp} {algoId}")


        except BinanceClientException as e:
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")
            order_status_verified = self._verify_order_and_state()
            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")
        except BinanceAPIException as e:
            error_code = getattr(e, 'code', None)
            exc_class = ErrorManager.get_exception_class(error_code)
            friendly_msg = ErrorManager.get_friendly_message(error_code, e.message)

            if exc_class == BinanceFatalError:
                logger.critical(f"FATAL ERROR: {friendly_msg}. (Error code: {error_code})", exc_info=True)
            else:
                logger.error(f"Failed to open {position} position: {e.message} (Error code: {e.code})", exc_info=True)
            raise e