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

        # RUN
        logger.info(f"Start Binance...")
        self._initialize_variables()
        self.api_client, self.ws_manager = self._initialize_clients()
        self._setup_initial_state()
        self._start_trading_loop()

    def _initialize_clients(self):
        key_file = sys.argv[1] if len(sys.argv) > 1 else 'binance.key'
        access, secret = self.get_key(key_file)
        api_client = BinanceClient(access, secret)
        ws_manager = WebSocketManager(
            api_key = access,
            api_secret = secret,
            kline_interval = app_config.DEFAULT_KLINE_INTERVAL,
            symbol = self.symbol,
            message_handler = self.handle_socket_message
        )
        return api_client, ws_manager

    def _initialize_variables(self):
        self._order_lock = threading.Lock() # 락 객체 초기화
        self.long_locks = {
            'S1': LockState.AWAITING_SELL_SIGNAL,
            'S2': LockState.AWAITING_SELL_SIGNAL,
            'ST': LockState.READY_TO_OPEN
        }
        self.short_locks = {
            'S1': LockState.AWAITING_SELL_SIGNAL,
            'S2': LockState.AWAITING_SELL_SIGNAL,
            'ST': LockState.READY_TO_OPEN
        }
        self.symbol = app_config.SYMBOL
        self.SYSTEM1 = app_config.ENABLE_SYSTEM1
        self.SYSTEM2 = app_config.ENABLE_SYSTEM2
        self.SUPERTREND = app_config.ENABLE_SUPERTREND
        self.ORDER_FILTER = app_config.ENABLE_ORDER_FILTER
        self.STOP_LOSS = app_config.ENABLE_STOP_LOSS
        self.sl_prices = {
            'S1': {'long': None, 'short': None},
            'S2': {'long': None, 'short': None},
            'ST': {'long': None, 'short': None}
        }
        self.long_open = False
        self.short_open = False
        self.order_long_Id = 0
        self.order_short_Id = 0
        self.is_connected_flag = False

    def _setup_initial_state(self):
        self.get_balance(True)
        self.get_positions()
        self.get_candle_chart()

    def _start_trading_loop(self):
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
        if not balance_info:
            logger.error("Failed to get balance information.")
            return

        for asset_data in balance_info:
            if asset_data.get('asset') == target_asset:
                balance = float(asset_data.get('balance', 0))
                if balance > 0:
                    self.deposit = balance * (_position_rate / 100) * app_config.DEFAULT_LEVERAGE
                    break
        else:
            logger.warning(f"Target asset {target_asset} not found or balance is zero.")

        if default:
            self.api_client.change_leverage(app_config.DEFAULT_LEVERAGE)
            mode = self.api_client.get_position_mode()
            if mode == False:
                self.api_client.change_position_mode(dual_side_position="true")

    def get_positions(self):
        self.long_dict = {}
        self.short_dict = {}
        positions = self.api_client.get_position_information()

        for i in positions:
            symbol = i['symbol']
            positionSide = i['positionSide']
            entryPrice = float(i['entryPrice'])
            positionAmt = float(i['positionAmt'])
            if positionSide == "LONG":
                self.long_dict[symbol] = {'positionAmt':positionAmt,'entryPrice':entryPrice}
            elif positionSide == "SHORT":
                self.short_dict[symbol] = {'positionAmt':positionAmt*-1, 'entryPrice':entryPrice}

    def get_book_order_price(self, bid_ask):
        data = self.api_client.get_orderbook_ticker()
        if data and data.get('symbol') == self.symbol:
            return float(data.get(f'{bid_ask}Price'))
        return None

    def orderFO(self, _side:str, _positionSide:str, _amount:float):
       if app_config.ENABLE_TEST_MODE == False:
            with self._order_lock:
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


    def process_system_signals(self, long_signals, short_signals, short_lock_dict, long_lock_dict, system_id):
        if long_signals and short_signals and len(long_signals) == len(short_signals):

            # 가장 최신 신호(리스트의 마지막 요소)를 확인
            latest_long_open, latest_long_close = long_signals[-1]
            if latest_long_open != latest_long_close and latest_long_close:
                long_lock_dict[system_id] = LockState.READY_TO_OPEN
                logger.debug(f"Long signal detected for {system_id}. Setting to READY_TO_OPEN.")

            # strategies.py에서 short_signals의 튜플 순서가 (close_val, open_val)임을 가정
            latest_short_close, latest_short_open = short_signals[-1]
            if latest_short_open != latest_short_close and latest_short_close:
                short_lock_dict[system_id] = LockState.READY_TO_OPEN
                logger.debug(f"Short signal detected for {system_id}. Setting to READY_TO_OPEN.")
        else:
            logger.warning("System signals lists are empty or have mismatched lengths.")

    def get_candle_chart(self):

        temp_open = []
        temp_high = []
        temp_low = []
        temp_close = []

        candles = self.api_client.get_klines(interval=self.DEFAULT_KLINE_INTERVAL) # config에 Client 상수 값을 직접 넣었다면 그대로 사용

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
            _long1, _short1, _, _ = self._get_system_signal(self.high_list, self.low_list, '1')
            self.process_system_signals(_long1, _short1, self.long_locks, self.short_locks, 'S1')

        if self.SYSTEM2:
            _, _, _long2, _short2 = self._get_system_signal(self.high_list, self.low_list, '2')
            self.process_system_signals(_long2, _short2, self.long_locks, self.short_locks, 'S2')

    def _get_supertrend_signal(self, high_list:list[float], low_list:list[float], close_list:list[float]):

        st_config = {
            'ATR_LENGTH': app_config.SUPERTREND_ATR_LENGTH,
            'MULTIPLIER': app_config.SUPERTREND_MULTIPLIER
            }
        signal, value = Indicators.supertrend_pine_style(
            high_list, low_list, close_list,
            _atr_length = st_config['ATR_LENGTH'], _multiplier = st_config['MULTIPLIER'])

        return signal, value

    def _get_system_signal(self, high_list, low_list, system:int = '1'):

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
        current_dict = self.long_dict if is_long else self.short_dict
        position_side = "LONG" if is_long else "SHORT"
        order_side_open = "BUY" if is_long else "SELL"
        order_side_close = "SELL" if is_long else "BUY"
        current_lock = self.long_locks[system_identifier] if is_long else self.short_locks[system_identifier]

        if self.symbol in current_dict and open_signal:
            if current_lock != LockState.AWAITING_SELL_SIGNAL:
                if is_long: self.long_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL
                else: self.short_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL
                logger.info(f"[INFO-{position_side} {system_identifier}] Position already open. Change/maintain status to AWAITING_SELL_SIGNAL.")
            return

        if open_signal != close_signal:
            if current_lock == LockState.IGNORE_NEXT_SIGNAL and open_signal:
                if is_long: self.long_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL
                else: self.short_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL

            if current_lock == LockState.AWAITING_SELL_SIGNAL and close_signal:
                if is_long: self.long_locks[system_identifier] = LockState.READY_TO_OPEN
                else: self.short_locks[system_identifier] = LockState.READY_TO_OPEN

            # CLOSE POSITION
            if self.symbol in current_dict:
                if close_signal:
                    qty = float(current_dict[self.symbol]['positionAmt'])
                    entry_price = current_dict[self.symbol]['entryPrice']
                    pnl = round(((close_price - entry_price) / entry_price) * (100 if is_long else -100), 4)
                    logger.info("Closing position for %s %s. PNL: %.4f", position_side, system_identifier, pnl)
                    self.orderFO(order_side_close, position_side, qty)
                    self.sl_prices[system_identifier]['long' if is_long else 'short'] = None
                    if self.ORDER_FILTER and pnl > app_config.PROFIT_PNL_THRESHOLD: # ORDER_FILTER
                        if is_long: self.long_locks[system_identifier] = LockState.IGNORE_NEXT_SIGNAL
                        else: self.short_locks[system_identifier] = LockState.IGNORE_NEXT_SIGNAL
                        logger.info(f"[CLOSE-{position_side} {system_identifier}] Successful profit realization, Ignore {('LONG' if is_long else 'SHORT')} Next Signal: {self.long_locks[system_identifier] if is_long else self.short_locks[system_identifier]}")

            # OPEN POSITION
            elif self.symbol not in current_dict and current_lock == LockState.READY_TO_OPEN and open_signal:

                # Calculate the Stop Loss Price
                self.sl_prices[system_identifier]['long' if is_long else 'short'] = round(close_price - atr if is_long else close_price + atr, 5)
                price = self.get_book_order_price("bid" if is_long else "ask")
                amount = round(self.deposit / price, 1)

                if is_long: self.long_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL
                else: self.short_locks[system_identifier] = LockState.AWAITING_SELL_SIGNAL

                sl_price = self.sl_prices[system_identifier]['long' if is_long else 'short']
                logger.info("Opening position for %s %s. PNL: %.4f. SL: %5f", position_side, system_identifier, pnl, sl_price)
                self.orderFO(order_side_open, position_side, amount)

                if is_long: self.long_open = True
                else: self.short_open = True

    def check_stop_loss(self, current_close_price):
        if self.SUPERTREND:
            _, st_value = self._get_supertrend_signal(self.high_list, self.low_list, self.close_list)
            if self.symbol in self.long_dict and self.sl_prices['ST']['long'] is not None:
                effective_long_sl = self.sl_prices['ST']['long']
                if app_config.ENABLE_SL_ST_ONLY and st_value is not None:
                    effective_long_sl = st_value
                elif app_config.ENABLE_SL_ST_BOTH and st_value is not None:
                    effective_long_sl = max(self.sl_prices['ST']['long'], st_value)
                self.sl_prices['ST']['long'] = effective_long_sl
            
            if self.symbol in self.short_dict and self.sl_prices['ST']['short'] is not None:
                effective_short_sl = self.sl_prices['ST']['short']
                if app_config.ENABLE_SL_ST_ONLY and st_value is not None:
                    effective_short_sl = st_value
                elif app_config.ENABLE_SL_ST_BOTH and st_value is not None:
                    effective_short_sl = min(self.sl_prices['ST']['short'], st_value)
                self.sl_prices['ST']['short'] = effective_short_sl

        # 모든 시스템의 손절가를 순회하며 확인
        for system_id, prices in self.sl_prices.items():
            sl_long_price = prices['long']
            sl_short_price = prices['short']

            # Check Long Stop-Loss
            if self.symbol in self.long_dict and sl_long_price is not None and current_close_price < sl_long_price:
                qty = self.long_dict[self.symbol]['positionAmt']
                entry_price = self.long_dict[self.symbol]['entryPrice']
                pnl = round(((current_close_price - entry_price) / entry_price) * 100, 4)
                logger.info(f"[CLOSE-LONG SL-{system_id}] SL:{sl_long_price} PNL: {pnl}")
                self.orderFO("SELL", "LONG", qty)
                self.sl_prices[system_id]['long'] = None

            # Check Short Stop-Loss
            if self.symbol in self.short_dict and sl_short_price is not None and current_close_price > sl_short_price:
                qty = self.short_dict[self.symbol]['positionAmt']
                entry_price = self.short_dict[self.symbol]['entryPrice']
                pnl = round(((current_close_price - entry_price) / entry_price) * -100, 4)
                logger.info(f"[CLOSE-SHORT SL-{system_id}] SL:{sl_short_price} PNL: {pnl}")
                self.orderFO("BUY", "SHORT", qty)
                self.sl_prices[system_id]['short'] = None

    def handle_socket_message(self, msg):
        if 'stream' in msg:
            if msg['stream'] == f'{self.symbol.lower()}@kline_{self.DEFAULT_KLINE_INTERVAL}':
                if not self.is_connected_flag:
                    self.is_connected_flag = True

                k = msg['data']['k']
                closed = k['x']
                open = float(k['o'])
                high = float(k['h'])
                low = float(k['l'])
                close = float(k['c'])

                if closed:
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

                    atr = Indicators.atr(self.high_list, self.low_list, self.close_list)
                    atr = round(atr, 4) * app_config.ATR_MULTIPLIER

                    if self.SUPERTREND:
                        st_signal, _ = self._get_supertrend_signal(self.high_list, self.low_list, self.close_list)
                        logger.info(st_signal)
                        self.handle_position_logic(True, st_signal == 1, st_signal == -1, "ST", atr, close)
                        self.handle_position_logic(False, st_signal == -1, st_signal == 1, "ST", atr, close)

                    if self.SYSTEM1:
                        open_long1, close_long1, open_short1, close_short1 = self._get_system_signal(self.high_list, self.low_list, '1')
                        self.handle_position_logic(True, open_long1, close_long1, "S1", atr, close)
                        self.handle_position_logic(False, open_short1, close_short1, "S1", atr, close)

                    if self.SYSTEM2:
                        open_long2, close_long2, open_short2, close_short2 = self._get_system_signal(self.high_list, self.low_list, '2')
                        self.handle_position_logic(True, open_long2, close_long2, "S2", atr, close)
                        self.handle_position_logic(False, open_short2, close_short2, "S2", atr, close)

                    self.long_open = False 
                    self.short_open = False

                if self.STOP_LOSS:
                    self.check_stop_loss(close)
        elif 'e' in msg:
            event_type = msg['e']
            if event_type == 'error':
                logger.error(f"WebSocket Error: {msg['m']}")
                self.is_connected_flag = False
            elif event_type == 'ORDER_TRADE_UPDATE':
                order_info = msg['o']
                if order_info['X'] == 'FILLED':
                    order_id = order_info['i']
                    if order_id == self.order_long_Id: self.order_long_Id = 0
                    if order_id == self.order_short_Id: self.order_short_Id = 0
            elif event_type == 'ACCOUNT_UPDATE':
                self.get_balance()
                self.get_positions()

if __name__ == "__main__":
    Binance()