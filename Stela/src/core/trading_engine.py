import logging
from typing import Dict
from decimal import Decimal
from settings import ENABLE_ORDER, ENABLE_SIMULATION
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

        self.opens = self.market_data.open_prices
        self.highs = self.market_data.high_prices
        self.lows = self.market_data.low_prices
        self.closes = self.market_data.close_prices

        self.positions = self.market_data.positions
        self.balances = self.market_data.balances

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

    def derive_exit_prices(
        self, side:PositionSide, stop_loss:Decimal, entry:Decimal, \
        rr_ratio:float = RISK_REWARD_RAITO, maximum_sl_ratio:Decimal = None):

        entry = Decimal(str(entry))

        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side parameter Error check your Input : {side}")

        result_sl = Decimal(str(stop_loss))
        result_tp = Decimal(str(stop_loss))

        rr_ratio = Decimal(str(rr_ratio))
        maximum_sl_ratio = Decimal(str(maximum_sl_ratio / app_config.LEVERAGE))

        if side == PositionSide.LONG:
            if maximum_sl_ratio != None:
                max_sl_price = entry * (Decimal('1') - maximum_sl_ratio / Decimal('100'))
                max_sl_price = round_step_size(max_sl_price, self.tickSize)
                if stop_loss < max_sl_price:
                    result_sl = max_sl_price

            if stop_loss != None:
                tp_price = entry + (entry - result_sl) * Decimal(str(RISK_REWARD_RAITO))
                tp_price = round_step_size(tp_price, self.tickSize)
                result_tp = tp_price

        elif side == PositionSide.SHORT:
            if maximum_sl_ratio != None:
                max_sl_price = entry * (1 + maximum_sl_ratio / 100)
                max_sl_price = round_step_size(max_sl_price, self.tickSize)
                if stop_loss > max_sl_price:
                    result_sl = max_sl_price

            if stop_loss != None:
                tp_price = entry - (result_sl - entry) * Decimal(str(RISK_REWARD_RAITO))
                tp_price = round_step_size(tp_price, self.tickSize)
                result_tp = tp_price

        return result_sl, result_tp

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
                    if self.positions.long_entry_price is None:
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
                    if self.positions.short_entry_price is None:
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
            long_idx, long_stop_Loss, long_entry, long_take_profit = long_signals[-1]
            long = [long_idx, long_stop_Loss, long_entry, long_take_profit]

        if short_signals and len(short_signals) > 0:
            short_idx, short_stop_Loss, short_entry, short_take_profit = short_signals[-1]
            short = [short_idx, short_stop_Loss, short_entry, short_take_profit]

        return long, short

    def process_exit_levels(self, long_raw: Dict = None, short_raw: Dict = None):
        """
        기존의 calculate_exit_level과 derive_exit_prices를 통합한 함수.
        언패킹 에러를 방지하기 위해 인덱싱 방식으로 수정되었습니다.
        """
        maximum_sl_ratio = MAX_STOP_LOSS_RATIO
        rr_ratio = Decimal(str(RISK_REWARD_RAITO))

        def calculate_logic(side: PositionSide, stop_loss_raw: Decimal, entry_raw: Decimal):
            entry = Decimal(str(entry_raw))
            result_sl = Decimal(str(stop_loss_raw))

            # 최대 손절 제한 계산 (레버리지 반영)
            actual_max_sl_ratio = Decimal(str(maximum_sl_ratio)) / Decimal(str(self.leverage))

            if side == PositionSide.LONG:
                max_sl_price = entry * (Decimal('1') - actual_max_sl_ratio / Decimal('100'))
                max_sl_price = round_step_size(max_sl_price, self.tickSize)
                if result_sl < max_sl_price:
                    result_sl = max_sl_price
                tp_price = entry + (entry - result_sl) * rr_ratio
            else:  # SHORT
                max_sl_price = entry * (Decimal('1') + actual_max_sl_ratio / Decimal('100'))
                max_sl_price = round_step_size(max_sl_price, self.tickSize)
                if result_sl > max_sl_price:
                    result_sl = max_sl_price
                tp_price = entry - (result_sl - entry) * rr_ratio

            final_tp = round_step_size(tp_price, self.tickSize)

            return result_sl, final_tp

        long_signals = []
        if long_raw:
            for idx, value in long_raw.items():
                # ⭐️ 수정 포인트: 언패킹 대신 인덱스로 접근 (요소가 2개 이상이어도 안전)
                sl = value[0]
                entry = value[1]
                final_sl, final_tp = calculate_logic(PositionSide.LONG, sl, entry)
                long_signals.append([idx, final_sl, entry, final_tp])

        short_signals = []
        if short_raw:
            for idx, value in short_raw.items():
                # ⭐️ 수정 포인트: 언패킹 대신 인덱스로 접근
                sl = value[0]
                entry = value[1]
                final_sl, final_tp = calculate_logic(PositionSide.SHORT, sl, entry)
                short_signals.append([idx, final_sl, entry, final_tp])

        return long_signals, short_signals

    def process_trading_signals(self):

        # 1. MarketData에서 최적화된 Numpy 데이터 생성
        common_data = self.market_data.get_analysis_data()

        # 2. 분석기에 데이터 주입 (BaseStrategy에서 상속받은 함수)
        self.smc_analyzer.update_data(common_data)
        
        # 3. 데이터가 주입된 후 분석 실행
        long_signals, short_signals = self.smc_analyzer.analyze()

        long_signal_with_exit, short_signal_with_exit = self.process_exit_levels(long_signals, short_signals)

        if app_config.ENABLE_SIMULATION:
            self.simulator.run(long_signal_with_exit, short_signal_with_exit, self.market_data.high_prices, self.market_data.low_prices, self.stepSize, True)

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

                    kline_data = stream_data.get('k')
                    if kline_data and kline_data.get('x'):

                        # First, Update Recent Candle
                        self.market_data.update_candle_data(kline_data)

                        # Second, Analysis Data and Get Signal
                        _long, _short = self.process_trading_signals()

                        long_signal = OrderSignal.NO_SIGNAL
                        short_signal = OrderSignal.NO_SIGNAL

                        if _long:
                            long_index = int(_long[0])
                            long_stop_loss = Decimal(str(_long[1]))
                            long_entry = Decimal(str(_long[2]))
                            long_take_profit = Decimal(str(_long[3]))
                            if int(len(self.lows)) - long_index == 1:
                                long_signal = OrderSignal.OPEN_POSITION

                        if _short:
                            short_index = int(_short[0])
                            short_stop_loss = Decimal(str(_short[1]))
                            short_entry = Decimal(str(_short[2]))
                            short_take_profit = Decimal(str(_short[3]))
                            if int(len(self.lows)) - short_index == 1:
                                short_signal = OrderSignal.OPEN_POSITION

                        # Third, Start Order
                        if ENABLE_ORDER:
                            if long_signal != OrderSignal.NO_SIGNAL:
                                self.execute_trade(PositionSide.LONG, long_signal, long_stop_loss, long_entry, long_take_profit)
                            if short_signal != OrderSignal.NO_SIGNAL:
                                self.execute_trade(PositionSide.SHORT, short_signal, short_stop_loss, short_entry, short_take_profit)
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
            match user_event:

                case UserDataEventType.ALGO_UPDATE.value:

                    algo_data = user_data.get('o')
                    symbol = algo_data.get('s') # XRPUSDT
                    dataX = algo_data.get('X') # 'NEW'

                    if self.symbol == symbol and dataX == 'NEW':
                        caid = algo_data.get('caid') # Algo Order ID
                        quantity = algo_data.get('q') # Quantity
                        exit_type = algo_data.get('o') # 'STOP_MARKET' or 'TAKE_PROFIT_MARKET'
                        data_s = algo_data.get('S') # 'BUY' or 'SELL'
                        data_ps = algo_data.get('ps') # 'LONG' or 'SHORT'
                        exit_price = algo_data.get('tp') # '1.2345'

                        if data_ps == 'LONG' and data_s == 'SELL':
                            if exit_type == 'STOP_MARKET' and self.positions.long_stop_loss == None:
                                self.positions.long_stop_loss = exit_price
                                self.positions.long_stop_loss_order_id = caid

                            elif exit_type == 'TAKE_PROFIT_MARKET' and self.positions.long_take_profit == None:
                                self.positions.long_take_profit = exit_price
                                self.positions.long_take_profit_order_id = caid

                        elif data_ps == 'SHORT' and data_s == 'BUY' and self.positions.short_stop_loss == None:
                            if exit_type == 'STOP_MARKET':
                                self.positions.short_stop_loss = exit_price
                                self.positions.short_stop_loss_order_id = caid

                            elif exit_type == 'TAKE_PROFIT_MARKET' and self.positions.short_take_profit == None:
                                self.positions.short_take_profit = exit_price
                                self.positions.short_take_profit_order_id = caid

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
                                    case UserDataEventReasonType.DEPOSIT.value:
                                        logger.info(f'[WALLET] Deposit Detected | Amount: +{bc} {asset} | New Balance: {cw} ({asset})')

                                    case UserDataEventReasonType.WITHDRAW.value:
                                        logger.info(f'[WALLET] Withdraw Detected | Amount: -{bc} {asset} | New Balance: {cw} ({asset})')

                            if reason_type == UserDataEventReasonType.ORDER.value:
                                logger.info(f'[ORDER] Trade Executed | Updated {asset} Balance: {cw} ({asset})')

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

                    self.balances.available_balance = self.balances.balance - (long_balance + short_balance) # Update Available Balance
                    self.order_manager.initialize_bot_state(showLog=True)

                case UserDataEventType.ORDER_TRADE_UPDATE.value:

                    logger.info(f"[ORDER_TRADE_UPDATE] {user_data}")

                    # o = user_data.get('o', {})

                    # order_status = o.get('X') # 'FILLED' or 'NEW'
                    # position_side = o.get('ps') # 'LONG' or 'SHORT'
                    # order_id = o.get('i')

                    # if order_status == 'FILLED':
                    #     order_side = o.get('S') # 'BUY' or 'SELL'
                    #     exit_price = Decimal(o.get('ap')) # 평균 체결가 사용
                    #     realized_profit = Decimal(o.get('rp')) # 바이낸스가 계산한 실제 수익금

                    #     # Close Long
                    #     if position_side == "LONG" and order_side == 'SELL' and self.positions.long_entry_price:
                    #         entry_price = self.positions.long_entry_price
                    #         pct = ((exit_price - entry_price) / entry_price) * 100 * self.leverage
                    #         send_order_sell_msg(self.symbol, 'LONG', pct, realized_profit)

                    #     # Close Short
                    #     if position_side == "SHORT" and order_side == 'BUY' and self.positions.short_entry_price:
                    #         entry_price = self.positions.short_entry_price
                    #         pct = ((entry_price - exit_price) / entry_price) * 100 * self.leverage
                    #         send_order_sell_msg(self.symbol, 'SHORT', pct, realized_profit)

                case UserDataEventType.ACCOUNT_CONFIG_UPDATE.value:

                    if ENABLE_ORDER:
                        ac = user_data.get('ac',None)
                        symbol = ac.get('s',None)
                        leverage = ac.get('l',None)
                        if leverage is not None and self.leverage != leverage:
                            logger.warning(f"Leverage mismatch for {symbol}. Resetting {leverage}x to target {self.leverage}x.")
                            self.client.futures_change_leverage(symbol=symbol, leverage=self.leverage)

                case UserDataEventType.TRADE_LITE.value:
                    pass

                case _:
                    logger.info(f"New UserDateEventType: {user_event}")

        except Exception as e:
            logger.error(f"Unexpected error during user data processing: {e}", exc_info=True)

    def execute_trade(self, side:PositionSide, signal: OrderSignal, stop_loss: Decimal, entry: Decimal, take_profit: Decimal):

        if side not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"side parameter is Error. {side}")

        if signal not in [OrderSignal.OPEN_POSITION, OrderSignal.CLOSE_POSITION, OrderSignal.UPDATE_STOP_LOSS, OrderSignal.UPDATE_TAKE_PROFIT]:
            raise ValueError(f"signal parameter is Error. {signal}")

        if side is PositionSide.LONG:

            if (stop_loss <= entry <= take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit}')

            # OPEN LONG POSTION
            if self.positions.long_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.get_position_quantity(position=PositionSide.LONG, price=entry, stop_loss_price=stop_loss)
                logger.info(f"SIGNAL: long position entry signal! Order quantity: {quantity:.2f}, Order Stop Loss: {stop_loss}, Entry: {entry}, Take Profit: {take_profit}")
                if quantity > 0:
                    self.order_manager.create_buy_position(position=PositionSide.LONG, quantity=quantity, current_price=entry, sl_price=stop_loss, tp_price=take_profit)
                else:
                    logger.warning(f"[{self.symbol}] 리스크 관리 조건(minQty/minNotional) 미달로 주문을 생성하지 않습니다.")

        if side is PositionSide.SHORT:

            if (stop_loss >= entry >= take_profit) == False:
                raise ValueError(f'Check Price: {stop_loss} {entry} {take_profit}')

            # OPEN SHORT POSTION
            if self.positions.short_entry_price is None and signal == OrderSignal.OPEN_POSITION:
                quantity = self.get_position_quantity(position=PositionSide.SHORT, price=entry, stop_loss_price=stop_loss)
                logger.info(f"SIGNAL: short position entry signal! Order quantity: {quantity:.2f}, Order Stop Loss: {stop_loss}, Entry: {entry}, Take-Profit: {take_profit}")
                if quantity > 0:
                    self.order_manager.create_buy_position(position=PositionSide.SHORT, quantity=quantity, current_price=entry, sl_price=stop_loss, tp_price=take_profit)
                else:
                    logger.warning(f"[{self.symbol}] 리스크 관리 조건(minQty/minNotional) 미달로 주문을 생성하지 않습니다.")