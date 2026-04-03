import logging
from ..shared.typings import *
from settings import ENABLE_ORDER, ENABLE_SIMULATION, ENABLE_DISCORD_ALERTS
from ..shared.enums import PositionSide, OrderSignal, UserDataEventType, AssetType, UserDataEventReasonType
from ..config import *
from ..strategies.market_mechanics import MarketMechanics
from .simulator import TradeSimulator
from ..shared.msg import *
from ..strategies.trading_params import MIN_RISK_REWARD_RAITO, MAX_STOP_LOSS_RATIO
from src.shared.utils import *


logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, market_data, order_manager, symbol, leverage, kline_intervals, setup_data):

        self.client = binance_client
        self.market_data = market_data
        self.order_manager = order_manager
        self.symbol = symbol
        self.leverage = int(str(leverage))

        self.str_intervals = []

        if len(kline_intervals) != 3:
            raise ValueError(f"정확히 3개의 인터벌이 필요합니다 (현재: {self.streams}). LTF, MTF, HTF 설정을 확인하세요.")

        self.streams = []
        self.mtf_ltf_ratio:int = None
        for i in range(len(kline_intervals)):
            interval = kline_intervals[i]
            if not interval:
                self.streams.append(None)
                self.str_intervals.append(None)
                continue
            interval_code = interval.code if hasattr(interval, 'code') else interval
            interval_min = interval.minutes if hasattr(interval, 'minutes') else interval
            self.str_intervals.append(f'{interval_code}')
            self.streams.append(f'{self.symbol.lower()}@kline_{interval_code}')

            if i == 0:
                self.mtf_ltf_ratio = interval_min
            elif i == 1:
                self.mtf_ltf_ratio = interval_min / self.mtf_ltf_ratio

        self.stepSize = setup_data.get('stepSize')
        self.tickSize = setup_data.get('tickSize')
        self.slippage_percent = Decimal(str(SLIPPAGE_PERCENT / 100))

        # 전략 분석 시 편리함을 위해 인터벌 코드를 따로 저장
        self.ltf_interval = kline_intervals[0].code if hasattr(kline_intervals[0], 'code') else kline_intervals[0]
        self.mtf_interval = kline_intervals[1].code if hasattr(kline_intervals[1], 'code') else kline_intervals[1]
        self.htf_interval = kline_intervals[2].code if hasattr(kline_intervals[2], 'code') else kline_intervals[2]

        self.positions = self.market_data.positions
        self.balances = self.market_data.balances

        if ENABLE_ORDER and ENABLE_SIMULATION:
            # 로그는 최대한 자세하게 (표준형)
            logger.critical("Configuration conflict detected: ENABLE_ORDER and ENABLE_SIMULATION cannot both be True.")
            
            # 에러 출력은 사용자에게 조치 방법을 안내 (직관형)
            raise ValueError("Invalid setup: Please enable either ENABLE_ORDER or ENABLE_SIMULATION, not both.")

        ### MarketMechanics Instance ###
        if app_config.ENABLE_SIMULATION:
            self.simulator = TradeSimulator(self.order_manager, self.symbol, self.leverage)
        self.smc_analyzer = MarketMechanics()
        self.smc_analyzer.market_data = self.market_data
        self.smc_analyzer.ltf_interval = kline_intervals[0]
        self.smc_analyzer.mtf_interval = kline_intervals[1]

        self.process_trading_signals()

    def trading_signal(self, execute_signals):
    
        signal = None

        # 리스트가 비어있지 않은지 먼저 확인
        if execute_signals and len(execute_signals) > 0:
            signal = execute_signals[-1]
        return signal

    def process_exit_levels(self, execute_signals, showLog:bool = False):

        return_signals = []

        if execute_signals:

            for position_side, signal_index, entry_price, stop_loss_price, take_profit_price in execute_signals:

                e, sl, tp = self.calculate_logic(position_side, entry_price, stop_loss_price, take_profit_price)

                if sl and e and tp:
                    return_signals.append((position_side, signal_index, e, sl, tp))

        return return_signals

    def process_trading_signals(self, showLog:bool = False):

        # 1. MarketData에서 최적화된 Numpy 데이터 생성
        ltf_data = self.market_data.get_analysis_data(self.str_intervals[0])
        mtf_data = self.market_data.get_analysis_data(self.str_intervals[1])
        htf_data = self.market_data.get_analysis_data(self.str_intervals[2])

        # 2. 데이터 유효성 검사 (매우 중요: KeyError 방지)
        if not mtf_data or 'opens' not in mtf_data:
            # 데이터가 아직 안 쌓였을 경우 조용히 리턴
            return

        self.tl = len(ltf_data['lows'])

        logger_data = ltf_data
        timestamps = logger_data['timestamps']
        opens = logger_data['opens']
        highs = logger_data['highs']
        lows = logger_data['lows']
        closes = logger_data['closes']
        f_time = format_timestamp(timestamps[-1])

        ltf_tl = len(ltf_data['lows'])
        mtf_tl = len(mtf_data['lows'])
        htf_tl = len(htf_data['lows'])

        # logger.info(f"HTF: {htf_tl} | MTF: {mtf_tl} | LTF: {ltf_tl}")
        # logger.info(f"HTF: {((htf_data['timestamps'][-1] - htf_data['timestamps'][0]) / 86400000):.2f} Days")
        # logger.info(f"MTF: {((mtf_data['timestamps'][-1] - mtf_data['timestamps'][0]) / 86400000):.2f} Days")
        logger.info(f"LTF: {((ltf_data['timestamps'][-1] - ltf_data['timestamps'][0]) / 86400000):.2f} Days")

        # for i in range(len(lows)):
        #     logger.info(f"hi {format_timestamp(timestamps[i]), opens[i], highs[i], lows[i], closes[i]}")

        # 2. 분석기에 데이터 주입 (BaseStrategy에서 상속받은 함수)
        self.smc_analyzer.update_data(ltf_data, mtf_data, htf_data, self.mtf_ltf_ratio)

        # 3. 데이터가 주입된 후 분석 실행
        execute_signals = self.smc_analyzer.analyze()

        signals_with_exit = self.process_exit_levels(execute_signals, False)

        # 신호 필터 함수
        if app_config.ENABLE_SIMULATION:
            self.simulator.run(signals_with_exit, ltf_data['highs'], ltf_data['lows'], self.stepSize)

        return_signal = self.trading_signal(signals_with_exit)

        return return_signal

    def process_stream_data(self, res):
        try:
            if hasattr(self, 'kline_queue'):
                q_size = self.kline_queue.qsize()
                # 평소엔 조용하다가, 큐가 20개 이상 쌓이면 '경고'를 띄웁니다.
                if q_size > MAX_QUEUE_TOLERANCE:
                    logger.warning(f"⚠️ [Queue Warning] 데이터 처리 지연 발생! 대기량: {q_size}개")
        except:
            pass
        try:
            data = res.get('data')
            if not data: return
            
            # 우리가 앞서 완성한 '밀어내기' 업데이트 실행
            self.market_data.update_candle_data(data)

            if 'stream' in res and 'data' in res:
                stream_name = str(res.get('stream'))
                stream_data = res.get('data')
                kline_data = stream_data.get('k')

                if kline_data.get('x'):

                    # HTF
                    if stream_name == self.streams[2]:
                        self.market_data.update_candle_data(kline_data)

                    # MTF
                    elif stream_name == self.streams[1]:
                        self.market_data.update_candle_data(kline_data)

                    # LTF
                    elif stream_name == self.streams[0]:
                        self.market_data.update_candle_data(kline_data)
                        signal = self.process_trading_signals()

                        order_signal = OrderSignal.NO_SIGNAL

                        if signal:
                            side, index, entry, stop_loss, take_profit = signal
                            if self.tl - index == 1:
                                logger.info(f"[{side}-{self.tl-index}] Balance: {self.balances.available_balance} | Entry: {entry}, Stop Loss: {stop_loss}, Take Profit: {take_profit}")
                                order_signal = OrderSignal.OPEN_POSITION

                        if order_signal != OrderSignal.NO_SIGNAL:
                            self.execute_trade(side, order_signal, entry, stop_loss, take_profit)
                        # else:
                        #     logger.info(f"[{side}-{self.tl-index}] Balance: {self.balances.available_balance} | Entry: {entry}, Stop Loss: {stop_loss}, Take Profit: {take_profit}")

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
                        is_open_long = self.positions.long_amount and self.positions.long_entry_price
                        is_open_short = self.positions.short_amount and self.positions.short_entry_price

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

                                case PositionSide.SHORT.value:
                                    if position_amount:
                                        self.positions.short_amount = position_amount
                                        self.positions.short_entry_price = entry_price
                                        short_balance = Decimal(entry_price * position_amount)
                                    else:
                                        self.positions.short_amount = None
                                        self.positions.short_entry_price = None

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

                                    # Open Long (To be later)

                                    # Close Long
                                    if ENABLE_DISCORD_ALERTS and order_side == Side.SELL.value:
                                        entry_price = (realized_profit / q) + exit_price
                                        long_realized_profit = realized_profit - self.long_fee
                                        self.long_fee = Decimal('0')
                                        send_order_sell_msg(self.symbol, PositionSide.LONG, realized_profit)

                                case PositionSide.SHORT.value:
                                    # Open Short (To be later)

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

    def execute_trade(self, side:PositionSide, signal: OrderSignal, entry:Decimal, stop_loss: Decimal, take_profit: Decimal):

        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side parameter is Error. {side}")

        if signal not in [OrderSignal.OPEN_POSITION, OrderSignal.CLOSE_POSITION, OrderSignal.UPDATE_STOP_LOSS, OrderSignal.UPDATE_TAKE_PROFIT]:
            raise ValueError(f"signal parameter is Error. {signal}")

        if side is PositionSide.LONG:

            if (stop_loss < entry < take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit}')

            # OPEN LONG POSTION
            if self.positions.long_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.order_manager.get_position_quantity(position=PositionSide.LONG, entry=entry, stop_loss=stop_loss)
                test_profit = (stop_loss - entry) / entry * 100
                logger.info(f"[LONG SIGNAL] Balance: {self.balances.available_balance:.2f} | Amount: {quantity:.2f} PNL: {test_profit:.2f}% | Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")
                if quantity > 0:
                    if ENABLE_ORDER:
                        self.order_manager.create_buy_position(position=PositionSide.LONG, quantity=quantity, sl_price=stop_loss, entry_price=entry, tp_price=take_profit)
                else:
                    logger.warning(f"[{self.symbol}] 리스크 관리 조건(minQty/minNotional) 미달로 주문을 생성하지 않습니다.")

        elif side is PositionSide.SHORT:

            if (stop_loss > entry > take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit}')

            # OPEN SHORT POSTION
            if self.positions.short_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.order_manager.get_position_quantity(position=PositionSide.SHORT, price=entry, stop_loss=stop_loss)
                test_profit = (stop_loss - entry) / entry * 100
                logger.info(f"[SHORT SIGNAL] Balance: {self.balances.available_balance:.2f} | Amount: {quantity:.2f} PNL: {test_profit:.2f}% | Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")
                if quantity > 0:
                    if ENABLE_ORDER:
                        self.order_manager.create_buy_position(position=PositionSide.SHORT, quantity=quantity, sl_price=stop_loss, entry_price=entry, tp_price=take_profit)
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

    def calculate_logic(self, side: PositionSide, entry_price: Decimal, stop_loss_price: Decimal = None, take_profit_price: Decimal = None):

        # Data Type Init
        entry_price = Decimal(str(entry_price))
        minimum_rr_ratio = int(MIN_RISK_REWARD_RAITO)

        # 퍼센트를 소수로 변환 (2% -> 0.02)
        stop_loss_pct = int(1) # (%)
        decimal_pct = Decimal(str(stop_loss_pct / 100))

        if not stop_loss_price: # 손절가 못 받았을 경우 퍼센트로 손절가 결정
            stop_loss_price = entry_price * (1 - decimal_pct) if side == PositionSide.LONG else entry_price * (1 + decimal_pct)

        stop_loss_price = Decimal(str(stop_loss_price))

        if not take_profit_price: # 익절가 못 받았을 경우 손익비로 익절가 결정
            take_profit_price = entry_price + (entry_price - stop_loss_price) * minimum_rr_ratio if side == PositionSide.LONG else entry_price - (stop_loss_price - entry_price) * minimum_rr_ratio

        stop_loss_price = Decimal(str(round_tick_size(side.value, stop_loss_price, self.tickSize)))
        take_profit_price = Decimal(str(round_tick_size(side.value, take_profit_price, self.tickSize)))

        # Entry & Exit 후 발생하는 최대 수수료
        fee_rate = Decimal(str(BINANCE_FEE_PERCENT / 100))
        maximum_total_fee = fee_rate * (entry_price + max(stop_loss_price, take_profit_price))

        # 최소한의 익절가
        minimum_take_profit = round_tick_size(side.value, entry_price - maximum_total_fee, self.tickSize)

        # # 퍼센트 기준 포지션의 최대 손절 가격
        max_loss_limit_ratio = Decimal(str(MAX_STOP_LOSS_RATIO)) / 100
        maximum_stop_price = entry_price * (1 - (max_loss_limit_ratio) if side == PositionSide.LONG else 1 + (max_loss_limit_ratio)) 
        maximum_stop_price = round_step_size(maximum_stop_price, self.tickSize)

        total_tp_fee = (entry_price + take_profit_price) * fee_rate
        total_sl_fee = (entry_price + stop_loss_price) * fee_rate

        tp_tick = abs(take_profit_price - entry_price)
        sl_tick = abs(stop_loss_price - entry_price)

        net_tp_tick = tp_tick - total_tp_fee
        net_sl_tick = sl_tick - total_sl_fee
        net_rr_ratio = net_tp_tick / net_sl_tick # 순수익 손익비 (수수료 제외)

        ### Entry & Exit price Conditions (Filter) ###
        '''
        1. Position Side
        2. (SL, Entry, TP) Comparison of transaction prices.
        3. Commission Drag (Min TP)
        4. 너무 넓은 손절가
        5. 최소 손익비 조건 (수수료 제외 순수익 기준)
        '''

        is_fee_valid = net_rr_ratio >= minimum_rr_ratio
        is_long_valid = side == PositionSide.LONG and take_profit_price > entry_price > stop_loss_price and minimum_take_profit < take_profit_price and stop_loss_price >= maximum_stop_price
        is_short_valid = side == PositionSide.SHORT and stop_loss_price > entry_price > take_profit_price and minimum_take_profit > take_profit_price and stop_loss_price <= maximum_stop_price

        if not (is_fee_valid and (is_long_valid or is_short_valid)):
            return (None, None, None)

        return (entry_price, stop_loss_price, take_profit_price)

    def calculate_target_price(self, entry, stop, rr, leverage, side, fee_rate=BINANCE_FEE_PERCENT):
        # 1. 총 수수료율 (진입 + 종료)
        fee_rate = fee_rate / 100
        total_fee_ratio = Decimal(str(fee_rate * 2 * leverage))

        if side == 'LONG':
            # 2. 순손실폭 계산 (가격 하락폭 * 레버리지 + 수수료)
            net_loss_ratio = ((entry - stop) / entry * leverage) + total_fee_ratio
            
            # 3. 목표 순수익률 계산 (순손실폭 * 손익비)
            target_net_profit_ratio = net_loss_ratio * rr
            
            # 4. 수수료를 감안한 목표 가격 변동률 (순수익률 + 수수료) / 레버리지
            required_move = (target_net_profit_ratio + total_fee_ratio) / leverage
            return entry * (1 + required_move)
        
        else: # Short
            net_loss_ratio = ((stop - entry) / entry * leverage) + total_fee_ratio
            target_net_profit_ratio = net_loss_ratio * rr
            required_move = (target_net_profit_ratio + total_fee_ratio) / leverage
            return entry * (1 - required_move)