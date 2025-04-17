import time
from config import *
from binance.client import Client
from binance import ThreadedWebsocketManager


class Binance:

    def __init__(self, _access, _secret):

        API_KEY = _access
        API_SECRET = _secret

        self.client = Client(API_KEY, API_SECRET)

        self.symbol = "XRPUSDT"
        self.TIME = self.client.KLINE_INTERVAL_1MINUTE # 1, 3, 5, 15, 30

        self.ORDER_LOCK = False

        self.balance_dict = {}
        self.order_buy_dict = {}
        self.order_sell_dict = {}

        # RUN
        self.set_dafault_settings()
        self.get_position()
        self.get_balance()
        print(f"\nStart Binance... {self.risk}\n")
        self.get_candle_chart()

        self.start_websocket(self.symbol)

    def set_dafault_settings(self):

        leverage = 1
        self.leverage = leverage
        self.client.futures_change_leverage(symbol=self.symbol, leverage=leverage)

    def get_position(self):

        # unRealizedProfit = (markPrice -entryPrice) * amount
        position = self.client.futures_position_information()
        position = list(position)

        if position == []:
            if self.balance_dict != {}:
                self.balance_dict = {}
        else:
            for i in position:

                symbol = str(i['symbol'])
                notional = float(i['notional'])

                if notional != 0:
                    notional = round(float(i['notional']),4)
                    entryPrice = float(i['entryPrice'])
                    positionAmt = abs(float(i['positionAmt']))
                    unRealizedProfit = float(round(float(i['unRealizedProfit']),3))
                    posit = "LONG"
                    if notional < 0:
                        posit = "SHORT"
                        notional = notional*-1

                    self.balance_dict.update({symbol:{posit:{'balance':notional, 'positionAmt':positionAmt, 'unRealizedProfit':unRealizedProfit,'entryPrice':entryPrice}}})

                elif self.balance_dict != {}:

                    if symbol in self.balance_dict.keys():

                        if notional == 0:
                            self.balance_dict.pop(symbol)

    def get_balance(self):

        position = 80 # 10 ~ 20 전체자산 기준 투자할 금액 비율 (%)
        risk = 0.5 # [0.25-1] [0.5-1.5] 투자금액 기준 손절할 금액 비율 (%)

        balance = self.client.futures_account_balance()

        for i in balance:

            if float(i['balance']) > 0:

                balance = float(i['balance'])
                balance = round(balance)
                deposit = balance*(position/100)
                self.deposit = round(deposit, 1) # USDT

                risk = balance*(risk/100)*-1*self.leverage
                self.risk = round(risk, 2) # USDT

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

    def orderFO(self, _symbol, _side:str, _amount:float, _price = 0):

        time.sleep(0.2)

        if self.ORDER_LOCK == False:

            if _price == 0:

                order = self.client.futures_create_order(
                    symbol = _symbol,
                    side = _side, # BUY or SELL
                    type = 'MARKET', # LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
                    positionSide= "BOTH",
                    quantity = _amount,
                    # reduceOnly = 'true',
                    )

            else:
                order = self.client.futures_create_order(
                    symbol = _symbol, 
                    side = _side, # BUY or SELL
                    type = 'LIMIT', # LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET
                    positionSide= "BOTH",
                    quantity = _amount,
                    price = _price,
                    timeinforce = "GTC"
                    # reduceOnly = 'true',
                    )

            if order != None:

                if _side == "BUY":
                    self.order_buy_dict.update({_symbol:_side})
                else:
                    self.order_sell_dict.update({_symbol:_side})

    def get_candle_chart(self):

        self.close_list = []
        count = 0
        candles = self.client.futures_klines(symbol=self.symbol, interval=self.TIME)

        for candle in candles:

            close = float(candle[4])
            self.close_list.append(close)
            count += 1

            if count == len(candles) - 1:
                break

        self.close_list.reverse()

    def scalping_tf(self, _ema_src, _short, _long, _array=0):

        change_ma = _ema_src[_array] - _ema_src[_array+1]
        change_ma = float(format(change_ma, '.4f'))

        if change_ma >= 0 and _short>_long:
            return 1
        elif change_ma <= 0 and _short<_long:
            return -1
        else:
            return 0

    def handle_socket_message(self, msg):

        if 'stream' in msg:

            if msg['stream'] == f'{self.ls}@kline_{self.ki}':

                k = msg['data']['k']
                closed = k['x']
                close = float(k['c'])
                
                if closed == True:

                    self.close_list.insert(0, close)

                    ema12 = Indicator.ema(self.close_list, 12, None)
                    ema36 = Indicator.ema(self.close_list, 36, None)

                    sEma12 = self.scalping_tf(ema12, ema12[0], ema36[0])
                    sEma36 = self.scalping_tf(ema36, ema12[0], ema36[0])

                    sEma12_1 = self.scalping_tf(ema12, ema12[1], ema36[1], 1)
                    sEma36_1 = self.scalping_tf(ema36, ema12[1], ema36[1], 1)

                    long_condition = (ema12[0] > ema36[0]) and ((sEma12 + sEma36) == 2) and (ema12[1] <= ema36[1]) and ((sEma12_1 + sEma36_1) != 2)
                    short_condition = (ema12[0] < ema36[0]) and ((sEma12 + sEma36) == -2) and (ema12[1] >= ema36[1]) and ((sEma12_1 + sEma36_1) != -2)

                    short_end = long_condition
                    long_end = short_condition

                    if self.balance_dict != {}:

                        # LONG 정리
                        if "LONG" in self.balance_dict[self.symbol].keys():

                            if self.symbol not in self.order_sell_dict.keys() and long_end == True:

                                Message("[CDTN] Close Long")
                                positionAmt = self.balance_dict[self.symbol]["LONG"]['positionAmt']
                                self.orderFO(self.symbol, "SELL", positionAmt)

                                if short_condition == True:
                                    Message("[CDTN] ... & Entry Short")
                                    time.sleep(1)
                                    self.get_balance()
                                    ask_price = self.get_book_order_price("ask")
                                    amount = round(self.deposit/ask_price, 1)
                                    self.orderFO(self.symbol, "SELL", amount)

                        # SHORT 정리
                        else:
                            if self.symbol not in self.order_buy_dict.keys() and short_end == True:

                                Message("[CDTN] Close Short")
                                positionAmt = self.balance_dict[self.symbol]["SHORT"]['positionAmt']
                                self.orderFO(self.symbol, "BUY", positionAmt)

                                if long_condition == True:
                                    Message("[CDTN] ... & Entry Long")
                                    time.sleep(1)
                                    self.get_balance()
                                    bid_price = self.get_book_order_price("bid")
                                    amount = round(self.deposit/bid_price,1)
                                    self.orderFO(self.symbol, "BUY", amount)
                    else:
                        # LONG 진입
                        if long_condition == True:
                            Message("Entry Long")
                            bid_price = self.get_book_order_price("bid")
                            amount = round(self.deposit/bid_price, 1)
                            self.orderFO(self.symbol, "BUY", amount)

                        # SHORT 진입
                        if short_condition == True:
                            Message("Entry Short")
                            ask_price = self.get_book_order_price("ask")
                            amount = round(self.deposit/ask_price, 1)
                            self.orderFO(self.symbol, "SELL", amount)

                #####################################
                self.close_list.insert(0, close)
                
                del self.close_list[0]
                #####################################

                ### 정리할 경우 ###
                if self.balance_dict != {}:

                    # LONG 정리
                    if "LONG" in self.balance_dict[self.symbol].keys():
                        positionAmt = self.balance_dict[self.symbol]["LONG"]['positionAmt']
                        entryPrice = self.balance_dict[self.symbol]["LONG"]['entryPrice']
                        self.balance_dict[self.symbol]["LONG"]['balance'] = round(float(positionAmt*close),4)

                        unRealizedProfit = (close - entryPrice) * positionAmt
                        self.balance_dict[self.symbol]["LONG"]['unRealizedProfit'] = round(float(unRealizedProfit),3)

                        if self.symbol not in self.order_sell_dict.keys():

                            urp = self.balance_dict[self.symbol]["LONG"]['unRealizedProfit']
                            urp = round(urp, 3)

                            # LONG 전부 손절 (조건)
                            if urp <= self.risk:
                                Message("[SL] Close Long")
                                self.orderFO(self.symbol, "SELL", positionAmt)

                    # SHORT 정리
                    else:
                        positionAmt = self.balance_dict[self.symbol]["SHORT"]['positionAmt']
                        entryPrice = self.balance_dict[self.symbol]["SHORT"]['entryPrice']
                        self.balance_dict[self.symbol]["SHORT"]['balance'] = round(float(positionAmt*close),4) 

                        unRealizedProfit = (close - entryPrice) * positionAmt
                        self.balance_dict[self.symbol]["SHORT"]['unRealizedProfit'] = round(float(unRealizedProfit*-1),3)

                        if self.symbol not in self.order_buy_dict.keys():

                            urp = self.balance_dict[self.symbol]["SHORT"]['unRealizedProfit']
                            urp = round(urp, 3)

                            # SHORT 전부 손절 (조건)
                            if urp <= self.risk:
                                Message("[SL] Close Short")
                                self.orderFO(self.symbol, "BUY", positionAmt)

        else:
            e = msg['e']

            if e == "TRADE_LITE": # 체결만
                symbol = msg['s']
                side = msg['S']

                if symbol in self.order_buy_dict.keys():
                    if side == self.order_buy_dict[symbol]:
                        self.order_buy_dict.pop(symbol)

                if symbol in self.order_sell_dict.keys():
                    if side == self.order_sell_dict[symbol]:
                        self.order_sell_dict.pop(symbol)

                self.get_position()
                self.get_balance()

            elif e == "ACCOUNT_UPDATE":
                self.get_balance()

    def start_websocket(self, _symbol):
        twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret)
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