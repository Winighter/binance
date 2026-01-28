import logging
from ..shared.enums import Side, PositionSide, AlgoOrderType, OrderType
from ..shared.errors import BinanceClientException
from ..shared.typings import *
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

        self.initialize_bot_state(showLog = True)

        self.stepSize = Decimal(setup_data.get('stepSize'))
        self.tickSize = Decimal(setup_data.get('tickSize'))
        self.minQty = Decimal(setup_data.get('minQty'))
        self.notional = Decimal(setup_data.get('notional'))

        self._symbol_info_cache: Dict[str, Dict[str, Any]] = {}
        self._leverage_cache: Dict[str, Decimal] = {}
        self._leverage_cache_time: Dict[str, datetime] = {}
        self._leverage_cache_timeout = timedelta(hours=1)


    def get_leverage(self, symbol: str) -> Decimal:
        now = datetime.now()
        if symbol in self._leverage_cache and (now - self._leverage_cache_time.get(symbol, now)).total_seconds() < self._leverage_cache_timeout.total_seconds():
            return self._leverage_cache[symbol]

        positions = self.client.futures_position_information()
        leverage = Decimal('1')
        for pos in positions:
            if pos['symbol'] == symbol:
                leverage = Decimal(pos['leverage'])
                break
        self._leverage_cache[symbol] = leverage
        self._leverage_cache_time[symbol] = now
        return leverage

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
            logger.info(f"[{symbol}] Order Rejected: Quantity below minimum ({adjusted_quantity} < {self.minQty})")
            return Decimal('0')

        total_notional = adjusted_quantity * Decimal(str(price))
        if total_notional < self.notional:
            logger.info(f"[{symbol}] Order Rejected: Notional value below minimum ({total_notional:.2f} < {self.notional} USDT))")
            return Decimal('0')

        return adjusted_quantity

    def create_market_order(self, symbol: str, side: Side, positionSide: PositionSide, quantity: Decimal, price:Decimal) -> Optional[dict]:

        if side not in [Side.BUY, Side.SELL]:
            raise ValueError(f"Invalid side: {side}. Must be one of {['BUY', 'SELL']}")
        
        if positionSide not in [PositionSide.BOTH, PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"Invalid positionSide: {positionSide}. Must be one of {['BOTH', 'LONG', 'SHORT']}")
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                positionSide=positionSide,
                quantity=quantity,
                price=price,
            )
            return order
        except BinanceClientException as e:
            logger.error(f"Error creating market order: {e}", exc_info=True)
            raise

    def update_exit_algo_order(self, ps:PositionSide, else_orderid:str, showLog:bool = False, order_lock:bool = ENABLE_ORDER):

        if order_lock:

            if ps == PositionSide.LONG:

                if not self.positions.long_amount and not self.positions.long_entry_price:

                    open_id = [self.positions.long_stop_loss_order_id, self.positions.long_take_profit_order_id]
                    for id in open_id:
                        id = str(id)
                        if id != else_orderid:
                            if showLog:
                                logger.info(f"{self.symbol} {id} Long Position Not open, cancel Long Exit Order.")
                            
                            self.cancel_algo_order(self.symbol, id)

            elif ps == PositionSide.SHORT:

                if not self.positions.short_amount and not self.positions.short_entry_price:

                    open_id = [self.positions.short_stop_loss_order_id, self.positions.short_take_profit_order_id]
                    for id in open_id:
                        id = str(id)
                        if id != else_orderid:
                            if showLog:
                                logger.info(f"{self.symbol} {id} Short Position Not open, cancel Short Exit Order.")

                            self.cancel_algo_order(self.symbol, id)

    def initialize_bot_state(self, order_lock:bool = ENABLE_ORDER, showLog:bool = False):

        if order_lock:

            if not self.positions.long_amount and not self.positions.long_entry_price:

                open_id = [self.positions.long_stop_loss_order_id, self.positions.long_take_profit_order_id]
                if showLog and open_id != [None, None]:
                    logger.info(f'Long Order IDs {open_id}')
                for id in open_id:
                    if id != None:
                        if showLog:
                            logger.info(f"{self.symbol} {id} Long Position Not open, cancel Long Exit Order.")
                        self.cancel_algo_order(self.symbol, id)

            if not self.positions.short_amount and not self.positions.short_entry_price:

                open_id = [self.positions.short_stop_loss_order_id, self.positions.short_take_profit_order_id]
                if showLog and open_id != [None, None]:
                    logger.info(f'Short Order IDs {open_id}')
                for id in open_id:
                    if id != None:
                        if showLog:
                            logger.info(f"{self.symbol} {id} Short Position Not open, cancel Short Exit Order.")
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
    
    def create_algo_exit_order(self, symbol:str, positionSide:PositionSide, type:AlgoOrderType, amount:Decimal, triggerPrice:Decimal) -> str:
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
                triggerPrice=triggerPrice,
            )
            return str(order.get('algoId'))
        except Exception as e:
            logger.warning(f"Failed to position close order : {e}")
            return None

    def cancel_algo_order(self, symbol:str, algoId:str):
        try:
            self.client.futures_cancel_algo_order(
                symbol=symbol,
                algoId=algoId
            )
        except Exception as e:
            # 이미 취소되었거나 존재하지 않을 경우 발생하는 에러(-2011 등)를 잡아서 로그 출력
            logger.warning(f"Failed to cancel order {algoId}: {e}")

    def create_buy_position(self, position:PositionSide, quantity: Decimal, sl_price: Decimal, entry_price: Decimal,  tp_price: Decimal, default_stop_loss:Decimal):
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
                positionSide=position,
                quantity=quantity,
                price=entry_price
            )
            if order:
                # 손절매 주문 생성 전, 기존 포지션이 있을 경우 평균 단가 계산
                if position == PositionSide.LONG:
                    # 첫 진입 시
                    self.positions.long_amount = quantity
                    self.positions.long_entry_price = entry_price
                    self.positions.long_default_stop_loss = default_stop_loss

                    self.cancel_all_exit_algo_order(PositionSide.LONG)

                    if sl_price < self.positions.long_entry_price:
                        algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.STOP_MARKET,
                            amount=quantity,
                            triggerPrice=sl_price,
                        )
                        self.positions.long_stop_loss = sl_price
                        self.positions.long_stop_loss_order_id = algoId
                        logger.info(f"New long stop-loss order placed with updated quantity and price. {sl_price} {algoId}")

                    if tp_price > self.positions.long_entry_price:
                        algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.TAKE_PROFIT_MARKET,
                            amount=quantity,
                            triggerPrice=tp_price,
                        )
                        self.positions.long_take_profit = tp_price
                        self.positions.long_take_profit_order_id = algoId
                        logger.info(f"New long take-profit order placed with updated quantity and price. {tp_price} {algoId}")

                elif position == PositionSide.SHORT:
                    # 첫 진입 시 초기화
                    self.positions.short_amount = quantity
                    self.positions.short_entry_price = entry_price
                    self.positions.short_default_stop_loss = default_stop_loss

                    self.cancel_all_exit_algo_order(PositionSide.SHORT)

                    # Short Stop Loss Order
                    if self.positions.short_entry_price and sl_price > self.positions.short_entry_price:
                        algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.STOP_MARKET,
                            amount=quantity,
                            triggerPrice=sl_price,
                        )
                        logger.info(f"New short stop-loss order placed with updated quantity and price. {sl_price} {algoId}")
                        self.positions.short_stop_loss = sl_price
                        self.positions.short_stop_loss_order_id = algoId

                    # Short Take Profit Order
                    if self.positions.short_entry_price and tp_price < self.positions.short_entry_price:
                        algoId = self.create_algo_exit_order(
                            symbol=self.symbol,
                            positionSide=position,
                            type=AlgoOrderType.TAKE_PROFIT_MARKET,
                            amount=quantity,
                            triggerPrice=tp_price,
                        )
                        logger.info(f"New short take-profit order placed with updated quantity and price. {tp_price} {algoId}")
                        self.positions.short_take_profit = tp_price
                        self.positions.short_take_profit_order_id = algoId

        except BinanceClientException as e:
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")
            order_status_verified = self._verify_order_and_state()
            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")

    def cancel_all_exit_algo_order(self, ps:PositionSide):

        match ps:
            case PositionSide.LONG:
                if self.positions.long_stop_loss_order_id:
                    self.cancel_algo_order(self.symbol, self.positions.long_stop_loss_order_id)
                if self.positions.long_take_profit_order_id:
                    self.cancel_algo_order(self.symbol, self.positions.long_take_profit_order_id)

            case PositionSide.SHORT:
                if self.positions.short_stop_loss_order_id:
                    self.cancel_algo_order(self.symbol, self.positions.short_stop_loss_order_id)
                if self.positions.short_take_profit_order_id:
                    self.cancel_algo_order(self.symbol, self.positions.short_take_profit_order_id)

    def update_exit_order(self, ps:PositionSide, amount:Decimal, entry_price:Decimal, sl_price:Decimal, tp_price:Decimal, showLog:bool = False):
        try:
            if ps == PositionSide.LONG:
                self.positions.long_amount = amount
                self.positions.long_entry_price = entry_price

                if sl_price < entry_price and self.positions.long_stop_loss != sl_price:
                    if self.positions.long_stop_loss_order_id:
                        self.cancel_algo_order(self.symbol, self.positions.long_stop_loss_order_id)
                    logger.info(f"TEst SL Pirce: {sl_price} {entry_price}")
                    algoId = self.create_algo_exit_order(
                        symbol=self.symbol,
                        positionSide=ps,
                        type=AlgoOrderType.STOP_MARKET,
                        amount=amount,
                        triggerPrice=sl_price,
                    )
                    if showLog:
                        logger.info(f"Update Exit Long SL Order {sl_price} {algoId}")
                    self.positions.long_stop_loss = sl_price
                    self.positions.long_stop_loss_order_id = algoId

                if tp_price > self.positions.long_entry_price and self.positions.long_take_profit != tp_price:
                    if self.positions.long_take_profit_order_id:
                        self.cancel_algo_order(self.symbol, self.positions.long_take_profit_order_id)

                    algoId = self.create_algo_exit_order(
                        symbol=self.symbol,
                        positionSide=ps,
                        type=AlgoOrderType.TAKE_PROFIT_MARKET,
                        amount=amount,
                        triggerPrice=tp_price,
                    )
                    if showLog:
                        logger.info(f"Update Exit Long TP Order {tp_price} {algoId}")
                    self.positions.long_take_profit = tp_price
                    self.positions.long_take_profit_order_id = algoId

            elif ps == PositionSide.SHORT:
                self.positions.short_amount = amount
                self.positions.short_entry_price = entry_price

                # Short Stop Loss Order
                if sl_price > self.positions.short_entry_price and sl_price != self.positions.short_stop_loss:
                    if self.positions.short_stop_loss_order_id:
                        self.cancel_algo_order(self.symbol, self.positions.short_stop_loss_order_id)
                    algoId = self.create_algo_exit_order(
                        symbol=self.symbol,
                        positionSide=ps,
                        type=AlgoOrderType.STOP_MARKET,
                        amount=amount,
                        triggerPrice=sl_price,
                    )
                    if showLog:
                        logger.info(f"Update Exit Short SL Order {sl_price} {algoId}")
                    self.positions.short_stop_loss = sl_price
                    self.positions.short_stop_loss_order_id = algoId

                # Short Take Profit Order
                if tp_price < self.positions.short_entry_price and self.positions.short_take_profit != tp_price:
                    if self.positions.short_take_profit_order_id:
                        self.cancel_algo_order(self.symbol, self.positions.short_take_profit_order_id)
                    algoId = self.create_algo_exit_order(
                        symbol=self.symbol,
                        positionSide=ps,
                        type=AlgoOrderType.TAKE_PROFIT_MARKET,
                        amount=amount,
                        triggerPrice=tp_price,
                    )
                    if showLog:
                        logger.info(f"Update Exit Short TP Order {tp_price} {algoId}")
                    self.positions.short_take_profit = tp_price
                    self.positions.short_take_profit_order_id = algoId

        except BinanceClientException as e:
            logger.error(f"FATAL: Exit Order submission failed after all retries. Error: {e}")
            order_status_verified = self._verify_order_and_state()
            if order_status_verified:
                logger.info("CONFIRMATION: Exit Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")
