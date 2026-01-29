import logging
from ..shared.typings import *
from settings import ENABLE_ORDER, ENABLE_SIMULATION, ENABLE_DISCORD_ALERTS
from ..shared.enums import PositionSide, OrderSignal, UserDataEventType, AssetType, UserDataEventReasonType
from ..config import *
from ..strategies.smc import SmartMoneyConcept
from .simulator import TradeSimulator
from ..shared.msg import *
from ..strategies.trading_params import RISK_REWARD_RAITO, MAX_STOP_LOSS_RATIO, MAX_POSITION_RATIO
from src.shared.utils import *

logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, market_data, order_manager, symbol, leverage, kline_interval, setup_data):

        self.client = binance_client
        self.market_data = market_data
        self.order_manager = order_manager
        self.symbol = symbol
        self.leverage = int(str(leverage))
        interval_str = kline_interval.code if hasattr(kline_interval, 'code') else kline_interval
        self.kline_interval = interval_str
        self.stepSize = setup_data.get('stepSize')
        self.tickSize = setup_data.get('tickSize')
        self.slippage_percent = Decimal(str(SLIPPAGE_PERCENT / 100))

        self.opens = self.market_data.open_prices
        self.highs = self.market_data.high_prices
        self.lows = self.market_data.low_prices
        self.closes = self.market_data.close_prices

        self.positions = self.market_data.positions
        self.balances = self.market_data.balances

        # self.bnb_price = Decimal('0')

        self.long_fee = Decimal('0')
        self.short_fee = Decimal('0')

        self.sync_initial_exit_levels()

        if ENABLE_ORDER and ENABLE_SIMULATION:
            # 로그는 최대한 자세하게 (표준형)
            logger.critical("Configuration conflict detected: ENABLE_ORDER and ENABLE_SIMULATION cannot both be True.")
            
            # 에러 출력은 사용자에게 조치 방법을 안내 (직관형)
            raise ValueError("Invalid setup: Please enable either ENABLE_ORDER or ENABLE_SIMULATION, not both.")

        ### SmartMoneyConcept Instance ###
        if app_config.ENABLE_SIMULATION:
            self.simulator = TradeSimulator(self.order_manager, self.symbol, self.leverage)
        self.smc_analyzer = SmartMoneyConcept()

        self.process_trading_signals()

    def get_position_quantity(self, position:PositionSide, price: Decimal, stop_loss_price: Decimal):

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        try:
            price_leverage = self.leverage * price
            max_position_value = self.balances.balance * self.leverage * Decimal(str(MAX_POSITION_RATIO / 100))

            if position == PositionSide.LONG:
                quantity = self.order_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.balances.balance,
                    stop_loss_price=stop_loss_price,
                    position_side=position
                )
                if quantity > 0:
                    # 2. 포지션 규모(총 가치) 계산
                    position_value = quantity * price_leverage

                    # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.balances.available_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = round_step_size(new_quantity, self.stepSize)
                            return adjusted_quantity

                    adjusted_quantity = round_step_size(quantity, self.stepSize)
                    return adjusted_quantity
                else:
                    logger.warning(f"Order skipped for {self.symbol} due to filter constraints.")

            elif position == PositionSide.SHORT:
                quantity = self.order_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.balances.balance,
                    stop_loss_price=stop_loss_price,
                    position_side=position
                )
                if quantity > 0:
                    # 2. 포지션 규모(총 가치) 계산
                    position_value = quantity * price_leverage

                    # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.balances.available_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = round_step_size(new_quantity, self.stepSize)
                            return adjusted_quantity

                    adjusted_quantity = round_step_size(quantity, self.stepSize)
                    return adjusted_quantity
                else:
                    logger.warning(f"Order skipped for {self.symbol} due to filter constraints.")

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def trading_signal(self, long_signals, short_signals):
        long = None
        short = None

        # 리스트가 비어있지 않은지 먼저 확인
        if long_signals and len(long_signals) > 0:
            latest_long = max(long_signals, key=lambda x: x[0])
            long = [latest_long[0], latest_long[1], latest_long[2], latest_long[3], latest_long[4]]

        if short_signals and len(short_signals) > 0:
            latest_short = max(short_signals, key=lambda x: x[0])
            short = [latest_short[0], latest_short[1], latest_short[2], latest_short[3], latest_short[4]]

        return long, short

    def process_exit_levels(self, long_raw: Dict = None, short_raw: Dict = None):

        # 시그널 데이터 처리 및 None 필터링
        total_len = len(self.lows)

        long_signals = []
        if long_raw:
            for idx, value in long_raw.items():
                sl, entry = value[0], value[1]
                df_sl, f_sl, f_tp = self.calculate_logic(PositionSide.LONG, sl, entry)
                if df_sl and f_sl and f_tp: # 수익성이 있는 신호만 추가
                    # logger.info(f"LONG {total_len-idx, f_sl, entry, f_tp, df_sl}")
                    long_signals.append([idx, f_sl, entry, f_tp, df_sl])

        short_signals = []
        if short_raw:
            for idx, value in short_raw.items():
                sl, entry = value[0], value[1]
                df_sl, f_sl, f_tp = self.calculate_logic(PositionSide.SHORT, sl, entry)
                if df_sl and f_sl and f_tp: # 수익성이 있는 신호만 추가
                    # logger.info(f"SHORT {total_len-idx, f_sl, entry, f_tp, df_sl}")
                    short_signals.append([idx, f_sl, entry, f_tp, df_sl])

        return long_signals, short_signals

    def process_trading_signals(self):

        # 1. MarketData에서 최적화된 Numpy 데이터 생성
        common_data = self.market_data.get_analysis_data()

        # 2. 분석기에 데이터 주입 (BaseStrategy에서 상속받은 함수)
        self.smc_analyzer.update_data(common_data)

        # 3. 데이터가 주입된 후 분석 실행
        long_signals, short_signals = self.smc_analyzer.analyze(Strategies.LIQUIDITY_SWEEP)

        long_signal_with_exit, short_signal_with_exit = self.process_exit_levels(long_signals, short_signals)

        # 신호 필터 함수

        if app_config.ENABLE_SIMULATION:
            self.simulator.run(long_signal_with_exit, short_signal_with_exit, self.market_data.high_prices, self.market_data.low_prices, self.stepSize)

        long, short = self.trading_signal(long_signal_with_exit, short_signal_with_exit)

        return long, short

    def process_stream_data(self, res):

        stream_name = res.get('stream', 'UNKNOWN_STREAM')
        try:
            if 'stream' in res and 'data' in res:
                stream_name = res.get('stream', 'Unknown Stream')
                stream_data = res.get('data')

                # Stream Data 1
                if stream_name == f"{self.symbol.lower()}@kline_{self.kline_interval}":
                    # logger.info(f"{res}")

                    kline_data = stream_data.get('k')
                    if kline_data and kline_data.get('x'):

                        # First, Update Recent Candle
                        self.market_data.update_candle_data(kline_data)

                        # Second, Analysis Data and Get Signal
                        _long, _short = self.process_trading_signals()

                        long_signal = OrderSignal.NO_SIGNAL
                        short_signal = OrderSignal.NO_SIGNAL

                        total_len = len(self.lows)

                        if _long:
                            long_index = int(_long[0])
                            long_stop_loss = Decimal(str(_long[1]))
                            long_entry = Decimal(str(_long[2]))
                            long_take_profit = Decimal(str(_long[3]))
                            long_default_stop_loss = Decimal(str(_long[4]))
                            if total_len - long_index == 1:
                                long_signal = OrderSignal.OPEN_POSITION

                        if _short:
                            short_index = int(_short[0])
                            short_stop_loss = Decimal(str(_short[1]))
                            short_entry = Decimal(str(_short[2]))
                            short_take_profit = Decimal(str(_short[3]))
                            short_default_stop_loss = Decimal(str(_short[4]))
                            if total_len - short_index == 1:
                                short_signal = OrderSignal.OPEN_POSITION

                        # Third, Start Order
                        if ENABLE_ORDER:
                            if long_signal != OrderSignal.NO_SIGNAL:
                                self.execute_trade(PositionSide.LONG, long_signal, long_stop_loss, long_entry, long_take_profit, long_default_stop_loss)
                            if short_signal != OrderSignal.NO_SIGNAL:
                                self.execute_trade(PositionSide.SHORT, short_signal, short_stop_loss, short_entry, short_take_profit, short_default_stop_loss)
                        else:
                            if long_signal is not OrderSignal.NO_SIGNAL:
                                logger.info(f"[LONG] {long_signal}, Stop Loss: {long_stop_loss}, Entry: {long_entry}, Take Profit: {long_take_profit}")
                            if short_signal is not OrderSignal.NO_SIGNAL:
                                logger.info(f"[SHORT] {short_signal}, Stop Loss: {short_stop_loss}, Entry: {short_entry}, Take Profit: {short_take_profit}")

        except Exception as e:
            logger.error(f"Unexpected error during data processing: {e}", exc_info=True)
            raise e

    def process_user_data(self, user_data):
        try:
            user_event = user_data.get('e')
            timestamp = user_data.get('T')
            # logger.info(f"user: {user_data}")
            match user_event:

                case UserDataEventType.ALGO_UPDATE.value:

                    algo_data = user_data.get('o')
                    aoes = str(algo_data.get('X')) # algoOrderEventStatus

                    if algo_data.get('s') == self.symbol and aoes in [AlgoOrderEventStatus.NEW.value, AlgoOrderEventStatus.FINISHED.value, AlgoOrderEventStatus.CANCELED.value]:

                        aid = str(algo_data.get('aid')) # Algo Order ID
                        exit_type = str(algo_data.get('o')) # 'STOP_MARKET' or 'TAKE_PROFIT_MARKET'
                        side = str(algo_data.get('S')) # 'BUY' or 'SELL'
                        ps = str(algo_data.get('ps')) # 'LONG' or 'SHORT'
                        trigger_price = Decimal(str(algo_data.get('tp'))) # '1.2345'

                        # State Conditions
                        is_open_long = self.positions.long_amount and self.positions.long_entry_price and self.positions.long_default_stop_loss
                        is_open_short = self.positions.short_amount and self.positions.short_entry_price and self.positions.short_default_stop_loss

                        long_exit_side = side == Side.SELL.value and ps == PositionSide.LONG.value # Close Long
                        short_exit_side = side == Side.BUY.value and ps == PositionSide.SHORT.value # Close Short

                        exit_sm_type = exit_type == AlgoOrderType.STOP_MARKET.value
                        exit_tpm_type = exit_type == AlgoOrderType.TAKE_PROFIT_MARKET.value

                        long_sl_true = self.positions.long_stop_loss and self.positions.long_stop_loss_order_id
                        long_sl_false = not self.positions.long_stop_loss and not self.positions.long_stop_loss_order_id

                        long_tp_true = self.positions.long_take_profit and self.positions.long_take_profit_order_id
                        long_tp_false = not self.positions.long_take_profit and not self.positions.long_take_profit_order_id

                        short_sl_true = self.positions.short_stop_loss and self.positions.short_stop_loss_order_id
                        short_sl_false = not self.positions.short_stop_loss and not self.positions.short_stop_loss_order_id

                        short_tp_true = self.positions.short_take_profit and self.positions.short_take_profit_order_id
                        short_tp_false = not self.positions.short_take_profit and not self.positions.short_take_profit_order_id

                        match aoes:
                            
                            # New Exit Order Price & OrderID
                            case AlgoOrderEventStatus.NEW.value if aid:

                                if long_exit_side:
                                    if exit_sm_type: # New Long Stop Loss
                                        self.positions.long_stop_loss = trigger_price
                                        self.positions.long_stop_loss_order_id = aid

                                    elif exit_tpm_type: # New Long Take Profit
                                        self.positions.long_take_profit = trigger_price
                                        self.positions.long_take_profit_order_id = aid

                                elif short_exit_side:
                                    if exit_sm_type: # New Short Stop Loss
                                        self.positions.short_stop_loss = trigger_price
                                        self.positions.short_stop_loss_order_id = aid

                                    elif exit_tpm_type: # New Short Take Profit
                                        self.positions.short_take_profit = trigger_price
                                        self.positions.short_take_profit_order_id = aid

                            # Exit Order is Filled
                            case AlgoOrderEventStatus.FINISHED.value if aid:

                                finished_side:PositionSide = None
                                finished_id:List = [None, None]

                                if long_exit_side and aid and trigger_price:
                                    finished_side = PositionSide.LONG

                                    if exit_sm_type and trigger_price == self.positions.long_stop_loss and \
                                        aid == self.positions.long_stop_loss_order_id:

                                        finished_id[0] = aid
                                        self.positions.long_stop_loss = None
                                        self.positions.long_stop_loss_order_id = None

                                    if exit_tpm_type and trigger_price == self.positions.long_take_profit and \
                                        aid == self.positions.long_take_profit_order_id:

                                        finished_id[1] = aid
                                        self.positions.long_take_profit = None
                                        self.positions.long_take_profit_order_id = None

                                elif short_exit_side and aid and trigger_price:
                                    finished_side = PositionSide.SHORT

                                    if exit_sm_type and trigger_price == self.positions.short_stop_loss and \
                                        aid == self.positions.short_stop_loss_order_id:

                                        finished_id[0] = aid
                                        self.positions.short_stop_loss = None
                                        self.positions.short_stop_loss_order_id = None

                                    if exit_tpm_type and trigger_price == self.positions.short_take_profit and \
                                        aid == self.positions.short_take_profit_order_id:

                                        finished_id[1] = aid
                                        self.positions.short_take_profit = None
                                        self.positions.short_take_profit_order_id = None

                                if finished_side and finished_id:
                                    self.order_manager.update_exit_algo_order(ps=finished_side, finished_id=finished_id, showLog = False)

                            case AlgoOrderEventStatus.CANCELED.value if aid:

                                canceled_id = None

                                if long_exit_side:
                                    # Long SL Cancel & Init
                                    if exit_sm_type and long_sl_true and self.positions.long_stop_loss_order_id == aid:
                                        canceled_id = aid
                                        self.positions.long_stop_loss = None
                                        self.positions.long_stop_loss_order_id = None

                                    # Long TP Cancel & Init
                                    if exit_tpm_type and long_tp_true and self.positions.long_take_profit_order_id == aid:
                                        canceled_id = aid
                                        self.positions.long_take_profit = None
                                        self.positions.long_take_profit_order_id = None

                                elif short_exit_side:
                                    # Short SL Cancel & Init
                                    if exit_sm_type and short_sl_true and self.positions.short_stop_loss_order_id == aid:
                                        canceled_id = aid
                                        self.positions.short_stop_loss = None
                                        self.positions.short_stop_loss_order_id = None

                                    # Short TP Cancel & Init
                                    if exit_tpm_type and short_tp_true and self.positions.short_take_profit_order_id == aid:
                                        canceled_id = aid
                                        self.positions.short_take_profit = None
                                        self.positions.short_take_profit_order_id = None

                                # if canceled_id:
                                #     logger.info(f"Successfully canceled order. Order Id: {canceled_id}")

                case UserDataEventType.ACCOUNT_UPDATE.value:

                    a = user_data.get('a')
                    balances = (a.get('B', None))
                    positions = (a.get('P', None))
                    reason_type = (a.get('m', None))

                    ### BALANCES ###
                    if balances:
                        for balance in balances:
                            asset = str(balance.get('a')) # Asset
                            cw = Decimal(balance.get('cw')) # Cross Wallet Balance
                            bc = Decimal(balance.get('bc')) # Balance Change except PnL and Commission
                            bc = abs(bc)

                            if not positions: # []
                                match reason_type:
                                    case UserDataEventReasonType.DEPOSIT.value: # Spot -> Futures
                                        logger.info(f'[WALLET] Deposit Detected | Amount: +{bc} {asset} | New Balance: {cw} ({asset})')

                                    case UserDataEventReasonType.WITHDRAW.value: # Futures -> Spot
                                        logger.info(f'[WALLET] Withdraw Detected | Amount: -{bc} {asset} | New Balance: {cw} ({asset})')

                            match asset:
                                case AssetType.USDT.value:
                                    self.balances.balance = cw

                                case AssetType.BNB.value:
                                    self.balances.bnb_balance = cw

                    ### POSITIONS ###
                    long_balance = Decimal('0')
                    short_balance = Decimal('0')

                    for position in positions:
                        if position['s'] == self.symbol:
                            position_amount = Decimal(position['pa']) # '3.7' if all amount filled, value is '0'
                            position_amount = abs(position_amount)
                            entry_price = Decimal(position['ep'])
                            position_side = str(position['ps']) # 'LONG' or 'SHORT'

                            match position_side:
                                case PositionSide.BOTH.value:
                                    logger.warning("One-way mode (BOTH) detected. This engine is optimized for Hedge Mode.")

                                case PositionSide.LONG.value:
                                    if position_amount:  # 0이 아닐 때 (True)
                                        self.positions.long_amount = position_amount
                                        self.positions.long_entry_price = entry_price
                                        long_balance = Decimal(entry_price * position_amount)
                                    else:  # 0일 때 (False)
                                        self.positions.long_amount = None
                                        self.positions.long_entry_price = None
                                        self.positions.long_default_stop_loss = None

                                case PositionSide.SHORT.value:
                                    if position_amount:
                                        self.positions.short_amount = position_amount
                                        self.positions.short_entry_price = entry_price
                                        short_balance = Decimal(entry_price * position_amount)
                                    else:
                                        self.positions.short_amount = None
                                        self.positions.short_entry_price = None
                                        self.positions.short_default_stop_loss = None

                    using_margin = (long_balance + short_balance) / Decimal(str(self.leverage))
                    self.balances.available_balance = self.balances.balance - (using_margin) # Update Available Balance

                case UserDataEventType.ORDER_TRADE_UPDATE.value:

                    o = user_data.get('o', {})
                    order_status = str(o.get('X')) # 'FILLED' or 'NEW'
                    fee_type = str(o.get('N'))
                    fee = Decimal(str(o.get('n'))) # USDT: 1.23, BNB: 0.000
                    q = Decimal(o.get('q')) # quantity
                    z = Decimal(o.get('z')) # Order Filled Accumulated Quantity
                    order_side = o.get('S') # 'BUY' or 'SELL'
                    exit_price = Decimal(o.get('ap')) # 평균 체결가 사용
                    realized_profit = Decimal(o.get('rp')) # # 포지션 종료시에만 사용

                    if order_status in [OrderStatus.PARTIALLY_FILLED.value, OrderStatus.FILLED.value]:

                        if fee_type == AssetType.BNB.value:
                            bnb_fee = fee

                            remaining_days = Decimal(self.market_data.update_bnb_fee_realtime(timestamp, bnb_fee))

                            if remaining_days < 2 and order_status == OrderStatus.FILLED.value:
                                self.transfer_fee(remaining_days)

                        if order_status == OrderStatus.FILLED.value and q and q == z:

                            match o.get('ps'):

                                case PositionSide.LONG.value:
                                    default_stop_loss = self.positions.long_default_stop_loss
                                    # Open Long
                                    if order_side == Side.BUY.value and default_stop_loss:
                                        _, sl_price, tp_price = self.calculate_logic(PositionSide.LONG, default_stop_loss, exit_price)
                                        if sl_price and tp_price and ((sl_price != self.positions.long_stop_loss) or (tp_price != self.positions.long_take_profit)):
                                            self.order_manager.update_exit_order(ps=PositionSide.LONG, amount=q, entry_price=exit_price, sl_price=sl_price, tp_price=tp_price,showLog=False)

                                    # Close Long
                                    if ENABLE_DISCORD_ALERTS and order_side == Side.SELL.value:
                                        entry_price = (realized_profit / q) + exit_price
                                        long_realized_profit = realized_profit - self.long_fee
                                        self.long_fee = Decimal('0')
                                        send_order_sell_msg(self.symbol, PositionSide.LONG, realized_profit)

                                case PositionSide.SHORT.value:
                                    default_stop_loss = self.positions.short_default_stop_loss
                                    # Open Short
                                    if order_side == Side.SELL.value and default_stop_loss:
                                        _, sl_price, tp_price = self.calculate_logic(PositionSide.SHORT, default_stop_loss, exit_price)
                                        if sl_price and tp_price and ((sl_price != self.positions.short_stop_loss) or (tp_price != self.positions.short_take_profit)):
                                            self.order_manager.update_exit_order(ps=PositionSide.SHORT, amount=q, entry_price=exit_price, sl_price=sl_price, tp_price=tp_price,showLog=False)

                                    # Close Short
                                    if ENABLE_DISCORD_ALERTS and order_side == Side.BUY.value:
                                        entry_price = (realized_profit / q) + exit_price
                                        short_realized_profit = realized_profit - self.short_fee
                                        self.short_fee = Decimal('0')
                                        send_order_sell_msg(self.symbol, PositionSide.SHORT, realized_profit)

                case UserDataEventType.ACCOUNT_CONFIG_UPDATE.value:

                    if ENABLE_ORDER:
                        ac = user_data.get('ac',None)
                        symbol = ac.get('s',None)
                        leverage = ac.get('l',None)
                        if leverage is not None and self.leverage != leverage and symbol == self.symbol:
                            logger.warning(f"Leverage mismatch for {symbol}. Resetting {leverage}x to target {self.leverage}x.")
                            self.client.futures_change_leverage(symbol=symbol, leverage=self.leverage)

                case UserDataEventType.TRADE_LITE.value:
                    pass

                case _:
                    logger.info(f"New UserDateEventType: {user_event}")

        except Exception as e:
            logger.error(f"Unexpected error during user data processing: {e}", exc_info=True)

    def execute_trade(self, side:PositionSide, signal: OrderSignal, stop_loss: Decimal, entry:Decimal, take_profit: Decimal, default_stop_loss:Decimal):

        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side parameter is Error. {side}")

        if signal not in [OrderSignal.OPEN_POSITION, OrderSignal.CLOSE_POSITION, OrderSignal.UPDATE_STOP_LOSS, OrderSignal.UPDATE_TAKE_PROFIT]:
            raise ValueError(f"signal parameter is Error. {signal}")

        if side is PositionSide.LONG:

            if (stop_loss < entry < take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit} | {default_stop_loss}')

            # OPEN LONG POSTION
            if self.positions.long_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.get_position_quantity(position=PositionSide.LONG, price=entry, stop_loss_price=stop_loss)
                logger.info(f"[LONG SIGNAL] Amount: {quantity:.2f} | Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")
                if quantity > 0:
                    self.order_manager.create_buy_position(position=PositionSide.LONG, quantity=quantity, sl_price=stop_loss, entry_price=entry, tp_price=take_profit, default_stop_loss=default_stop_loss)
                else:
                    logger.warning(f"[{self.symbol}] 리스크 관리 조건(minQty/minNotional) 미달로 주문을 생성하지 않습니다.")

        elif side is PositionSide.SHORT:

            if (stop_loss > entry > take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit} | {default_stop_loss}')

            # OPEN SHORT POSTION
            if self.positions.short_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.get_position_quantity(position=PositionSide.SHORT, price=entry, stop_loss_price=stop_loss)
                logger.info(f"[SHORT SIGNAL] Amount: {quantity:.2f} | Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")
                if quantity > 0:
                    self.order_manager.create_buy_position(position=PositionSide.SHORT, quantity=quantity, sl_price=stop_loss, entry_price=entry, tp_price=take_profit, default_stop_loss=default_stop_loss)
                else:
                    logger.warning(f"[{self.symbol}] 리스크 관리 조건(minQty/minNotional) 미달로 주문을 생성하지 않습니다.")

    def transfer_fee(self, remaining_days):
        # 1. 최근 7일간의 일평균 소모량 (BNB 단위)
        daily_avg = self.market_data.total_7d_bnb_fee / Decimal('7')

        # 2. 추가로 필요한 7일치 분량
        needed_bnb_7d = daily_avg * Decimal('7')

        # 3. 현재 BNB 가격 조회 (API 사용)
        current_bnb_price = self.client.get_symbol_ticker('BNBUSDT')

        # 4. 필요한 USDT 금액 계산
        need_bnb = Decimal(needed_bnb_7d * current_bnb_price)

        logger.info(f"[!] BNB Balance is low (under 2 days). Starting auto-recharge process...")
        logger.info(f"[+] Calculating 7-day fee coverage based on recent activity.")
        logger.info(f"[+] Target USDT to transfer: {need_bnb:.2f} USDT")

        prev_usdt = Decimal(str(self.client.spot_account_balance('USDT'))) # 사기 전 spot 의 usdt
        need_bnb = need_bnb - prev_usdt
        need_bnb = round(need_bnb, 2)

        if need_bnb > 0: # 부족한 경우 Futures -> Spot 으로 USDT 입금
            trandId = self.client.futures_account_transfer('USDT', need_bnb, 2)
            if not trandId:
                raise ValueError(f"futures_account_transfer return is None -> {trandId}")

        # self.client.spot_create_order_buy(self.symbol, Decimal(need_bnb))

        spot_balances = self.client.spot_account_balance()

        if not spot_balances:
            raise ValueError(f"bought it, but couldn't find anything. -> {spot_balances}")

        for spot in spot_balances:
            asset = spot
            amount = spot_balances.get(spot)

            if asset in ['USDT', 'BNB']:
                logger.info(f"{asset} {amount}")
                # Futures 으로 BNB 입금
                self.client.futures_account_transfer(asset, Decimal(amount), 1)

                if asset == 'BNB':
                    logger.info(f"[+] {asset} Auto-Recharge successful.")
                    logger.info(f"[+] Purchased: {amount} {asset}")
                    logger.info(f"[+] Current estimated survival: {remaining_days+Decimal('7')} Days")

                    if ENABLE_DISCORD_ALERTS:
                        '''
                        Low fee balance detected (under 2 days).
                        System has automatically replenished 7 days of BNB.

                        • Transferred : {usdt_amount} USDT
                        • Purchased   : {bnb_amount} BNB
                        • New Survival: {new_days} Days
                        '''
                        send_bnb_recharge_msg(
                            usdt_amount=need_bnb,
                            bnb_amount=amount,
                            new_days=remaining_days+Decimal('7')
                        )

    def calculate_logic(self, side: PositionSide, sl_raw: Decimal, entry_price: Decimal):
        entry = Decimal(str(entry_price))
        raw_sl = Decimal(str(sl_raw)) # 마지노선 고정 (예: 1.9331) 
        slippage_amount = Decimal(str(entry * self.slippage_percent))


        max_loss_limit_ratio = Decimal(str(MAX_STOP_LOSS_RATIO)) / 100
        rr_ratio = Decimal(str(RISK_REWARD_RAITO))
        fee_rate = Decimal('0.00045') # 0.045%
        total_fee_rate = fee_rate * 2  # 왕복 0.09%

        # --- 1. 포지션별 계산 로직 ---
        if side == PositionSide.LONG:
            # 손절가는 마지노선보다 위(안쪽)로 설정 [cite: 8]
            result_sl = raw_sl + slippage_amount 
            # 실질 손실액 계산 (수수료 포함) [cite: 9]
            net_loss = (entry - result_sl) + (entry + result_sl) * fee_rate
            # 익절가 역산 (실질 수익 1:1 보전) [cite: 6]
            result_tp = (entry * (1 + fee_rate) + (net_loss * rr_ratio)) / (1 - fee_rate)
            result_tp = result_tp - slippage_amount

        elif side == PositionSide.SHORT:
            # 손절가는 마지노선보다 아래(안쪽)로 설정 (예: 1.9327 < 1.9331) 
            result_sl = raw_sl - slippage_amount
            # 실질 손실액 계산 (수수료 포함) 
            net_loss = (result_sl - entry) + (entry + result_sl) * fee_rate
            # 익절가 역산 
            result_tp = (entry * (1 - fee_rate) - (net_loss * rr_ratio)) / (1 + fee_rate)
            result_tp = result_tp + slippage_amount

        # --- 2. 사용자 요청 필터링 로직 추가 ---
        # 방향성 검증: 롱은 TP > Entry > SL, 숏은 SL > Entry > TP 여야 함 [cite: 3, 14]
        is_long_valid = (side == PositionSide.LONG and result_tp > entry > result_sl)
        is_short_valid = (side == PositionSide.SHORT and result_sl > entry > result_tp)

        min_distance = entry * total_fee_rate # 최소 익절 거리 (수수료만큼은 벌어야 함)
        actual_distance = abs(result_tp - entry)
        actual_loss_ratio = net_loss / entry # 진입가 대비 실질 손실 비중

        # 조건 미달 시 진입 금지 (None 반환)
        if not (is_long_valid or is_short_valid) or (actual_distance <= min_distance) or (actual_loss_ratio > max_loss_limit_ratio):
            return None, None, None

        # --- 3. 최종 값 반올림 및 반환 ---
        def_sl = round_step_size(raw_sl, self.tickSize)       # 원본 마지노선 
        final_sl = round_step_size(result_sl, self.tickSize)   # 보정된 손절가 
        final_tp = round_step_size(result_tp, self.tickSize)   # 보정된 익절가 

        return def_sl, final_sl, final_tp

    def sync_initial_exit_levels(self):
        """
        봇 재시작 시 거래소에 걸린 주문에서 sl_raw를 역산하여 
        현재 평단 기준의 정밀 TP/SL로 업데이트합니다.
        """
        # 1. LONG 포지션 확인
        if self.positions.long_amount:
            entry_price = self.positions.long_entry_price
            default_stop_loss = self.positions.long_default_stop_loss

            if entry_price and default_stop_loss:
                # 실제 평단 기준으로 재보정
                _, sl_price, tp_price = self.calculate_logic(PositionSide.LONG, default_stop_loss, entry_price)
                if sl_price and tp_price:
                    self.order_manager.update_exit_order(
                        ps=PositionSide.LONG,
                        amount=self.positions.long_amount,
                        entry_price=entry_price,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        showLog=False
                    )

        # 2. SHORT 포지션 확인
        if self.positions.short_amount:
            entry_price = self.positions.short_entry_price
            default_stop_loss = self.positions.short_default_stop_loss
            if entry_price and default_stop_loss:
                # 실제 평단 기준으로 재보정
                _, sl_price, tp_price = self.calculate_logic(PositionSide.SHORT, default_stop_loss, entry_price)
                if sl_price and tp_price:
                    self.order_manager.update_exit_order(
                        ps=PositionSide.SHORT,
                        amount=abs(self.positions.short_amount),
                        entry_price=entry_price,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        showLog=False
                    )
