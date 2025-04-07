import time
from config import *
from binance.client import Client
from binance import ThreadedWebsocketManager


class Binance:

    def __init__(self, _access, _secret):

        API_KEY = _access
        API_SECRET = _secret

        self.client = Client(API_KEY,API_SECRET)

        self.symbol = "XRPUSDT"
        self.TIME = self.client.KLINE_INTERVAL_3MINUTE # 1, 3, 5, 15, 30

        self.ORDER_LOCK = True

        self.ORDER = False
        self.HALF = True
        self.Scalping = True
        self.balance_dict = {}
        self.ochl_dict = {}

        self.max_profit = 0

        self.min_profit_list = []

        self.mark_price = 0.0

        self.LONG_SIGNAL = False
        self.SHORT_SIGNAL = False

        self.order_buy_dict = {}
        self.order_sell_dict = {}

        # RUN
        self.set_dafault_settings()
        self.get_position()
        self.get_balance()
        print(f"\nStart Binance...{self.profit} {self.risk}\n")
        self.get_candle_chart()

        self.start_websocket(self.symbol)

    def set_dafault_settings(self):

        leverage = 1
        self.leverage = leverage
        if leverage != 1:
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
        risk = 1.5 # [0.25-1] [0.5-1.5] 투자금액 기준 손절할 금액 비율 (%)
        profit = 1.2
        balance = self.client.futures_account_balance()

        # profit and loss ratio
        profit_ratio = 1.5 # profit
        loss_ratio = 1.2

        손익비 = f'{profit_ratio} : {loss_ratio}'

        for i in balance:

            if float(i['balance']) > 0:

                balance = float(i['balance'])
                balance = round(balance)
                deposit = balance*(position/100)
                self.deposit = round(deposit, 1) # USDT

                risk = balance*(risk/100)*-1*self.leverage
                self.risk = round(risk, 2) # USDT

                profit = balance*(profit/100)*self.leverage
                self.profit = round(profit, 2) # USDT

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

            # if self.ORDER == False:

            #     self.ORDER = True

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

        self.low_list = []
        self.high_list = []
        self.open_list = []
        self.close_list = []

        count = 0
        candles = self.client.futures_klines(symbol=self.symbol, interval=self.TIME)

        for candle in candles:
            open = float(candle[1]) # Open
            high = float(candle[2]) # High
            low = float(candle[3]) # Low
            close = float(candle[4]) # Close

            self.open_list.append(open)
            self.low_list.append(low)
            self.high_list.append(high)
            self.close_list.append(close)
            count += 1

            if count == len(candles) - 1:
                break

        self.open_list.reverse()
        self.low_list.reverse()
        self.high_list.reverse()
        self.close_list.reverse()

    def scalping_tf(self,maBase,_ema_src, maRef,_array=0):
        change_ma = _ema_src[_array] - _ema_src[_array+1]
        change_ma = float(format(change_ma, '.4f'))

        if change_ma >= 0 and maBase>maRef:
            return 1
        elif change_ma <= 0 and maBase<maRef:
            return -1
        else:
            return 0

    def handle_socket_message(self, msg):

        if 'stream' in msg:

            if msg['stream'] == f'{self.ls}@kline_{self.ki}':

                k = msg['data']['k']

                closed = k['x']

                open = float(k['o'])
                close = float(k['c'])
                high = float(k['h'])
                low = float(k['l'])
                
                if closed == True:

                    self.open_list.insert(0, open)
                    self.high_list.insert(0, high)
                    self.low_list.insert(0, low)
                    self.close_list.insert(0, close)


                    if self.Scalping == False:

                        open_1 = self.open_list[1]
                        close_1 = self.close_list[1]
                        ema = Indicator.ema(self.close_list, 60, None)

                        cLong = (ema[0] >= ema[2]) and (ema[1] < ema[3])

                        cSHort = (ema[0] <= ema[2]) and (ema[1] > ema[3])

                        ### Entry Condition ###
                        # Long
                        long_condition = (open < close) and (open_1 > close_1) and cLong

                        # Short
                        short_condition = (open > close) and (open_1 < close_1) and cSHort

                    else:
                        ema12 = Indicator.ema(self.close_list, 12, None)
                        ema36 = Indicator.ema(self.close_list, 36, None)

                        if ema12[0] != ema36[0]:

                            sEma12 = self.scalping_tf(ema12[0], ema12, ema36[0])
                            sEma36 = self.scalping_tf(ema12[0], ema36, ema36[0])

                            sEma12_1 = self.scalping_tf(ema12[1], ema12, ema36[1], 1)
                            sEma36_1 = self.scalping_tf(ema12[1], ema36, ema36[1], 1)

                            long_con1 = (ema12[0] > ema36[0]) and ((sEma36 and sEma12) == 1)
                            long_con2 = (ema12[1] <= ema36[1]) and ((sEma36_1 and sEma12_1) != 1)

                            long_condition = long_con1 and long_con2

                            short_con1 = (ema12[0] < ema36[0]) and ((sEma36 and sEma12) == -1)
                            short_con2 = (ema12[1] >= ema36[1]) and ((sEma36_1 and sEma12_1) != -1)

                            short_condition = short_con1 and short_con2

                            if long_condition != short_condition:
                            ### End Condition ###
                                # Long
                                long_end = short_condition
                                # Short
                                short_end = long_condition

                                if self.balance_dict != {}:

                                    # LONG 정리
                                    if "LONG" in self.balance_dict[self.symbol].keys():
                                        lpositionAmt = self.balance_dict[self.symbol]["LONG"]['positionAmt']

                                        if self.symbol not in self.order_sell_dict.keys():

                                            if long_end == True:
                                                self.HALF = False
                                                Message("Sell Long and Buy Short")
                                                self.orderFO(self.symbol, "SELL", lpositionAmt)
                                                time.sleep(1)
                                                self.get_balance()
                                                ask_price = self.get_book_order_price("ask")
                                                amount = round(self.deposit/ask_price,1)
                                                self.orderFO(self.symbol, "SELL", amount)

                                    # SHORT 정리
                                    else:
                                        spositionAmt = self.balance_dict[self.symbol]["SHORT"]['positionAmt']

                                        if self.symbol not in self.order_buy_dict.keys():

                                            if short_end == True:
                                                self.HALF = False
                                                Message("Sell Short and Buy Long")
                                                self.orderFO(self.symbol, "BUY", spositionAmt)
                                                time.sleep(1)
                                                self.get_balance()
                                                bid_price = self.get_book_order_price("bid")
                                                amount = round(self.deposit/bid_price,1)
                                                self.orderFO(self.symbol, "BUY", amount)

                                if self.balance_dict == {}:

                                    # LONG 진입
                                    if long_condition == True:
                                        Message("Buy Long")
                                        bid_price = self.get_book_order_price("bid")
                                        amount = round(self.deposit/bid_price,1)
                                        self.orderFO(self.symbol, "BUY", amount)

                                    # SHORT 진입
                                    if short_condition == True:
                                        Message("Buy Short")
                                        ask_price = self.get_book_order_price("ask")
                                        amount = round(self.deposit/ask_price,1)
                                        self.orderFO(self.symbol, "SELL", amount)

                ### 정리할 경우 ###
                if self.balance_dict != {}:

                    # LONG 정리
                    if "LONG" in self.balance_dict[self.symbol].keys():
                        lpositionAmt = self.balance_dict[self.symbol]["LONG"]['positionAmt']
                        lentryPrice = self.balance_dict[self.symbol]["LONG"]['entryPrice']
                        self.balance_dict[self.symbol]["LONG"]['balance'] = round(float(lpositionAmt*close),4)
                        if self.mark_price != 0:
                            unRealizedProfit = (self.mark_price - lentryPrice) * lpositionAmt
                            self.balance_dict[self.symbol]["LONG"]['unRealizedProfit'] = round(float(unRealizedProfit),3)
                        lurp = self.balance_dict[self.symbol]["LONG"]['unRealizedProfit']
                        lurp = round(lurp, 3)

                        if self.symbol not in self.order_sell_dict.keys():

                            # LONG 절반 익절 (조건)
                            if self.HALF == False and lurp >= self.profit:
                                self.HALF = True
                                lpositionAmt = round(lpositionAmt/2, 1)
                                self.orderFO(self.symbol, "SELL", lpositionAmt)

                            # LONG 전부 손절 (조건)
                            if lurp <= self.risk:
                                self.HALF = False
                                self.max_profit = 0
                                self.orderFO(self.symbol, "SELL", lpositionAmt)

                    # SHORT 정리
                    else:
                        spositionAmt = self.balance_dict[self.symbol]["SHORT"]['positionAmt']
                        sentryPrice = self.balance_dict[self.symbol]["SHORT"]['entryPrice']
                        self.balance_dict[self.symbol]["SHORT"]['balance'] = round(float(spositionAmt*close),4) 

                        if self.mark_price != 0:
                            unRealizedProfit = (self.mark_price - sentryPrice) * spositionAmt
                            self.balance_dict[self.symbol]["SHORT"]['unRealizedProfit'] = round(float(unRealizedProfit*-1),3)
                        surp = self.balance_dict[self.symbol]["SHORT"]['unRealizedProfit']
                        surp = round(surp, 3)

                        if self.symbol not in self.order_buy_dict.keys():

                            # SHORT 절반 익절 (조건)
                            if self.HALF == False and surp >= self.profit:
                                self.HALF = True
                                spositionAmt = round(spositionAmt/2,1)
                                self.orderFO(self.symbol, "BUY", spositionAmt)

                            # SHORT 전부 손절 (조건)
                            if surp <= self.risk:
                                self.HALF = False
                                self.max_profit = 0
                                self.orderFO(self.symbol, "BUY", spositionAmt)

            elif msg['stream'] == f'{self.ls}@markPrice':

                mark = msg['data']['p']
                self.mark_price = round(float(mark),3)
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

            elif e == "ORDER_TRADE_UPDATE": # 미체결 체결
                pass

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
        streams = [f'{ls}@kline_{ki}',f'{ls}@markPrice']
        twm.start_futures_multiplex_socket(self.handle_socket_message, streams)
        twm.join()

if __name__ == "__main__":

    with open("./binance.key") as f:
        lines = f.readlines()
        api_key = lines[0].strip()
        api_secret = lines[1].strip()

    binance = Binance(api_key, api_secret)