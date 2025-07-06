from config import *
from binance.client import Client
from binance import ThreadedWebsocketManager


class Binance:

    def __init__(self, _access, _secret):

        self.client = Client(_access, _secret)

        self.symbol = "XRPUSDT"
        self.TIME = self.client.KLINE_INTERVAL_15MINUTE

        self.ORDER_LOCK = True
        self.LONG_LOCK = True
        self.SHORT_LOCK = True

        self.LONG2 = False
        self.SHORT2 = False

        self.SYSTEM2_LONG_LOCK = 0
        self.SYSTEM2_SHORT_LOCK = 0

        self.n2_long_price = 0
        self.n2_short_price = 0

        self.order_long_Id = 0
        self.order_short_Id = 0

        # RUN
        print(f"\nStart Binance...\n")
        self.set_the_default_settings()
        self.get_candle_chart()
        self.start_websocket(self.symbol)

    def set_the_default_settings(self):

        self.change_leverage()
        self.change_hedge_mode()
        self.get_balance()
        self.get_positions()

    def change_leverage(self, _leverage:int = 10):

        self.leverage = _leverage
        self.client.futures_change_leverage(symbol=self.symbol, leverage=_leverage)

    def change_hedge_mode(self):
        
        mode = self.client.futures_get_position_mode()
        if mode['dualSidePosition'] == False:
            self.client.futures_change_position_mode(dualSidePosition="true")

    def get_balance(self):

        position = 45
        self.balance_dict = {}
        balances = self.client.futures_account_balance()

        for i in balances:

            asset = i['asset']
            balance = float(i['balance'])
            availableBalance = float(i['availableBalance'])

            if balance > 0:
                self.deposit = balance*(position/100)*self.leverage
                self.balance_dict.update({asset:{'balance':balance,'availableBalance':availableBalance}})

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
                    positionSide= _positionSide,
                    quantity = _amount,
                    )

            if order != None:
                if _positionSide == "LONG":
                    self.order_long_Id = order['orderId']
                else:
                    self.order_short_Id = order['orderId']

    def get_candle_chart(self):

        self.open_list = []
        self.high_list = []
        self.low_list = []
        self.close_list = []

        count = 0
        candles = self.client.futures_klines(symbol=self.symbol, interval=self.TIME)

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
                    atr = Indicators.atr(self.high_list,self.low_list,self.close_list)
                    atr = round(atr, 4)*2

                    # SYSTEM 2
                    if self.SYSTEM2_LONG_LOCK != 0:
                        _s1_long2 = Strategies.system(self.high_list, self.low_list, _high_len=77, _low_len=28)

                        long_condition2 = _s1_long2[0]
                        long_end2 = _s1_long2[1]

                        # Open Positions
                        if self.symbol not in self.long_dict.keys() and self.LONG2 == False and self.LONG_LOCK == False and long_condition2 != long_end2 and long_condition2:
                            self.LONG2 = True
                            bid_price = self.get_book_order_price("bid")
                            amount = round(self.deposit/bid_price, 1)
                            self.n2_long_price = round(close - atr, 5)
                            Message(f"[OPEN-LONG 2] {self.symbol} sl:{self.n2_long_price}")
                            self.orderFO(self.symbol, "BUY", "LONG", amount)

                        # [TP] Close Positions 
                        if self.symbol in self.long_dict.keys() and long_condition2 != long_end2 and self.SYSTEM2_LONG_LOCK == 0 and long_end2:
                            self.LONG2 = False
                            self.LONG_LOCK = True
                            entryPrice = self.long_dict[self.symbol]['entryPrice']
                            pnl = round(((close-entryPrice)/entryPrice)*100, 4)
                            quantity = float(self.long_dict[self.symbol]['positionAmt'])
                            Message(f"[TP CLOSE-LONG 2] {self.symbol} sl:{self.n2_long_price}, PNL: {pnl}")
                            self.n2_long_price = 0.
                            self.orderFO(self.symbol, "SELL", "LONG", quantity)

                    if self.SYSTEM2_SHORT_LOCK != 0:
                        _s1_short2 = Strategies.system(self.high_list, self.low_list, _high_len=28, _low_len=77)

                        short_condition2 = _s1_short2[1]
                        short_end2 = _s1_short2[0]

                        if self.symbol not in self.short_dict.keys() and self.SHORT2 == False and self.SHORT_LOCK == False and short_condition2 != short_end2 and short_condition2:
                            
                            self.SHORT2 = True
                            ask_price = self.get_book_order_price("ask")
                            amount = round(self.deposit/ask_price, 1)
                            self.n2_short_price = round(close + atr, 5)
                            Message(f"[OPEN-SHORT 2] {self.symbol} sl:{self.n2_short_price}")
                            self.orderFO(self.symbol, "SELL", "SHORT", amount)

                        if self.symbol in self.short_dict.keys() and short_condition2 != short_end2 and self.SYSTEM2_SHORT_LOCK == 0 and short_end2:
                            self.SHORT2 = False
                            self.SHORT_LOCK = True
                            entryPrice = self.short_dict[self.symbol]['entryPrice']
                            pnl = round(((close-entryPrice)/entryPrice)*-100, 4)
                            quantity = float(self.short_dict[self.symbol]['positionAmt'])
                            Message(f"[TP CLOSE-SHORT 2] {self.symbol} sl:{self.n2_short_price} PNL: {pnl}")
                            self.n2_short_price = 0.
                            self.orderFO(self.symbol, "BUY", "SHORT", quantity)

                    # SYSTEM 1
                    _s1_long = Strategies.system(self.high_list, self.low_list)
                    _s1_short = Strategies.system(self.high_list, self.low_list, _high_len=14, _low_len=28)

                    long_condition = _s1_long[0]
                    long_end = _s1_long[1]

                    short_condition = _s1_short[1]
                    short_end = _s1_short[0]

                    long_condition = _s1_long[0]
                    long_end = _s1_long[1]

                    short_condition = _s1_short[1]
                    short_end = _s1_short[0]

                    if (long_condition != long_end) and long_end == True and self.SYSTEM2_LONG_LOCK == -1:
                        self.SYSTEM2_LONG_LOCK = 0

                    if (short_condition != short_end) and short_end == True and self.SYSTEM2_SHORT_LOCK == -1:
                        self.SYSTEM2_SHORT_LOCK = 0

                    if (long_condition != long_end) and long_condition == True and self.SYSTEM2_LONG_LOCK == 1:
                        self.SYSTEM2_LONG_LOCK = -1

                    if (short_condition != short_end) and short_condition == True and self.SYSTEM2_SHORT_LOCK == 1:
                        self.SYSTEM2_SHORT_LOCK = -1

                    if (long_condition != long_end) and (self.LONG_LOCK and long_end) == True:
                        Message("LONG_LOCK: False")
                        self.LONG_LOCK = False

                    if (short_condition != short_end) and (self.SHORT_LOCK and short_end) == True:
                        Message("SHORT_LOCK: False")
                        self.SHORT_LOCK = False

                    # Open Positions
                    if self.symbol not in self.long_dict.keys() and self.LONG2 == False and self.SYSTEM2_LONG_LOCK == 0 and self.LONG_LOCK == False and long_condition != long_end and long_condition:

                        bid_price = self.get_book_order_price("bid")
                        amount = round(self.deposit/bid_price, 1)
                        self.n2_long_price = round(close - atr, 5)
                        Message(f"[OPEN-LONG 1] {self.symbol}, sl:{self.n2_long_price}")
                        self.orderFO(self.symbol, "BUY", "LONG", amount)

                    if self.symbol not in self.short_dict.keys() and self.SHORT2 == False and self.SYSTEM2_SHORT_LOCK == 0 and self.SHORT_LOCK == False and short_condition != short_end and short_condition:

                        ask_price = self.get_book_order_price("ask")
                        amount = round(self.deposit/ask_price, 1)
                        self.n2_short_price = round(close + atr, 5)
                        Message(f"[OPEN-SHORT 1] {self.symbol}, sl:{self.n2_short_price}")
                        self.orderFO(self.symbol, "SELL", "SHORT", amount)

                    # [TP] Close Positions 
                    if self.symbol in self.long_dict.keys() and long_condition != long_end and long_end:

                        entryPrice = self.long_dict[self.symbol]['entryPrice']
                        pnl = round(((close-entryPrice)/entryPrice)*100, 4)
                        quantity = float(self.long_dict[self.symbol]['positionAmt'])
                        Message(f"[TP CLOSE-LONG 1] {self.symbol} , sl:{self.n2_long_price}, PNL: {pnl}")
                        self.n2_long_price = 0.
                        if pnl > 0:
                            Message("[LONG 1] 이익 실현, 다음 매수 신호만 무시")
                            self.SYSTEM2_LONG_LOCK = 1
                        self.orderFO(self.symbol, "SELL", "LONG", quantity)

                    if self.symbol in self.short_dict.keys() and short_condition != short_end and short_end:

                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        pnl = round(((close-entryPrice)/entryPrice)*-100, 4)
                        quantity = float(self.short_dict[self.symbol]['positionAmt'])
                        Message(f"[TP CLOSE-SHORT 1] {self.symbol} ,sl:{self.n2_short_price}, PNL: {pnl}")
                        self.n2_short_price = 0.
                        if pnl > 0:
                            Message("[SHORT 1] 이익 실현, 다음 매수 신호만 무시")
                            self.SYSTEM2_SHORT_LOCK = 1
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)                        

                self.close_list.insert(0, close)

                # [SL 2N] Close Positions
                if self.symbol in self.long_dict.keys():

                    if 0 < self.n2_long_price and close < self.n2_long_price:

                        entryPrice = self.long_dict[self.symbol]['entryPrice']
                        quantity = self.long_dict[self.symbol]['positionAmt']
                        pnl = ((close-entryPrice)/entryPrice)*100
                        Message(f"[SL CLOSE-LONG] {self.symbol} , sl:{self.n2_long_price}, PNL: {pnl}")
                        self.LONG2 = False
                        self.LONG_LOCK = True
                        Message("LONG_LOCK: True")
                        self.n2_long_price = 0
                        self.orderFO(self.symbol, "SELL", "LONG", quantity)

                if self.symbol in self.short_dict.keys():

                    if 0 < self.n2_short_price and close > self.n2_short_price:

                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        quantity = self.short_dict[self.symbol]['positionAmt']
                        pnl = ((close-entryPrice)/entryPrice)*-100
                        Message(f"[SL CLOSE-SHORT] {self.symbol},sl:{self.n2_short_price},  PNL: {pnl}")
                        self.SHORT2 = False
                        self.SHORT_LOCK = True
                        Message("SHORT_LOCK: True")
                        self.n2_short_price = 0
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)

                del self.close_list[0]
        else:
            e = msg['e']

            if e == 'error':
                Message(f"WebSocket Error: {msg['m']}")
                print(f"WebSocket Error: {msg['m']}")
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

    def start_websocket(self, _symbol):
        twm = ThreadedWebsocketManager(api_key, api_secret)
        twm.start()
        ls = _symbol.lower()
        self.ls = ls
        ki = self.TIME
        self.ki = ki
        twm.start_futures_user_socket(self.handle_socket_message)
        streams = [f'{ls}@kline_{ki}']
        twm.start_futures_multiplex_socket(self.handle_socket_message, streams)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            Message("Stopping websocket manager...")
            print("Stopping websocket manager...")
            twm.stop()
            twm.join()

if __name__ == "__main__":

    with open("./binance.key") as f:
        lines = f.readlines()
        api_key = lines[0].strip()
        api_secret = lines[1].strip()

    Binance(api_key, api_secret)
