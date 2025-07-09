from config import *
from binance.client import Client
from binance import ThreadedWebsocketManager


class Binance:

    def __init__(self, _access, _secret):

        self.client = Client(_access, _secret)

        self.symbol = "XRPUSDT"
        TIME = self.client.KLINE_INTERVAL_15MINUTE

        self.ORDER_LOCK = False
        self.SYSTEM1 = True
        self.SYSTEM2 = True

        self.LONG_LOCK = 1 # 0: False, 1: True
        self.SHORT_LOCK = 1 # 0: False, 1: True

        self.LONG_LOCK2 = 1 # 0: False, 1: True
        self.SHORT_LOCK2 = 1 # 0: False, 1: True

        self.n2_long_price = 0
        self.n2_short_price = 0

        self.n2_long_price2 = 0
        self.n2_short_price2 = 0

        self.order_long_Id = 0
        self.order_short_Id = 0

        self.last_received_time = None
        self.data_received_count = 0
        self.is_connected_flag = False # 초기 연결 및 재연결 상태를 나타내는 플래그

        # RUN
        print(f"\nStart Binance...\n")
        self.get_balance(True)
        self.get_positions()
        self.get_candle_chart(TIME)
        self.start_websocket(self.symbol, TIME)

    def get_balance(self, _default:bool = False, _leverage:int = 10, _position_rate:int = 45):
        
        if _default:
            self.client.futures_change_leverage(symbol = self.symbol, leverage = _leverage)

            mode = self.client.futures_get_position_mode()
            if mode['dualSidePosition'] == False:
                self.client.futures_change_position_mode(dualSidePosition="true")

        for i in self.client.futures_account_balance():

            balance = float(i['balance'])

            if balance > 0:
                self.deposit = balance*(_position_rate/100)*_leverage

    def get_positions(self):

        self.long_dict = {}
        self.short_dict = {}

        positions = self.client.futures_position_information()

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

        symbols = self.client.futures_orderbook_ticker()
        for symbol in symbols:
            if symbol['symbol'] == self.symbol:
                
                if _bid_ask == "bid":
                    result = symbol['bidPrice']

                elif _bid_ask == "ask":
                    result = symbol['bidPrice']

                result = float(result)
                return result

    def orderFO(self, _symbol:str, _side:str, _positionSide:str, _amount:float):

        if self.ORDER_LOCK == False:

            if (_positionSide == "LONG" and self.order_long_Id == 0) or (_positionSide == "SHORT" and self.order_short_Id == 0):

                order = self.client.futures_create_order(
                    symbol = _symbol,
                    side = _side, # BUY or SELL
                    type = 'MARKET', # LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
                    positionSide = _positionSide,
                    quantity = _amount
                    )

            if order != None:
                if _positionSide == "LONG":
                    self.order_long_Id = order['orderId']
                else:
                    self.order_short_Id = order['orderId']

    def get_candle_chart(self, _time):

        self.open_list = []
        self.high_list = []
        self.low_list = []
        self.close_list = []

        count = 0
        candles = self.client.futures_klines(symbol=self.symbol, interval=_time)

        for candle in candles:

            self.open_list.insert(0, float(candle[1]))
            self.high_list.insert(0, float(candle[2]))
            self.low_list.insert(0, float(candle[3]))
            self.close_list.insert(0, float(candle[4]))
            count += 1

            if count == len(candles) - 1:
                break

    def handle_socket_message(self, msg):

        if 'stream' in msg:

            if msg['stream'] == f'{self.ls}@kline_{self.ki}':

                if not self.is_connected_flag:
                    print("--- 데이터 수신 시작 (재연결 성공 또는 초기 연결)! ---")
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

                    # ATR
                    atr = Indicators.atr(self.high_list, self.low_list, self.close_list)
                    atr = round(atr, 4)*2

                    # SYSTEM 1
                    if self.SYSTEM1:
                        _long_system = Strategies.system(self.high_list, self.low_list, _high_len=28, _low_len=14)
                        _short_system = Strategies.system(self.high_list, self.low_list, _high_len=14, _low_len=28)

                        open_long = _long_system[0]
                        close_long = _long_system[1]

                        open_short = _short_system[1]
                        close_short = _short_system[0]

                        # LONG TERRITORY 1
                        if open_long != close_long:

                            if self.LONG_LOCK == -1:
                                if open_long:
                                    self.LONG_LOCK = 1

                            if self.LONG_LOCK == 1:
                                if close_long:
                                    self.LONG_LOCK = 0

                            # CLOSE LONG 1
                            if self.symbol in self.long_dict:
                                
                                if self.LONG_LOCK and close_long:

                                    qty = float(self.long_dict[self.symbol]['positionAmt'])
                                    price = self.long_dict[self.symbol]['entryPrice']
                                    pnl = round(((close-price)/price)*100, 4)
                                    Message(f"[{self.symbol} TP CLOSE-LONG 1] SL:{self.n2_long_price} PNL: {pnl}")
                                    self.orderFO(self.symbol, "SELL", "LONG", qty)
                                    self.n2_long_price = 0.
                                    if pnl > 0:
                                        self.LONG_LOCK == -1
                                        Message("[LONG] 이익 실현, 다음 매수 신호만 무시")

                                if open_long:
                                    self.LONG_LOCK = 1

                            # OPEN LONG 1
                            if self.symbol not in self.long_dict and self.LONG_LOCK == 0 and open_long:

                                self.n2_long_price = round(close - atr, 5)
                                price = self.get_book_order_price("bid")
                                amount = round(self.deposit/price, 1)
                                self.LONG_LOCK = 1
                                Message(f"[{self.symbol} OPEN-LONG 1] SL:{self.n2_long_price}")
                                self.orderFO(self.symbol, "BUY", "LONG", amount)

                        # SHORT TERRITORY 1
                        if open_short != close_short:

                            if self.SHORT_LOCK == -1:
                                if open_short:
                                    self.SHORT_LOCK = 1

                            if self.SHORT_LOCK == 1:
                                if close_short:
                                    self.SHORT_LOCK = 0

                            # CLOSE SHORT 1
                            if self.symbol in self.short_dict:

                                if self.SHORT_LOCK and close_short:

                                    qty = float(self.short_dict[self.symbol]['positionAmt'])
                                    price = self.short_dict[self.symbol]['entryPrice']
                                    pnl = round(((close-price)/price)*-100, 4)
                                    Message(f"[{self.symbol} TP CLOSE-SHORT 1] SL:{self.n2_short_price} PNL: {pnl}")
                                    self.orderFO(self.symbol, "BUY", "SHORT", qty)
                                    self.n2_short_price = 0.
                                    if pnl > 0:
                                        self.SHORT_LOCK == -1
                                        Message("[SHORT 1] 이익 실현, 다음 매수 신호만 무시")

                                if open_short:
                                    self.SHORT_LOCK = 1

                            # OPEN SHORT 1
                            if self.symbol not in self.short_dict and self.SHORT_LOCK == 0 and open_short:

                                self.n2_short_price = round(close + atr, 5)
                                price = self.get_book_order_price("ask")
                                amount = round(self.deposit/price, 1)
                                self.SHORT_LOCK = 1
                                Message(f"[{self.symbol} OPEN-SHORT 1] SL:{self.n2_short_price}")
                                self.orderFO(self.symbol, "SELL", "SHORT", amount)

                    # SYSTEM 2
                    if self.SYSTEM2:
                        _long_system2 = Strategies.system(self.high_list, self.low_list, _high_len=56, _low_len=28)
                        _short_system2 = Strategies.system(self.high_list, self.low_list, _high_len=28, _low_len=56)

                        open_long2 = _long_system2[0]
                        close_long2 = _long_system2[1]

                        open_short2 = _short_system2[1]
                        close_short2 = _short_system2[0]

                        # LONG TERRITORY 2
                        if open_long2 != close_long2:

                            if self.LONG_LOCK2 == -1:
                                if open_long2:
                                    self.LONG_LOCK2 = 1

                            if self.LONG_LOCK2 == 1:
                                if close_long2:
                                    self.LONG_LOCK2 = 0

                            # CLOSE LONG 2
                            if self.symbol in self.long_dict:

                                if self.LONG_LOCK2 and close_long2:

                                    qty = float(self.long_dict[self.symbol]['positionAmt'])
                                    price = self.long_dict[self.symbol]['entryPrice']
                                    pnl = round(((close-price)/price)*100, 4)
                                    Message(f"[{self.symbol} TP CLOSE-LONG 2] SL:{self.n2_long_price2} PNL: {pnl}")
                                    self.orderFO(self.symbol, "SELL", "LONG", qty)
                                    self.n2_long_price2 = 0.
                                    if pnl > 0:
                                        self.LONG_LOCK2 == -1
                                        Message("[LONG 2] 이익 실현, 다음 매수 신호만 무시")

                                if open_long2:
                                    self.LONG_LOCK2 = 1

                            # OPEN LONG 2
                            elif self.symbol not in self.long_dict and self.LONG_LOCK2 == 0 and open_long2:

                                self.n2_long_price2 = round(close - atr, 5)
                                price = self.get_book_order_price("bid")
                                amount = round(self.deposit/price, 1)
                                self.LONG_LOCK2 = 1
                                Message(f"[{self.symbol} OPEN-LONG 2] SL:{self.n2_long_price2}")
                                self.orderFO(self.symbol, "BUY", "LONG", amount)

                        # SHORT TERRITORY 2
                        if open_short2 != close_short2:

                            if self.SHORT_LOCK2 == -1:
                                if open_short2:
                                    self.SHORT_LOCK2 = 1

                            if self.SHORT_LOCK2 == 1:
                                if close_short2:
                                    self.SHORT_LOCK2 = 0

                            # CLOSE SHORT 2
                            if self.symbol in self.short_dict:
                                
                                if self.SHORT_LOCK2 and close_short2:

                                    qty = float(self.short_dict[self.symbol]['positionAmt'])
                                    price = self.short_dict[self.symbol]['entryPrice']
                                    pnl = round(((close-price)/price)*-100, 4)
                                    Message(f"[{self.symbol} TP CLOSE-SHORT 2] SL:{self.n2_short_price2} PNL: {pnl}")
                                    self.orderFO(self.symbol, "BUY", "SHORT", qty)
                                    self.n2_short_price2 = 0.
                                    if pnl > 0:
                                        self.SHORT_LOCK2 == -1
                                        Message("[SHORT 2] 이익 실현, 다음 매수 신호만 무시")
                                
                                if open_short2:
                                    self.SHORT_LOCK2 = 1
                            
                            # OPEN SHORT 2
                            elif self.symbol not in self.short_dict and self.SHORT_LOCK2 == 0 and open_short2:

                                self.n2_short_price2 = round(close + atr, 5)
                                price = self.get_book_order_price("ask")
                                amount = round(self.deposit/price, 1)
                                self.SHORT_LOCK2 = 1
                                Message(f"[{self.symbol} OPEN-SHORT 2] SL:{self.n2_short_price2}")
                                self.orderFO(self.symbol, "SELL", "SHORT", amount)

                self.close_list.insert(0, close)

                # SL Close TERRITORY
                if self.SYSTEM1:
                    if self.symbol in self.long_dict and 0 < self.n2_long_price and close < self.n2_long_price:

                        self.LONG_LOCK = 1
                        price = self.long_dict[self.symbol]['entryPrice']
                        qty = self.long_dict[self.symbol]['positionAmt']
                        pnl = ((close-price)/price)*100
                        Message(f"[{self.symbol} SL CLOSE-LONG] SL:{self.n2_long_price} PNL: {pnl}")
                        self.orderFO(self.symbol, "SELL", "LONG", qty)
                        self.n2_long_price = 0

                    if self.symbol in self.short_dict and 0 < self.n2_short_price and close > self.n2_short_price:

                        self.SHORT_LOCK = 1
                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        quantity = self.short_dict[self.symbol]['positionAmt']
                        pnl = ((close-entryPrice)/entryPrice)*-100
                        Message(f"[{self.symbol} SL CLOSE-SHORT] SL:{self.n2_short_price} PNL: {pnl}")
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)
                        self.n2_short_price = 0

                if self.SYSTEM2:
                    if self.symbol in self.long_dict and 0 < self.n2_long_price2 and close < self.n2_long_price2:

                        self.LONG_LOCK2 = 1
                        price = self.long_dict[self.symbol]['entryPrice']
                        qty = self.long_dict[self.symbol]['positionAmt']
                        pnl = ((close-price)/price)*100
                        Message(f"[{self.symbol} SL CLOSE-LONG 2] SL:{self.n2_long_price2} PNL: {pnl}")
                        self.orderFO(self.symbol, "SELL", "LONG", qty)
                        self.n2_long_price2 = 0

                    if self.symbol in self.short_dict and 0 < self.n2_short_price2 and close > self.n2_short_price2:

                        self.SHORT_LOCK2 = 1
                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        quantity = self.short_dict[self.symbol]['positionAmt']
                        pnl = ((close-entryPrice)/entryPrice)*-100
                        Message(f"[{self.symbol} SL CLOSE-SHORT 2] SL:{self.n2_short_price2} PNL: {pnl}")
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)
                        self.n2_short_price2 = 0

                del self.close_list[0]

                self.last_received_time = time.time()
                self.data_received_count += 1

        else:
            e = msg['e']

            if e == 'error':
                Message(f"WebSocket Error: {msg['m']}")
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

    def start_websocket(self, _symbol, _time):

        # ThreadedWebsocketManager 인스턴스 생성
        twm = ThreadedWebsocketManager(api_key, api_secret)

        # WebSocket 관리자 시작
        twm.start()

        print("WebSocket Manager 시작 중...")

        # 캔들스틱(Kline) 스트림 구독
        self.ls = _symbol.lower() # symbol: 거래 쌍 (예: 'BTCUSDT')
        self.ki = _time
        twm.start_futures_user_socket(self.handle_socket_message)
        twm.start_futures_multiplex_socket(self.handle_socket_message, [f'{self.ls}@kline_{_time}'])

        try:
            while True:
                # 일정 간격으로 연결 상태 확인
                time.sleep(1)  # 1초마다 상태 체크

                if self.is_connected_flag:
                    pass
                    # print(f"현재 연결 상태: 활성 (총 {self.data_received_count}개 데이터 수신됨). 마지막 수신 시간: {time.time() - self.last_received_time:.2f}초 전")
                else:
                    print("현재 연결 상태: 비활성 또는 재연결 대기 중...")
                
                # 마지막 데이터 수신 시간을 기준으로 연결 끊김 여부 판단
                if self.last_received_time is not None and (time.time() - self.last_received_time > 60): # 60초 이상 데이터 없으면 문제로 간주
                    print("경고: 60초 이상 데이터 수신 없음. 연결 문제 가능성 있음.")
                    # 이때 ThreadedWebsocketManager는 내부적으로 재연결을 시도할 것입니다.
                    # 명시적인 재연결 코드를 여기에 넣을 필요는 없습니다.

        except KeyboardInterrupt:
            print("\nCtrl+C 감지. WebSocket Manager 종료 중...")
            twm.stop() # WebSocket 관리자 종료
            twm.join() # 스레드가 완전히 종료될 때까지 대기
            print("WebSocket Manager 종료 완료.")

if __name__ == "__main__":

    with open("./binance.key") as f:
        lines = f.readlines()
        api_key = lines[0].strip()
        api_secret = lines[1].strip()

    Binance(api_key, api_secret)
