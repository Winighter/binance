from config.msg import logger
from config.indicators import Indicators
from config.strategies import Strategies
import config.config as app_config
from config.enums import LockState
from clients import BinanceClient, WebSocketManager
import time, os, threading


class Binance:

    DEFAULT_KLINE_INTERVAL = app_config.DEFAULT_KLINE_INTERVAL

    def __init__(self):

        # KEY
        script_dir = os.path.dirname(__file__)
        key_file_path = os.path.join(script_dir, "binance.key")

        with open(key_file_path) as f:
            lines = f.readlines()
            access = lines[0].strip()
            secret = lines[1].strip()

        # CLIENT
        self.api_client = BinanceClient(access, secret) # BinanceClient 인스턴스 생성
        self._order_lock = threading.Lock() # 락 객체 초기화

        # LOCK 변수 초기값을 config에서 가져오도록 변경
        self.LONG_LOCK1 = LockState.AWAITING_SELL_SIGNAL
        self.SHORT_LOCK1 = LockState.AWAITING_SELL_SIGNAL
        self.LONG_LOCK2 = LockState.AWAITING_SELL_SIGNAL
        self.SHORT_LOCK2 = LockState.AWAITING_SELL_SIGNAL
        # 🚩 SUPERTREND 관련 변경 사항: SuperTrend Lock 상태 변수 추가
        self.LONG_LOCK_ST = LockState.READY_TO_OPEN
        # self.SHORT_LOCK_ST = LockState.AWAITING_SELL_SIGNAL

        self.symbol = app_config.SYMBOL
        self.SYSTEM1 = app_config.ENABLE_SYSTEM1
        self.SYSTEM2 = app_config.ENABLE_SYSTEM2
        self.SUPERTREND = app_config.ENABLE_SUPERTREND
        self.ORDER_FILTER = app_config.ENABLE_ORDER_FILTER

        self.SL_long_price = None
        self.SL_short_price = None
        self.SL_long_price2 = None
        self.SL_short_price2 = None
        # 🚩 SUPERTREND 관련 변경 사항: SuperTrend SL 가격 변수 추가
        self.SL_long_price_ST = None
        # self.SL_short_price_ST = None

        self.long_open = False
        self.short_open = False

        # ORDER NUMVBER
        self.order_long_Id = 0
        self.order_short_Id = 0

        self.last_received_time = None
        self.is_connected_flag = False

        self.ws_manager = None

        # RUN
        logger.info("Start Binance...")
        self.get_balance(True)
        self.get_positions()
        self.get_candle_chart()

        # WebSocketManager 인스턴스 생성 (WS 연결 담당)
        self.ws_manager = WebSocketManager(
            api_key=access,
            api_secret=secret,
            kline_interval=app_config.DEFAULT_KLINE_INTERVAL,
            symbol=self.symbol,
            message_handler=self.handle_socket_message # 콜백 함수 전달
        )
        self.ws_manager.start()

        try:
            while True:
                time.sleep(1) # 봇의 메인 루프는 여기서 계속 실행
        except KeyboardInterrupt:
            logger.info("\\n[Ctrl+C] detection. Shutting down bot...")
        finally:
            if self.ws_manager:
                self.ws_manager.stop()

    def get_balance(self, default:bool = False, _position_rate:int = app_config.DEFAULT_POSITION_RATE):

        balance_info = self.api_client.get_account_balance()

        if balance_info:
            for i in balance_info:
                balance = float(i['balance'])
                if balance > 0:
                    self.deposit = balance*(_position_rate/100)*app_config.DEFAULT_LEVERAGE

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

            if positionSide == "SHORT":
                self.short_dict.update({symbol:{'positionAmt':positionAmt*-1,'entryPrice':entryPrice}})

    def get_book_order_price(self, _bid_ask):

        data = self.api_client.get_orderbook_ticker(self.symbol)

        if data['symbol'] == self.symbol:

            price = float(data[f'{_bid_ask}Price'])

            return price

    def orderFO(self, _side:str, _positionSide:str, _amount:float):

       with self._order_lock:
            if (_positionSide == "LONG" and self.order_long_Id == 0) or \
                (_positionSide == "SHORT" and self.order_short_Id == 0):
                try:
                    order = self.api_client.create_market_order(
                        symbol = self.symbol,
                        side = _side,
                        positionSide=_positionSide,
                        quantity = _amount
                    )
                    if order:
                        order_id = order['orderId']
                        if _positionSide == "LONG":
                            self.order_long_Id = order_id
                        else:
                            self.order_short_Id = order_id
                        # 주문 성공 시 Discord 알림을 위한 이 줄을 추가합니다.
                        logger.info(f"[ORDER PLACED] {_side} {_positionSide} Order - ID: {order_id}, QTY: {_amount} on {self.symbol}")

                except Exception as e:
                    # 이 줄은 이미 Discord에 오류 알림을 보냅니다.
                    logger.error(f"[{_side}/{_positionSide}] Order Placement Failed - QTY: {_amount}, Error: {e}", exc_info=True)
                    time.sleep(app_config.ORDER_PLACEMENT_RETRY_DELAY)
            else:
                logger.info(f"Skipping order for {_positionSide} as another order is pending or lock is active.")

    def _process_system_signals(self, long_signals, short_signals, long_lock_attr, short_lock_attr):
            """
            주어진 롱/숏 신호를 기반으로 락 상태를 업데이트합니다.
            """
            if len(long_signals) == len(short_signals):
                # 롱 신호 처리
                for open_val, close_val in long_signals:
                    if open_val != close_val:
                        if close_val:
                            setattr(self, long_lock_attr, LockState.READY_TO_OPEN)
                        break # 첫 번째 유효 신호에서만 업데이트

                # 숏 신호 처리
                for close_val, open_val in short_signals: # Strategies.system의 반환 구조에 따라 순서 조정
                    if open_val != close_val:
                        if close_val:
                            setattr(self, short_lock_attr, LockState.READY_TO_OPEN)
                        break # 첫 번째 유효 신호에서만 업데이트

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

        # 데이터를 가져온 후 한 번만 뒤집습니다.
        self.open_list = temp_open[::-1]
        self.high_list = temp_high[::-1]
        self.low_list = temp_low[::-1]
        self.close_list = temp_close[::-1]

        # SYSTEM1이 활성화된 경우, _get_system_signals 함수를 사용하여 신호를 확인합니다.
        if self.SYSTEM1:
            sys1_config = {
                'HIGH_PERIOD_LONG': app_config.SYSTEM1_HIGH_PERIOD_LONG,
                'LOW_PERIOD_LONG': app_config.SYSTEM1_LOW_PERIOD_LONG,
                'HIGH_PERIOD_SHORT': app_config.SYSTEM1_HIGH_PERIOD_SHORT,
                'LOW_PERIOD_SHORT': app_config.SYSTEM1_LOW_PERIOD_SHORT
            }
            # _get_system_signals 함수는 _long, _short 를 반환합니다.
            _long, _short = self._get_system_signals(self.high_list, self.low_list, sys1_config)
            self._process_system_signals(_long, _short, 'LONG_LOCK1', 'SHORT_LOCK1')

        # SYSTEM2가 활성화된 경우, 유사하게 신호를 확인합니다.
        if self.SYSTEM2:
            sys2_config = {
                'HIGH_PERIOD_LONG': app_config.SYSTEM2_HIGH_PERIOD_LONG,
                'LOW_PERIOD_LONG': app_config.SYSTEM2_LOW_PERIOD_LONG,
                'HIGH_PERIOD_SHORT': app_config.SYSTEM2_HIGH_PERIOD_SHORT,
                'LOW_PERIOD_SHORT': app_config.SYSTEM2_LOW_PERIOD_SHORT
            }
            _long2, _short2 = self._get_system_signals(self.high_list, self.low_list, sys2_config)
            self._process_system_signals(_long2, _short2, 'LONG_LOCK2', 'SHORT_LOCK2')

    def _get_system_signals(self, high_list, low_list, system_config):

        _long_system = Strategies.system(high_list, low_list,
                                        _high_len=system_config['HIGH_PERIOD_LONG'],
                                        _low_len=system_config['LOW_PERIOD_LONG'])
        _short_system = Strategies.system(high_list, low_list,
                                         _high_len=system_config['HIGH_PERIOD_SHORT'],
                                         _low_len=system_config['LOW_PERIOD_SHORT'])

        return _long_system, _short_system

    def _handle_position_logic(self, is_long: bool, open_signal: bool, close_signal: bool,
                               current_lock: LockState, sl_price_var_name: str,
                               order_id_var_name: str, system_identifier: str, atr: float, close_price: float):
        """
        롱/숏 포지션 오픈 및 클로즈 로직을 처리하는 일반화된 함수.
        is_long: True면 롱, False면 숏
        open_signal: 해당 방향의 오픈 신호
        close_signal: 해당 방향의 클로즈 신호
        current_lock: 현재 락 상태 (예: self.LONG_LOCK1, self.SHORT_LOCK1, self.LONG_LOCK_ST)
        sl_price_var_name: SL 가격을 저장하는 인스턴스 변수 이름 (예: 'SL_long_price', 'SL_long_price_ST')
        order_id_var_name: 주문 ID를 저장하는 인스턴스 변수 이름 (예: 'order_long_Id')
        system_identifier: 로깅 메시지에 사용할 시스템 식별자 (예: "1", "2", "ST")
        atr: ATR 값 (SuperTrend에서는 사용되지 않을 수 있지만, 다른 시스템과 호환을 위해 유지)
        close_price: 현재 캔들 종가
        """
        current_dict = self.long_dict if is_long else self.short_dict
        position_side = "LONG" if is_long else "SHORT"
        order_side_open = "BUY" if is_long else "SELL"
        order_side_close = "SELL" if is_long else "BUY"

        sl_price = getattr(self, sl_price_var_name)
        order_id = getattr(self, order_id_var_name)

        # 🚩 SUPERTREND 관련 변경 사항: lock_attr_name 동적 생성 (ST 시스템 포함)
        lock_attr_name = f"{'LONG_LOCK' if is_long else 'SHORT_LOCK'}{'_' if system_identifier != '1' and system_identifier != '2' else ''}{system_identifier}"
        current_lock_state = getattr(self, lock_attr_name)

        # 💡 추가할 부분 시작
        # 이미 해당 방향으로 포지션이 열려있고, 현재 들어온 신호가 'open_signal'이라면, 불필요한 로직 실행을 막습니다.
        # 특히 System 2의 경우, System 1에 의해 이미 포지션이 열려있을 때 중복 로그를 방지합니다.
        if (self.symbol in current_dict) and open_signal:
            # 이 경우, 이미 포지션이 열려 있으므로 더 이상 '오픈' 관련 처리는 필요 없습니다.
            # LockState를 AWAITING_SELL_SIGNAL로 설정하거나 유지하여 다음 매도 신호를 기다리도록 합니다.
            if current_lock_state != LockState.AWAITING_SELL_SIGNAL:
                setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                # 상태 변경 시에만 로그를 남겨 불필요한 반복 로그를 줄입니다.
                logger.info(f"[INFO-{position_side} {system_identifier}] Position already open. Change/maintain status to AWAITING_SELL_SIGNAL.")
            return # 더 이상 이 함수에서 처리할 것이 없으므로 종료합니다.

        if open_signal != close_signal:
            if current_lock_state == LockState.IGNORE_NEXT_SIGNAL:
                if open_signal:
                    setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                    logger.info(f"[SYSTEM {system_identifier}] Change {lock_attr_name}: {getattr(self, lock_attr_name)}")

            if current_lock_state == LockState.AWAITING_SELL_SIGNAL:
                if close_signal:
                    setattr(self, lock_attr_name, LockState.READY_TO_OPEN)
                    logger.info(f"[SYSTEM {system_identifier}] Change {lock_attr_name}: {getattr(self, lock_attr_name)}")

            # CLOSE POSITION
            if self.symbol in current_dict:

                # 🚩 SUPERTREND 관련 변경 사항: SuperTrend의 SL은 직접 받은 _value를 사용
                if system_identifier == "ST":
                    # SuperTrend의 _value가 곧 SL 역할을 하므로, 이를 직접 사용
                    # 하지만 _handle_position_logic 에서는 sl_price_var_name으로만 접근하므로,
                    # 이 함수 호출 전에 sl_price_var_name을 SuperTrend의 _value로 업데이트해야 함.
                    # 이 함수 내에서는 sl_price가 이미 _value로 설정되어 있다고 가정.
                    pass # SL check is handled by _check_stop_loss or by the signal itself
                else:
                    if sl_price is None: # For systems not using dynamic SL like SuperTrend, ensure SL is set
                        return # Should not happen if SL is properly initialized

                if system_identifier != "ST" and close_signal: # Always close on close signal, regardless of SL price check here
                    qty = float(current_dict[self.symbol]['positionAmt'])
                    entry_price = current_dict[self.symbol]['entryPrice']
                    pnl = round(((close_price - entry_price) / entry_price) * (100 if is_long else -100), 4)
                    logger.info(f"[CLOSE-{position_side} {system_identifier}] PNL: {pnl}")
                    self.orderFO(order_side_close, position_side, qty)
                    setattr(self, sl_price_var_name, None) # Clear SL price after closing
                    if pnl > app_config.PROFIT_PNL_THRESHOLD and self.ORDER_FILTER:
                        setattr(self, lock_attr_name, LockState.IGNORE_NEXT_SIGNAL)
                        logger.info(f"[CLOSE-{position_side} {system_identifier}] Successful profit realization, Ignore {('LONG' if is_long else 'SHORT')} Next Signal: {getattr(self, lock_attr_name)}")

            # OPEN POSITION
            elif (self.symbol not in current_dict) and \
                 (current_lock_state == LockState.READY_TO_OPEN) and \
                 open_signal:

                # SYSTEM 2의 경우 long_open/short_open 플래그로 중복 진입 방지
                # 🚩 SUPERTREND 관련 변경 사항: SuperTrend도 이 플래그를 사용하여 중복 진입 방지
                if ((system_identifier == '2' or system_identifier == 'ST') and ((is_long and self.long_open) or (not is_long and self.short_open))):
                    logger.info(f"[INFO-{position_side} {system_identifier}] Skipping open as another position is pending or open.")
                    return # 이미 다른 시스템에서 해당 방향으로 진입 시도 중이면 무시

                # SuperTrend의 경우 SL price는 _handle_position_logic 호출 시 이미 설정되어야 함
                # 🚩 SUPERTREND 관련 변경 사항: SuperTrend 시스템이 아닐 경우에만 ATR 기반 SL 설정
                if system_identifier != "ST":
                    setattr(self, sl_price_var_name, round(close_price - atr if is_long else close_price + atr, 5))
                # else: for SuperTrend, sl_price_var_name (e.g., SL_long_price_ST) should already contain the _value from supertrend_pine_style

                price = self.get_book_order_price("bid" if is_long else "ask")
                # 여기서 amount 계산 시 거래소 필터링 (stepSize) 고려해야 함 (아래 참조)
                amount = round(self.deposit / price, 1) # 정밀도 문제 발생 가능성 있음

                setattr(self, lock_attr_name, LockState.AWAITING_SELL_SIGNAL)
                logger.info(f"[OPEN-{position_side} {system_identifier}] SL:{getattr(self, sl_price_var_name)} {getattr(self, lock_attr_name)}")
                self.orderFO(order_side_open, position_side, amount)
                if is_long: self.long_open = True
                else: self.short_open = True

    def _check_stop_loss(self, current_close_price):
        """모든 활성 포지션에 대한 손절매를 확인하고 처리합니다."""
        # SYSTEM 1 SL
        if self.SYSTEM1:
            if (self.symbol in self.long_dict) and \
               (self.SL_long_price is not None) and \
               (current_close_price < self.SL_long_price):
                self.LONG_LOCK1 = LockState.AWAITING_SELL_SIGNAL
                price = self.long_dict[self.symbol]['entryPrice']
                qty = self.long_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                logger.info(f"[CLOSE-LONG 1 SL] SL:{self.SL_long_price} PNL: {pnl} {self.LONG_LOCK1.name}")
                self.orderFO("SELL", "LONG", qty)
                self.SL_long_price = None

            if (self.symbol in self.short_dict) and \
               (self.SL_short_price is not None) and \
               (current_close_price > self.SL_short_price):
                self.SHORT_LOCK1 = LockState.AWAITING_SELL_SIGNAL
                entryPrice = self.short_dict[self.symbol]['entryPrice']
                quantity = self.short_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - entryPrice) / entryPrice) * -100, 4)
                logger.info(f"[CLOSE-SHORT 1 SL] SL:{self.SL_short_price} PNL: {pnl} {self.SHORT_LOCK1.name}")
                self.orderFO("BUY", "SHORT", quantity)
                self.SL_short_price = None

        # SYSTEM 2 SL
        if self.SYSTEM2:
            if (self.symbol in self.long_dict) and \
               (self.SL_long_price2 is not None) and \
               (current_close_price < self.SL_long_price2):
                self.LONG_LOCK2 = LockState.AWAITING_SELL_SIGNAL
                price = self.long_dict[self.symbol]['entryPrice']
                qty = self.long_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                logger.info(f"[CLOSE-LONG 2 SL] SL:{self.SL_long_price2} PNL: {pnl} {self.LONG_LOCK2.name}")
                self.orderFO("SELL", "LONG", qty)
                self.SL_long_price2 = None

            if (self.symbol in self.short_dict) and \
               (self.SL_short_price2 is not None) and \
               (current_close_price > self.SL_short_price2):
                self.SHORT_LOCK2 = LockState.AWAITING_SELL_SIGNAL
                entryPrice = self.short_dict[self.symbol]['entryPrice']
                quantity = self.short_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - entryPrice) / entryPrice) * -100, 4)
                logger.info(f"[CLOSE-SHORT 2 SL] SL:{self.SL_short_price2} PNL: {pnl} {self.SHORT_LOCK2.name}")
                self.orderFO("BUY", "SHORT", quantity)
                self.SL_short_price2 = None

        # 🚩 SUPERTREND 관련 변경 사항: SUPERTREND SL 로직 추가
        if self.SUPERTREND:
            # For SuperTrend, the _value returned from supertrend_pine_style acts as the trailing stop.
            # We need to get the latest SuperTrend value to compare.
            # Note: This is a simplified approach. A more robust solution might involve
            # storing the SuperTrend value when a position is opened and updating it
            # only if the trend continues in the favorable direction.
            # However, for now, we'll re-calculate the ST value for comparison.
            
            # Recalculate SuperTrend to get the latest _value for SL comparison
            # We only need the latest value, so _array=0
            st_signal, st_value = Indicators.supertrend_pine_style(
                self.high_list, self.low_list, self.close_list,
                _atr_length=app_config.SUPERTREND_ATR_LENGTH, # Assuming these are in config
                _multiplier=app_config.SUPERTREND_MULTIPLIER, # Assuming these are in config
                _array=0
            )
            
            # Check for Long SuperTrend SL
            if (self.symbol in self.long_dict) and \
               (self.SL_long_price_ST is not None) and \
               (current_close_price < st_value): # Use the latest ST value as dynamic SL

                price = self.long_dict[self.symbol]['entryPrice']
                qty = self.long_dict[self.symbol]['positionAmt']
                pnl = round(((current_close_price - price) / price) * 100, 4)
                if pnl < 0:
                    self.LONG_LOCK_ST = LockState.AWAITING_SELL_SIGNAL
                    logger.info(f"[CLOSE-LONG ST SL] SL:{st_value} PNL: {pnl} {self.LONG_LOCK_ST.name}")
                    self.orderFO("SELL", "LONG", qty)
                    self.SL_long_price_ST = None # Clear SL after closing

            # # Check for Short SuperTrend SL
            # if (self.symbol in self.short_dict) and \
            #    (self.SL_short_price_ST is not None) and \
            #    (current_close_price > st_value): # Use the latest ST value as dynamic SL

            #     entryPrice = self.short_dict[self.symbol]['entryPrice']
            #     quantity = self.short_dict[self.symbol]['positionAmt']
            #     pnl = round(((current_close_price - entryPrice) / entryPrice) * -100, 4)
            #     if pnl < 0:
            #         self.SHORT_LOCK_ST = LockState.AWAITING_SELL_SIGNAL
            #         logger.info(f"[CLOSE-SHORT ST SL] SL:{st_value} PNL: {pnl} {self.SHORT_LOCK_ST.name}")
            #         self.orderFO("BUY", "SHORT", quantity)
            #         self.SL_short_price_ST = None # Clear SL after closing

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

                if closed == True:

                    self.open_list.insert(0, open)
                    self.high_list.insert(0, high)
                    self.low_list.insert(0, low)
                    self.close_list.insert(0, close)

                    # 🚩 SUPERTREND 관련 변경 사항: max_len 계산에 SUPERTREND_ATR_LENGTH 추가
                    max_len = max(app_config.SYSTEM2_HIGH_PERIOD_LONG, app_config.SYSTEM1_HIGH_PERIOD_LONG, app_config.SUPERTREND_ATR_LENGTH + 1) + app_config.DATA_HISTORY_BUFFER # config 변수 사용
                    if len(self.open_list) > max_len:
                        del self.open_list[-1]
                        del self.high_list[-1]
                        del self.low_list[-1]
                        del self.close_list[-1]

                    # ATR (for System 1 and 2)
                    atr = Indicators.atr(self.high_list, self.low_list, self.close_list)
                    atr = round(atr, 4) * app_config.ATR_MULTIPLIER

                    # SYSTEM 1
                    if self.SYSTEM1:

                        sys1_config = {
                            'HIGH_PERIOD_LONG': app_config.SYSTEM1_HIGH_PERIOD_LONG,
                            'LOW_PERIOD_LONG': app_config.SYSTEM1_LOW_PERIOD_LONG,
                            'HIGH_PERIOD_SHORT': app_config.SYSTEM1_HIGH_PERIOD_SHORT,
                            'LOW_PERIOD_SHORT': app_config.SYSTEM1_LOW_PERIOD_SHORT
                        }

                        _long, _short = self._get_system_signals(self.high_list, self.low_list, sys1_config)

                        _long = _long[0]
                        _short = _short[0]

                        open_long, close_long = _long[0], _long[1]
                        open_short, close_short = _short[1], _short[0]

                        self._handle_position_logic(True, open_long, close_long, self.LONG_LOCK1, 'SL_long_price', 'order_long_Id', "1", atr, close)
                        self._handle_position_logic(False, open_short, close_short, self.SHORT_LOCK1, 'SL_short_price', 'order_short_Id', "1", atr, close)

                    # SYSTEM 2
                    if self.SYSTEM2:
                        sys2_config = {
                            'HIGH_PERIOD_LONG': app_config.SYSTEM2_HIGH_PERIOD_LONG,
                            'LOW_PERIOD_LONG': app_config.SYSTEM2_LOW_PERIOD_LONG,
                            'HIGH_PERIOD_SHORT': app_config.SYSTEM2_HIGH_PERIOD_SHORT,
                            'LOW_PERIOD_SHORT': app_config.SYSTEM2_LOW_PERIOD_SHORT
                        }
                        _long2, _short2 = self._get_system_signals(self.high_list, self.low_list, sys2_config)

                        _long2 = _long2[0]
                        _short2 = _short2[0]

                        open_long2, close_long2 = _long2[0], _long2[1]
                        open_short2, close_short2 = _short2[1], _short2[0]

                        # System 2의 경우 self.long_open / self.short_open 플래그는 System 1과의 중복 진입 방지를 위해 필요함.
                        # _handle_position_logic 내부에서 이 플래그를 사용하여 제어함.
                        self._handle_position_logic(True, open_long2, close_long2, self.LONG_LOCK2, 'SL_long_price2', 'order_long_Id', "2", atr, close)
                        self._handle_position_logic(False, open_short2, close_short2, self.SHORT_LOCK2, 'SL_short_price2', 'order_short_Id', "2", atr, close)

                    # 🚩 SUPERTREND 관련 변경 사항: SUPERTREND 처리 블록 추가
                    if self.SUPERTREND:
                        # Get latest SuperTrend signal and value
                        # _signal: 1 for buy, -1 for sell, 0 for no signal
                        # _value: The SuperTrend line value, which acts as the stop-loss
                        st_signal, st_value = Indicators.supertrend_pine_style(
                            self.high_list, self.low_list, self.close_list,
                            _atr_length=app_config.SUPERTREND_ATR_LENGTH,
                            _multiplier=app_config.SUPERTREND_MULTIPLIER,
                            _array=0 # Get the most recent signal and value
                        )
                        if st_signal != 0:
                            logger.info(f'SuperTrend Signal: {st_signal}, Value: {st_value}')

                        # SuperTrend signals are slightly different:
                        # st_signal == 1 means buy (open_long) and implicitly close_short
                        # st_signal == -1 means sell (open_short) and implicitly close_long

                        # Determine open and close signals for _handle_position_logic
                        open_long_st = (st_signal == 1)
                        close_long_st = (st_signal == -1) # If ST goes short, close long
                        open_short_st = (st_signal == -1)
                        close_short_st = (st_signal == 1) # If ST goes long, close short

                        # 🚩 SUPERTREND 관련 변경 사항: SuperTrend SL 가격 설정 (_handle_position_logic 호출 전에)
                        self.SL_long_price_ST = st_value
                        # self.SL_short_price_ST = st_value

                        # Handle Long position for SuperTrend
                        self._handle_position_logic(True, open_long_st, close_long_st,
                                                    self.LONG_LOCK_ST, 'SL_long_price_ST',
                                                    'order_long_Id', "ST", atr, close) # ATR might not be directly used, but for consistency

                        # Handle Short position for SuperTrend
                        # self._handle_position_logic(False, open_short_st, close_short_st,
                        #                             self.SHORT_LOCK_ST, 'SL_short_price_ST',
                        #                             'order_short_Id', "ST", atr, close) # ATR might not be directly used, but for consistency

                    # 각 캔들 처리 후 초기화 (다음 캔들에서 다시 판단)
                    self.long_open = False 
                    self.short_open = False

                # SL Close TERRITORY (이 부분도 _check_stop_loss 함수로 분리 가능)
                self._check_stop_loss(close)
        else:
            e = msg['e']

            if e == 'error':
                logger.error(f"WebSocket Error: {msg['m']}")
                self.is_connected_flag = False
            else:
                if e == 'ORDER_TRADE_UPDATE':

                    o = msg['o']
                    i = o['i']
                    if o['X'] == 'FILLED':

                        if i == self.order_long_Id:
                            self.order_long_Id = 0

                        if i == self.order_short_Id:
                            self.order_short_Id = 0

                if e == 'ACCOUNT_UPDATE':
                    self.get_balance()
                    self.get_positions()

if __name__ == "__main__":
    Binance()