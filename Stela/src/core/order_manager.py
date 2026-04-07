import logging
from ..shared.enums import Side, PositionSide, AlgoOrderType, OrderType
from ..shared.errors import BinanceClientException
from ..shared.typings import *
from datetime import datetime, timedelta
from ..shared.msg import get_logger
from ..strategies.trading_params import MAX_RISK_RATIO, MAX_POSITION_RATIO
from src.shared.utils import *
from settings import *
from ..config import BINANCE_FEE_PERCENT

logger = logging.getLogger("ORDER_MANAGER")


getcontext().prec = 20

logger = get_logger("ORDER_MANAGER")

class OrderManager:
    def __init__(self, binance_client, setup_data, market_data, symbol):

        self.client = binance_client
        self.market_data = market_data
        self.symbol = symbol
        self.balances = self.market_data.balances
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
        entry: Decimal, 
        symbol: str,
        total_balance: Decimal,
        stop_loss: Decimal,
        position_side:PositionSide
    ) -> Decimal:
        maximum_position_limit = Decimal(str(MAX_POSITION_RATIO / 100)) # 0.4
        entry = Decimal(str(entry))
        total_balance = Decimal(str(total_balance))
        stop_loss = Decimal(str(stop_loss))
        risk_percentage = Decimal(str(MAX_RISK_RATIO))
        fee_rate = Decimal(str(BINANCE_FEE_PERCENT / 100))
        total_fee = Decimal(str((entry + stop_loss) * fee_rate))

        # 1. 최대 손실 포지션 크기 계산 (총 자산 기준)
        max_loss_position = total_balance * (risk_percentage / 100) # 손절 시 usdt 금액
        loss_unit = total_fee + (entry - stop_loss) if position_side == PositionSide.LONG else total_fee + (stop_loss - entry) # 포지션이 없을 경우 0

        # 3. 총 포지션 가치 계산
        quantity = max_loss_position / loss_unit
        maximum_quantity = (total_balance * maximum_position_limit - total_fee) / stop_loss

        if quantity > maximum_quantity:
            quantity = maximum_quantity

        adjusted_quantity = round_step_size(quantity, self.stepSize) # 최대 손실 수량 (MAX_RISK_RATIO)

        # 3. [추가] 최소 수량(minQty) 검증
        # 계산된 수량이 최소 수량보다 작으면 주문을 내지 않거나 최소 수량으로 맞춤
        if adjusted_quantity < self.minQty:
            logger.info(f"[{symbol}] Order Rejected: Quantity below minimum ({adjusted_quantity} < {self.minQty})")
            return Decimal('0')

        total_notional = adjusted_quantity * Decimal(str(entry))
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

    def update_exit_algo_order(self, ps:PositionSide, finished_id:List, showLog:bool = False, order_lock:bool = ENABLE_ORDER):

        if order_lock:
            order_id = None

            if ps == PositionSide.LONG:

                open_long = self.positions.long_amount and self.positions.long_entry_price
                stop_loss = self.positions.long_stop_loss and self.positions.long_stop_loss_order_id
                take_profit = self.positions.long_take_profit and self.positions.long_take_profit_order_id

                if not open_long:

                    if not stop_loss and take_profit and not finished_id[1]:
                        order_id = self.positions.long_take_profit_order_id

                    if not take_profit and stop_loss and not finished_id[0]:
                        order_id = self.positions.long_stop_loss_order_id

            elif ps == PositionSide.SHORT:
                
                open_short = self.positions.short_amount and self.positions.short_entry_price
                stop_loss = self.positions.short_stop_loss and self.positions.short_stop_loss_order_id
                take_profit = self.positions.short_take_profit and self.positions.short_take_profit_order_id

                if not open_short:

                    if not stop_loss and take_profit and not finished_id[1]:
                        order_id = self.positions.short_take_profit_order_id

                    if not take_profit and stop_loss and not finished_id[0]:
                        order_id = self.positions.short_stop_loss_order_id

            if order_id:
                self.cancel_algo_order(self.symbol, order_id)

    def initialize_bot_state(self, order_lock:bool = ENABLE_ORDER, showLog:bool = False):

        if order_lock:

            long_orders = [None, None]
            open_long = self.positions.long_amount and self.positions.long_entry_price
            long_stop_loss = self.positions.long_stop_loss and self.positions.long_stop_loss_order_id
            long_take_profit = self.positions.long_take_profit and self.positions.long_take_profit_order_id

            if not open_long:

                if long_stop_loss:
                    long_orders[0] = self.positions.long_stop_loss_order_id

                if long_take_profit:
                    long_orders[1] = self.positions.long_take_profit_order_id

                if long_orders != [None, None]:

                    for i in range(len(long_orders)):

                        if long_orders[i]:
                            lr = self.cancel_algo_order(self.symbol, long_orders[i])
                            if lr:
                                if i == 0:
                                    self.positions.long_stop_loss = None
                                    self.positions.long_stop_loss_order_id = None
                                elif i == 1:
                                    self.positions.long_take_profit = None
                                    self.positions.long_take_profit_order_id = None

            short_orders = [None, None]
            open_short = self.positions.short_amount and self.positions.short_entry_price
            short_stop_loss = self.positions.short_stop_loss and self.positions.short_stop_loss_order_id
            short_take_profit = self.positions.short_take_profit and self.positions.short_take_profit_order_id

            if not open_short:

                if short_stop_loss:
                    short_orders[0] = self.positions.short_stop_loss_order_id

                if short_take_profit:
                    short_orders[1] = self.positions.short_take_profit_order_id

                if short_orders != [None, None]:

                    for i in range(len(short_orders)):
                        
                        if short_orders[i]:
                            sr = self.cancel_algo_order(self.symbol, short_orders[i])
                            if sr:
                                if i == 0:
                                    self.positions.short_stop_loss = None
                                    self.positions.short_stop_loss_order_id = None

                                elif i == 1:
                                    self.positions.short_take_profit = None
                                    self.positions.short_take_profit_order_id = None

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
            r = self.client.futures_cancel_algo_order(
                symbol=symbol,
                algoId=algoId
            )
            return r.get('algoId', None)
        except Exception as e:
            # 이미 취소되었거나 존재하지 않을 경우 발생하는 에러(-2011 등)를 잡아서 로그 출력
            logger.warning(f"Failed to cancel order {algoId}: {e}")

    def create_buy_position(self, position:PositionSide, quantity: Decimal, sl_price: Decimal, entry_price: Decimal,  tp_price: Decimal):
        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')

        bids, asks = self.client.futures_order_book(self.symbol)
        long_entry = bids[0]
        short_entry = asks[0]

        e_price = None
        if position == PositionSide.LONG:
            side = Side.BUY
            e_price = Decimal(long_entry[0])
            if (sl_price < e_price < tp_price) == False:
                logger.warning(f"Bids Invalid Error {sl_price} {e_price} {tp_price}")
        elif position == PositionSide.SHORT:
            side = Side.SELL
            e_price = Decimal(short_entry[0])
            if (sl_price > e_price > tp_price) == False:
                logger.warning(f"Asks Invalid Error {sl_price} {e_price} {tp_price}")
        try:
            check_order_book = self.client.futures_check_orderbook_quantity(self.symbol, position, e_price, quantity)
            if not check_order_book:
                logger.warning(f'[{self.symbol}] check_order_book {position} {e_price} {quantity}')

            order = self.create_market_order(
                symbol=self.symbol,
                side=side,
                positionSide=position,
                quantity=quantity,
                price=entry_price
            )
            if order:
                if position == PositionSide.LONG:
                    # 첫 진입 시
                    self.positions.long_amount = quantity
                    self.positions.long_entry_price = entry_price

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

                elif position == PositionSide.SHORT:
                    # 첫 진입 시 초기화
                    self.positions.short_amount = quantity
                    self.positions.short_entry_price = entry_price

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

    def get_position_quantity(self, position:PositionSide, entry: Decimal, stop_loss: Decimal, total_balance: Decimal = None):

        '''
        수량을 계산할때 적용하는 원칙
        1. 포지션 보유가능한 최대치 제한 (자산 기준 최대 40%)
        2. 손절 체결시 손실 제한 (자산 기준 최대 1%)
        '''

        if not total_balance:
            total_balance = self.balances.balance

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        try:
            quantity = self.calculate_quantity_with_risk_management(
                entry=entry,
                symbol=self.symbol,
                total_balance=total_balance,
                stop_loss=stop_loss,
                position_side=position
            )
            if quantity > 0:
                # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                adjusted_quantity = round_step_size(quantity, self.stepSize)
                return adjusted_quantity
            else:
                logger.warning(f"Order skipped for {self.symbol} due to filter constraints.")

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0
