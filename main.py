from config import *
from binance.client import Client
from binance import ThreadedWebsocketManager


class Binance:

    def __init__(self, _access, _secret, _test:bool=False):

        API_KEY = _access
        API_SECRET = _secret

        if _test:
            API_KEY = 'de67f50b776dc8af9f88c9035e46725d0b63a864ea3cad411618430af7ac83e2'
            API_SECRET = '5d4a6177bda0eb57929c68f9fabbcf640c9335acd5566cd28805496e23eeb779'

        self.client = Client(API_KEY, API_SECRET, testnet=_test)

        self.symbol = "XRPUSDT"
        self.TIME = self.client.KLINE_INTERVAL_15MINUTE # 1, 3, 5, 15, 30

        self.ORDER_LOCK = True
        self.LONG_LOCK = True
        self.SHORT_LOCK = True

        self.n2_long_price = 0.
        self.n2_short_price = 0.

        self.order_long_Id = 0
        self.order_short_Id = 0

        self.order_long_dict = {}
        self.order_short_dict = {}

        # RUN
        print(f"\nStart Binance...\n")
        self.set_the_default_settings()
        # self.get_exchange_info()
        self.get_candle_chart()

        self.start_websocket(self.symbol)

    def get_exchange_info(self):

        info = self.client.futures_exchange_info()

        timezone = info['timezone']
        serverTime = info['serverTime']
        futuresType = info['futuresType']
        rateLimits = info['rateLimits']
        exchangeFilters = info['exchangeFilters']
        assets = info['assets']
        symbols = info['symbols']

        for i in symbols:
            if i['symbol'] == self.symbol:
                filters = (i['filters'])

        for i in filters:

            filterType = i['filterType']
            if filterType == 'PERCENT_PRICE':
                multiplierDown = i['multiplierDown']
                multiplierUp = i['multiplierUp']

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

        self.balance_dict = {}
        position = 40 # 10 ~ 20 전체자산 기준 투자할 금액 비율 (%)
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

    def orderFO(self, _symbol:str, _side:str, _positionSide:str, _amount:float, _price = 0):

        if self.ORDER_LOCK == False:

            if (_positionSide == "LONG" and self.order_long_Id == 0) or (_positionSide == "SHORT" and self.order_short_Id == 0):

                if _price == 0:

                    order = self.client.futures_create_order(
                        symbol = _symbol,
                        side = _side, # BUY or SELL
                        type = 'MARKET', # LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
                        positionSide= _positionSide,
                        quantity = _amount,
                        )
                else:
                    order = self.client.futures_create_order(
                        symbol = _symbol, 
                        side = _side, # BUY or SELL
                        type = 'LIMIT', # LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
                        positionSide= _positionSide,
                        quantity = _amount,
                        price = _price,
                        timeinforce = "GTC"
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

            open = float(candle[1])
            high = float(candle[2])
            low = float(candle[3])
            close = float(candle[4])

            self.open_list.append(open)
            self.high_list.append(high)
            self.low_list.append(low)
            self.close_list.append(close)
            count += 1

            if count == len(candles) - 1:
                break

        self.open_list.reverse()
        self.high_list.reverse()
        self.low_list.reverse()
        self.close_list.reverse()

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

                    _s1_long = Strategies.system1(self.high_list, self.low_list)
                    _s1_short = Strategies.system1(self.high_list, self.low_list,_high_len=15,_low_len=30)

                    atr = Indicators.atr(self.high_list,self.low_list,self.close_list,30)
                    atr = round(atr, 4)*2

                    long_condition = _s1_long[0]
                    long_end = _s1_long[1]

                    short_condition = _s1_short[1]
                    short_end = _s1_short[0]

                    if self.symbol not in self.long_dict and self.LONG_LOCK:
                        if long_end:
                            self.LONG_LOCK = False

                    if self.symbol not in self.short_dict and self.SHORT_LOCK:
                        if short_end:
                            self.SHORT_LOCK = False

                    # Open Positions
                    if self.symbol not in self.long_dict.keys() and self.LONG_LOCK == False and long_condition:

                        Message(f"[OPEN-LONG] {self.symbol}")
                        bid_price = self.get_book_order_price("bid")
                        amount = round(self.deposit/bid_price, 1)
                        self.n2_long_price = round(self.close_list[0] - atr, 5)
                        self.orderFO(self.symbol, "BUY", "LONG", amount)

                    if self.symbol not in self.short_dict.keys() and self.SHORT_LOCK == False and short_condition:

                        Message(f"[OPEN-SHORT] {self.symbol}")
                        ask_price = self.get_book_order_price("ask")
                        amount = round(self.deposit/ask_price, 1)
                        self.n2_short_price = round(self.close_list[0] + atr, 5)
                        self.orderFO(self.symbol, "SELL", "SHORT", amount)

                    # [TP] Close Positions 
                    if self.symbol in self.long_dict.keys() and long_end:

                        entryPrice = self.long_dict[self.symbol]['entryPrice']
                        long_pnl = round(((close-entryPrice)/entryPrice)*100, 4)
                        quantity = float(self.long_dict[self.symbol]['positionAmt'])
                        Message(f"[TP CLOSE-LONG] {self.symbol} pnl:{long_pnl} sl_price:{self.n2_long_price}")
                        self.n2_long_price = 0.
                        self.orderFO(self.symbol, "SELL", "LONG", quantity)

                    if self.symbol in self.short_dict.keys() and short_end:

                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        short_pnl = round(((close-entryPrice)/entryPrice)*-100, 4)
                        quantity = float(self.short_dict[self.symbol]['positionAmt'])
                        Message(f"[TP CLOSE-SHORT] {self.symbol} pnl:{short_pnl} sl_price:{self.n2_short_price}")
                        self.n2_short_price = 0.
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)                        

                self.close_list.insert(0, close)

                # [SL 2N] Close Positions
                if self.symbol in self.long_dict.keys():

                    if 0 < close and close < self.n2_long_price:

                        entryPrice = self.long_dict[self.symbol]['entryPrice']
                        quantity = self.long_dict[self.symbol]['positionAmt']
                        long_pnl = ((close-entryPrice)/entryPrice)*100
                        Message(f"[SL CLOSE-LONG] {self.symbol} PNL: {long_pnl} sl_Price:{self.n2_long_price}")
                        self.n2_long_price = 0.
                        self.LONG_LOCK = True
                        self.orderFO(self.symbol, "SELL", "LONG", quantity)

                if self.symbol in self.short_dict.keys():

                    if 0 < self.n2_short_price and self.n2_short_price < close:

                        entryPrice = self.short_dict[self.symbol]['entryPrice']
                        quantity = self.short_dict[self.symbol]['positionAmt']
                        short_pnl = ((close-entryPrice)/entryPrice)*-100
                        Message(f"[SL CLOSE-SHORT] {self.symbol} PNL: {short_pnl} sl_Price:{self.n2_short_price}")
                        self.n2_short_price = 0.
                        self.SHORT_LOCK = True
                        self.orderFO(self.symbol, "BUY", "SHORT", quantity)

                del self.close_list[0]
        else:
            e = msg['e']

            if e == 'ORDER_TRADE_UPDATE':

                o = msg['o']
                i = o['i']
                if o['X'] == 'FILLED':

                    if i == self.order_long_Id:
                        self.order_long_Id = 0

                    if i == self.order_short_Id:
                        self.order_short_Id = 0

            if e == 'ACCOUNT_UPDATE':
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
        twm.join()

if __name__ == "__main__":

    with open("./binance.key") as f:
        lines = f.readlines()
        api_key = lines[0].strip()
        api_secret = lines[1].strip()

    binance = Binance(api_key, api_secret)
