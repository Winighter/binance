import os, sys, time, threading
from config.msg import logger
from config.enums import LockState
import config.config as app_config
from config.indicators import Indicators
from config.strategies import Strategies
from clients import BinanceClient, WebSocketManager


class Binance:

    # Chart Min Setting
    DEFAULT_KLINE_INTERVAL = app_config.DEFAULT_KLINE_INTERVAL

    def __init__(self):

        # 키 파일 경로를 명령줄 인자로 받습니다.
        key_file = sys.argv[1] if len(sys.argv) > 1 else 'binance.key'

        access, secret = self.get_key(key_file)

        # CLIENT
        self.api_client = BinanceClient(access, secret) # BinanceClient 인스턴스 생성
        self._order_lock = threading.Lock() # 락 객체 초기화

        ### LOCK STATE ###
        self.LONG_LOCK_S1 = LockState.AWAITING_SELL_SIGNAL
        self.SHORT_LOCK_S1 = LockState.AWAITING_SELL_SIGNAL

        self.LONG_LOCK_S2 = LockState.AWAITING_SELL_SIGNAL
        self.SHORT_LOCK_S2 = LockState.AWAITING_SELL_SIGNAL

        self.LONG_LOCK_ST = LockState.READY_TO_OPEN
        self.SHORT_LOCK_ST = LockState.READY_TO_OPEN

        ### APP CONFIG ###
        self.symbol = app_config.SYMBOL
        self.SYSTEM1 = app_config.ENABLE_SYSTEM1
        self.SYSTEM2 = app_config.ENABLE_SYSTEM2
        self.SUPERTREND = app_config.ENABLE_SUPERTREND
        self.ORDER_FILTER = app_config.ENABLE_ORDER_FILTER
        self.STOP_LOSS = app_config.ENABLE_STOP_LOSS

        ### STOP LOSS VARIABLES ###
        self.SL_long_price_S1 = None
        self.SL_short_price_S1 = None

        self.SL_long_price_S2 = None
        self.SL_short_price_S2 = None

        self.SL_long_price_ST = None
        self.SL_short_price_ST = None

        self.long_open = False
        self.short_open = False

        # ORDER NUMVBER
        self.order_long_Id = 0
        self.order_short_Id = 0

        self.is_connected_flag = False

        # RUN
        logger.info(f"Start Binance...")
        self.get_balance(True)
        self.get_positions()
        self.get_candle_chart()

        # WebSocketManager 인스턴스 생성 (WS 연결 담당)
        self.ws_manager = WebSocketManager(
            api_key = access,
            api_secret = secret,
            kline_interval = app_config.DEFAULT_KLINE_INTERVAL,
            symbol = self.symbol,
            message_handler = self.handle_socket_message)
        self.ws_manager.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\\n[Ctrl+C] detection. Shutting down bot...")
        finally:
            if self.ws_manager:
                self.ws_manager.stop()

    def get_key(self, key_file_name: str):
        script_dir = os.path.dirname(__file__)
        key_file_path = os.path.join(script_dir, key_file_name)
        
        if not os.path.exists(key_file_path):
            raise FileNotFoundError(f"Key file not found: {key_file_path}")
            
        with open(key_file_path) as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise ValueError("Key file must contain at least two lines for access and secret keys.")
            access = lines[0].strip()
            secret = lines[1].strip()
            
        if not access or not secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_SECRET_KEY must be set in the key file.")
        
        return access, secret

    def get_balance(self, default:bool = False, _position_rate:int = app_config.DEFAULT_POSITION_RATE, target_asset: str = "USDT"):

        balance_info = self.api_client.get_account_balance()
        if balance_info:
            for asset_data in balance_info:
                if asset_data.get('asset') == target_asset:
                    balance = float(asset_data.get('balance', 0))
                    if balance > 0:
                        self.deposit = balance * (_position_rate / 100) * app_config.DEFAULT_LEVERAGE
                        # logger.info(f"Using {target_asset} balance for deposit calculation: {self.deposit}")
                        break # 원하는 자산을 찾았으면 루프 종료
            else: # for 루프가 break 없이 완료된 경우 (자산을 찾지 못한 경우)
                logger.warning(f"Target asset {target_asset} not found or balance is zero.")
            if default:
                self.api_client.change_leverage(self.symbol, app_config.DEFAULT_LEVERAGE)
                mode = self.api_client.get_position_mode()
                if mode == False:
                    self.api_client.change_position_mode(dual_side_position="true")
        else:
            logger.error("Failed to get balance information.")

    def get_positions(self):
        self.long_dict = {}
        self.short_dict = {}
        positions = self.api_client.get_position_information(self.symbol)
        for i in positions:
            symbol = i['symbol']
            positionSide = i['positionSide']
            entryPrice = float(i['entryPrice'])
            positionAmt = float(i['positionAmt'])
            if positionSide == "LONG":
                self.long_dict.update({symbol:{'positionAmt':positionAmt,'entryPrice':entryPrice}})
            elif positionSide == "SHORT":
                self.short_dict.update({symbol:{'positionAmt':positionAmt*-1, 'entryPrice':entryPrice}})

    def get_book_order_price(self, bid_ask):

        data = self.api_client.get_orderbook_ticker(self.symbol)
        if data['symbol'] == self.symbol:
            price = float(data[f'{bid_ask}Price'])
            return price

    def orderFO(self, _side:str, _positionSide:str, _amount:float):
       
       if app_config.ENABLE_TEST_MODE == False:
            with self._order_lock:
                if (_positionSide == "LONG" and self.order_long_Id == 0) or \
                    (_positionSide == "SHORT" and self.order_short_Id == 0):
                    try:
                        order = self.api_client.create_market_order(
                            symbol = self.symbol,
                            side = _side,
                            positionSide =_positionSide,
                            quantity = _amount)
                        if order:
                            order_id = order['orderId']
                            if _positionSide == "LONG":
                                self.order_long_Id = order_id
                            else:
                                self.order_short_Id = order_id
                            # logger.info(f"[ORDER PLACED] {_side} {_positionSide} Order - ID: {order_id}, QTY: {_amount} on {self.symbol}")
                    except Exception as e:
                        logger.error(f"[{_side}/{_positionSide}] Order Placement Failed - QTY: {_amount}, Error: {e}", exc_info=True)
                        time.sleep(app_config.ORDER_PLACEMENT_RETRY_DELAY)
                else:
                    logger.info(f"Skipping order for {_positionSide} as another order is pending or lock is active.")

    def process_system_signals(self, long_signals, short_signals, long_lock_attr, short_lock_attr):
        if long_signals and short_signals and len(long_signals) == len(short_signals):

            # 가장 최신 신호(리스트의 마지막 요소)를 확인
            latest_long_open, latest_long_close = long_signals[-1]
            if latest_long_open != latest_long_close and latest_long_close:
                setattr(self, long_lock_attr, LockState.READY_TO_OPEN)
                logger.debug(f"Long signal detected for {long_lock_attr}. Setting to READY_TO_OPEN.")

            # strategies.py에서 short_signals의 튜플 순서가 (close_val, open_val)임을 가정
            latest_short_close, latest_short_open = short_signals[-1]
            if latest_short_open != latest_short_close and latest_short_close:
                setattr(self, short_lock_attr, LockState.READY_TO_OPEN)
                logger.debug(f"Short signal detected for {short_lock_attr}. Setting to READY_TO_OPEN.")
        else:
            logger.warning("System signals lists are empty or have mismatched lengths.")

    def get_candle_chart(self):

        temp_open = []
        temp_high = []
        temp_low = []
        temp_close = []

        candles = self.api_client.get_klines(symbol=self.symbol, interval=self.DEFAULT_KLINE_INTERVAL) # config에 Client 상수 값을 직접 넣었다면 그대로 사용

        for candle in candles:

            temp_open.append(float(candle[1]))
            temp_high.append(float(candle[2]))
            temp_low.append(float(candle[3]))
            temp_close.append(float(candle[4]))

        self.open_list = temp_open[::-1]
        self.high_list = temp_high[::-1]
        self.low_list = temp_low[::-1]
        self.close_list = temp_close[::-1]

        if self.SYSTEM1:
            _long1, _short1, _, _ = self.get_system_signal(self.high_list, self.low_list, '1')
            self.process_system_signals(_long1, _short1, 'LONG_LOCK_S1', 'SHORT_LOCK_S1')

        if self.SYSTEM2:
            _, _, _long2, _short2 = self.get_system_signal(self.high_list, self.low_list, '2')
            self.process_system_signals(_long2, _short2, 'LONG_LOCK_S2', 'SHORT_LOCK_S2')

    def get_supertrend_signal(self, high_list:list[float], low_list:list[float], close_list:list[float]):

        st_config = {
            'ATR_LENGTH': app_config.SUPERTREND_ATR_LENGTH,
            'MULTIPLIER': app_config.SUPERTREND_MULTIPLIER
            }
        signal, value = Indicators.supertrend_pine_style(
            high_list, low_list, close_list,
            _atr_length = st_config['ATR_LENGTH'], _multiplier = st_config['MULTIPLIER'])

        return signal, value

    def get_system_signal(self, high_list, low_list, system:int = '1'):

        if system == '1':
            config = {
                'HIGH_PERIOD_LONG': app_config.SYSTEM1_HIGH_PERIOD_LONG,
                'LOW_PERIOD_LONG': app_config.SYSTEM1_LOW_PERIOD_LONG,
                'HIGH_PERIOD_SHORT': app_config.SYSTEM1_HIGH_PERIOD_SHORT,
                'LOW_PERIOD_SHORT': app_config.SYSTEM1_LOW_PERIOD_SHORT
            }
        elif system == '2':
            config = {
                'HIGH_PERIOD_LONG': app_config.SYSTEM2_HIGH_PERIOD_LONG,
                'LOW_PERIOD_LONG': app_config.SYSTEM2_LOW_PERIOD_LONG,
                'HIGH_PERIOD_SHORT': app_config.SYSTEM2_HIGH_PERIOD_SHORT,
                'LOW_PERIOD_SHORT': app_config.SYSTEM2_LOW_PERIOD_SHORT
            }

        _long_system = Strategies.system(high_list, low_list,
                                        _high_len=config['HIGH_PERIOD_LONG'],
                                        _low_len=config['LOW_PERIOD_LONG'])
        _short_system = Strategies.system(high_list, low_list,
                                         _high_len=config['HIGH_PERIOD_SHORT'],
                                         _low_len=config['LOW_PERIOD_SHORT'])
        _long_system = _long_system[0]
        _short_system = _short_system[0]

        open_long, close_long = _long_system[0], _long_system[1]
        open_short, close_short = _short_system[1], _short_system[0]

        return open_long, close_long, open_short, close_short

    def handle_position_logic(self, is_long: bool, open_signal: bool, close_signal: bool, system_identifier: str, atr: float, close_price: float):
        """
        롱/숏 포지션 오픈 및 클로즈 로직을 처리하는 일반화된 함수.
        is_long: True면 롱, False면 숏
        open_signal: 해당 방향의 오픈 신호
        close_signal: 해당 방향의 클로즈 신호
        system_identifier: 로깅 메시지에 사용할 시스템 식별자 (예: "S1", "S2", "ST")
        atr: ATR 손절값
        lock_attr_name: Current Lock Status (ex: 'LONG_LOCK1', 'SHORT_LOCK1')
        sl_price_var_name: SL 가격을 저장하는 인스턴스 변수 이름 (ex: 'SL_long_price_S1', 'SL_long_price_S2', 'SL_long_price_ST')
        """
        current_dict = self.long_dict if is_long else self.short_dict
        position_side = "LONG" if is_long else "SHORT"
        order_side_open = "BUY" if is_long else "SELL"
        order_side_close = "SELL" if is_long else "BUY"
        lock_attr_name = f"{'LONG_LOCK' if is_long else 'SHORT_LOCK'}_{system_identifier}"
        sl_price_var_name = f"SL_{'long' if is_long else 'short'}_price_{system_identifier}"
        current_lock_state = getattr(self, lock_attr_name)

        ### 중복 진입 방지 ###
        if self.symbol in current_dict and open_signal:
            if current_lock_state != LockState.AWAITING_SELL_SIGNAL:
                setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                logger.info(f"[INFO-{position_side} {system_identifier}] Position already open. Change/maintain status to AWAITING_SELL_SIGNAL.")
            return # There is nothing more to deal with in this function, so exit.

        if open_signal != close_signal:
            if current_lock_state == LockState.IGNORE_NEXT_SIGNAL:
                if open_signal:
                    setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                    # logger.info(f"[SYSTEM {system_identifier}] Change {lock_attr_name}: {getattr(self, lock_attr_name)}")

            if current_lock_state == LockState.AWAITING_SELL_SIGNAL and close_signal:
                setattr(self, lock_attr_name, LockState.READY_TO_OPEN)
                # logger.info(f"[SYSTEM {system_identifier}] Change {lock_attr_name}: {getattr(self, lock_attr_name)}")

            # CLOSE POSITION
            if self.symbol in current_dict:
                if close_signal:
                    qty = float(current_dict[self.symbol]['positionAmt'])
                    entry_price = current_dict[self.symbol]['entryPrice']
                    pnl = round(((close_price - entry_price) / entry_price) * (100 if is_long else -100), 4)
                    logger.info(f"[CLOSE-{position_side} {system_identifier}] PNL: {pnl}")
                    self.orderFO(order_side_close, position_side, qty)
                    setattr(self, sl_price_var_name, None) # Clear SL price after closing
                    if self.ORDER_FILTER and pnl > app_config.PROFIT_PNL_THRESHOLD: # ORDER_FILTER
                        setattr(self, lock_attr_name, LockState.IGNORE_NEXT_SIGNAL)
                        logger.info(f"[CLOSE-{position_side} {system_identifier}] Successful profit realization, Ignore {('LONG' if is_long else 'SHORT')} Next Signal: {getattr(self, lock_attr_name)}")

            # OPEN POSITION
            elif self.symbol not in current_dict and current_lock_state == LockState.READY_TO_OPEN and open_signal:

                # Calculate the Stop Loss Price
                setattr(self, sl_price_var_name, round(close_price - atr if is_long else close_price + atr, 5))
                price = self.get_book_order_price("bid" if is_long else "ask")
                # 여기서 amount 계산 시 거래소 필터링 (stepSize) 고려해야 함 (아래 참조)
                amount = round(self.deposit / price, 1) # 정밀도 문제 발생 가능성 있음

                setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                logger.info(f"[{system_identifier} OPEN-{position_side}] SL:{getattr(self, sl_price_var_name)} {getattr(self, lock_attr_name)}")
                self.orderFO(order_side_open, position_side, amount)

                if is_long: self.long_open = True
                else: self.short_open = True

    def check_stop_loss(self, current_close_price):

        # SYSTEM 1 SL
        if self.SYSTEM1:
            if (self.symbol in self.long_dict) and \
               (self.SL_long_price_S1 is not None) and \
               (current_close_price < self.SL_long_price_S1):
                self.LONG_LOCK_S1 = LockState.AWAITING_SELL_SIGNAL
                price = self.long_dict[self.symbol]['entryPrice']
                qty = self.long_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                logger.info(f"[S1 CLOSE-LONG SL] SL:{self.SL_long_price_S1} PNL: {pnl} {self.LONG_LOCK_S1.name}")
                self.orderFO("SELL", "LONG", qty)
                self.SL_long_price_S1 = None

            if (self.symbol in self.short_dict) and \
               (self.SL_short_price_S1 is not None) and \
               (current_close_price > self.SL_short_price_S1):
                self.SHORT_LOCK_S1 = LockState.AWAITING_SELL_SIGNAL
                entryPrice = self.short_dict[self.symbol]['entryPrice']
                quantity = self.short_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - entryPrice) / entryPrice) * -100, 4)
                logger.info(f"[S1 CLOSE-SHORT SL] SL:{self.SL_short_price_S1} PNL: {pnl} {self.SHORT_LOCK_S1.name}")
                self.orderFO("BUY", "SHORT", quantity)
                self.SL_short_price_S1 = None

        # SYSTEM 2 SL
        if self.SYSTEM2:
            if (self.symbol in self.long_dict) and \
               (self.SL_long_price_S2 is not None) and \
               (current_close_price < self.SL_long_price_S2):
                self.LONG_LOCK_S2 = LockState.AWAITING_SELL_SIGNAL
                price = self.long_dict[self.symbol]['entryPrice']
                qty = self.long_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                logger.info(f"[S2 CLOSE-LONG SL] SL:{self.SL_long_price_S2} PNL: {pnl} {self.LONG_LOCK_S2.name}")
                self.orderFO("SELL", "LONG", qty)
                self.SL_long_price_S2 = None

            if (self.symbol in self.short_dict) and \
               (self.SL_short_price_S2 is not None) and \
               (current_close_price > self.SL_short_price_S2):
                self.SHORT_LOCK_S2 = LockState.AWAITING_SELL_SIGNAL
                entryPrice = self.short_dict[self.symbol]['entryPrice']
                quantity = self.short_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - entryPrice) / entryPrice) * -100, 4)
                logger.info(f"[S2 CLOSE-SHORT SL] SL:{self.SL_short_price_S2} PNL: {pnl} {self.SHORT_LOCK_S2.name}")
                self.orderFO("BUY", "SHORT", quantity)
                self.SL_short_price_S2 = None

        # SUPER TREND
        if self.SUPERTREND:

            st_signal, st_value = self.get_supertrend_signal(self.high_list, self.low_list, self.close_list)

            if self.symbol in self.long_dict:
                price = self.long_dict[self.symbol]['entryPrice']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                if pnl < 0:
                    if (self.SL_long_price_ST is not None) and (st_value is not None):

                        if app_config.ENABLE_SL_ST_BOTH:
                            max_long_sl_price = max(self.SL_long_price_ST,st_value)
                        elif app_config.ENABLE_SL_ST_ONLY:
                            max_long_sl_price = st_value
                        else:
                            max_long_sl_price = self.SL_long_price_ST

                        if current_close_price < max_long_sl_price: # Use the latest ST value as dynamic SL
                            qty = self.long_dict[self.symbol]['positionAmt']
                            self.LONG_LOCK_ST = LockState.AWAITING_SELL_SIGNAL
                            logger.info(f"[ST CLOSE-LONG SL] SL:{max_long_sl_price} PNL: {pnl} {self.LONG_LOCK_ST.name}")
                            self.orderFO("SELL", "LONG", qty)
                            self.SL_long_price_ST = None # Clear SL after closing

            if self.symbol in self.short_dict:
                price = self.short_dict[self.symbol]['entryPrice']
                pnl = round(((current_close_price - price) / price) * -100, 4)
                if pnl < 0:
                    if (self.SL_short_price_ST is not None) and (st_value is not None):

                        if app_config.ENABLE_SL_ST_BOTH:
                            max_short_sl_price = min(self.SL_short_price_ST,st_value)
                        elif app_config.ENABLE_SL_ST_ONLY:
                            max_short_sl_price = st_value
                        else:
                            max_short_sl_price = self.SL_long_price_ST

                        if current_close_price > max_short_sl_price: # Use the latest ST value as dynamic SL
                            qty = self.short_dict[self.symbol]['positionAmt']
                            self.SHORT_LOCK_ST = LockState.AWAITING_SELL_SIGNAL
                            logger.info(f"[ST CLOSE-SHORT SL] SL:{max_short_sl_price} PNL: {pnl} {self.SHORT_LOCK_ST.name}")
                            self.orderFO("BUY", "SHORT", qty)
                            self.SL_short_price_ST = None # Clear SL after closing

    def handle_socket_message(self, msg):

        if 'stream' in msg:

            if msg['stream'] == f'{self.symbol.lower()}@kline_{self.DEFAULT_KLINE_INTERVAL}':

                if not self.is_connected_flag:
                    # logger.info("Connection Status: Connected")
                    self.is_connected_flag = True

                k = msg['data']['k']

                closed = k['x']
                open = float(k['o'])
                high = float(k['h'])
                low = float(k['l'])
                close = float(k['c'])

                atr = Indicators.atr(self.high_list, self.low_list, self.close_list)
                atr = round(atr, 4) * app_config.ATR_MULTIPLIER

                if closed == True:

                    self.open_list.insert(0, open)
                    self.high_list.insert(0, high)
                    self.low_list.insert(0, low)
                    self.close_list.insert(0, close)

                    max_len = max(app_config.SYSTEM2_HIGH_PERIOD_LONG, app_config.SYSTEM1_HIGH_PERIOD_LONG, app_config.SUPERTREND_ATR_LENGTH + 1) + app_config.DATA_HISTORY_BUFFER # config 변수 사용
                    if len(self.open_list) > max_len:
                        del self.open_list[-1]
                        del self.high_list[-1]
                        del self.low_list[-1]
                        del self.close_list[-1]

                    # ATR
                    atr = Indicators.atr(self.high_list, self.low_list, self.close_list)
                    atr = round(atr, 4) * app_config.ATR_MULTIPLIER

                    a = round(close - atr, 5)
                    b = round(close + atr, 5)
                    logger.info(f"{a} {b}")

                    if self.SUPERTREND:
                        # Get latest SuperTrend signal and value
                        # _signal: 1 for buy, -1 for sell, 0 for no signal
                        # _value: The SuperTrend line value, which acts as the stop-loss

                        st_signal, _ = self.get_supertrend_signal(self.high_list, self.low_list, self.close_list)
                        # Determine open and close signals for handle_position_logic
                        open_long = (st_signal == 1)
                        close_long = (st_signal == -1)

                        # Handle Long position for SuperTrend
                        self.handle_position_logic(True, open_long, close_long, "ST", atr, close) # ATR might not be directly used, but for consistency
                        self.handle_position_logic(False, close_long, open_long, "ST", atr, close) # ATR might not be directly used, but for consistency

                    # SYSTEM 1
                    if self.SYSTEM1:

                        open_long, close_long, open_short, close_short = self.get_system_signal(self.high_list, self.low_list, '1')

                        self.handle_position_logic(True, open_long, close_long, "S1", atr, close)
                        self.handle_position_logic(False, open_short, close_short, "S1", atr, close)

                    # SYSTEM 2
                    if self.SYSTEM2:

                        open_long2, close_long2, open_short2, close_short2 = self.get_system_signal(self.high_list, self.low_list, '2')

                        # System 2의 경우 self.long_open / self.short_open 플래그는 System 1과의 중복 진입 방지를 위해 필요함.
                        # handle_position_logic 내부에서 이 플래그를 사용하여 제어함.
                        self.handle_position_logic(True, open_long2, close_long2, "S2", atr, close)
                        self.handle_position_logic(False, open_short2, close_short2, "S2", atr, close)

                    # 각 캔들 처리 후 초기화 (다음 캔들에서 다시 판단)
                    self.long_open = False 
                    self.short_open = False

                # SL Close TERRITORY (이 부분도 check_stop_loss 함수로 분리 가능)
                if self.STOP_LOSS:
                    self.check_stop_loss(close)
        else:
            e = msg['e']

            if e == 'error':
                logger.error(f"WebSocket Error: {msg['m']}")
                self.is_connected_flag = False

            elif e == 'ORDER_TRADE_UPDATE':
                o = msg['o']
                i = o['i']
                if o['X'] == 'FILLED':

                    if i == self.order_long_Id:
                        self.order_long_Id = 0

                    if i == self.order_short_Id:
                        self.order_short_Id = 0

            elif e == 'ACCOUNT_UPDATE':
                self.get_balance()
                self.get_positions()

if __name__ == "__main__":
    Binance()