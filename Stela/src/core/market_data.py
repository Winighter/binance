import logging
from collections import deque
from decimal import Decimal
from typing import  Tuple, Deque
from ..config import KLINE_LIMIT
from ..shared.enums import Side, PositionSide, AlgoOrderType, AlgoOrderEventStatus
from ..api.binance_setup_manager import BinanceSetupManager
import numpy as np
from ..shared.state_manager import BalanceState, PositionState

logger = logging.getLogger("MARKET_DATA")


class SetupError(Exception):
    """Initial setup failed."""
    pass

class MarketDataProcessor:
    def __init__(self, binance_client, symbol, kline_interval, setup_data):

        self.client = binance_client
        self.symbol = symbol
        self.kline_interval = kline_interval
        ohlc_prices = setup_data.get('ohlc_prices')

        self.initialize_candle_data(ohlc_prices=ohlc_prices, maxlen=KLINE_LIMIT)

        # Initialize State
        self.balances = BalanceState()
        self.positions = PositionState()
        self.update_balance(showLog=True)
        self.update_position(showLog=True)

    def initialize_candle_data(self, ohlc_prices, maxlen):
        self.open_prices = deque([item[0] for item in ohlc_prices], maxlen=maxlen)
        self.high_prices = deque([item[1] for item in ohlc_prices], maxlen=maxlen)
        self.low_prices = deque([item[2] for item in ohlc_prices], maxlen=maxlen)
        self.close_prices = deque([item[3] for item in ohlc_prices], maxlen=maxlen)

    def update_candle_data(self, ohlc_data) -> Tuple[Deque[Decimal], Deque[Decimal], Deque[Decimal], Deque[Decimal]]:
        """
        Appends the latest OHLC (Open, High, Low, Close) data to the price deques.

        The function leverages the 'maxlen' property of collections.deque to 
        automatically manage the fixed-size lookback window (FIFO structure), 
        ensuring O(1) time complexity for data updates.

        Args:
            ohlc_data (dict): A dictionary containing the latest OHLC data 
                            (keys 'o', 'h', 'l', 'c').

        Returns:
            tuple: A tuple containing the updated (open_prices, high_prices, 
                low_prices, close_prices) deques.
        """
        # Append the new OHLC values. 
        # Using Decimal conversion ensures high precision for financial calculations.
        # The maxlen property automatically removes the oldest element (popleft) upon append.

        self.open_prices.append(Decimal(str(ohlc_data.get('o'))))
        self.high_prices.append(Decimal(str(ohlc_data.get('h'))))
        self.low_prices.append(Decimal(str(ohlc_data.get('l'))))
        self.close_prices.append(Decimal(str(ohlc_data.get('c'))))

        # Lookback Window Management is now handled automatically by deque's maxlen.
        # The previous O(N) checking and pop(0) logic is safely removed.

        # Return the final, updated, and fixed-size candle deques for indicator calculation.

        return self.open_prices, self.high_prices, self.low_prices, self.close_prices

    def update_balance(self, showLog:bool = True):
        try:
            self.balances.reset()
            self.balances.balance, self.balances.available_balance, self.balances.bnb_balance = self.client.futures_account_balance()
            if showLog:
                logger.info(f"Balance successfully updated. Balance: {self.balances.balance:.2f} Available balance: {self.balances.available_balance:.2f} | BNB : {self.balances.bnb_balance}")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def update_position(self, symbol:str = None, showLog:bool = False):
        '''
        Docstring for update_position
        
        :param self: Description
        :param showLog: Description
        :type showLog: bool

        Updates the open position amount and entry price.
        '''
        try:
            self.positions.reset()
            positions = self.client.futures_position_information(symbol)
            match positions:
                case None:
                    raise ValueError("Position data is missing.")

                case [*positions]:
                    for pos in positions:
                        if self.symbol != pos['symbol']:
                            continue

                        amount = Decimal(pos['positionAmt'])
                        side = str(pos['positionSide'])
                        entry_price = Decimal(pos['entryPrice'])

                        if side == PositionSide.LONG.value and amount > 0:
                            if showLog:
                                logger.info(f"{self.symbol} [LONG-Position] amount:{amount}, entry: {entry_price:.4f}")

                            self.positions.long_amount = amount
                            self.positions.long_entry_price = entry_price

                        elif side == PositionSide.SHORT.value and amount < 0:
                            if showLog:
                                logger.info(f"{self.symbol} [SHORT-Position] amount:{amount * -1}, entry: {entry_price:.4f}")

                            self.positions.short_amount = amount * -1
                            self.positions.short_entry_price = entry_price

            orders = self.client.futures_get_open_orders()

            if orders:
                for order in orders:
                    match order['algoStatus']:
                        case AlgoOrderEventStatus.NEW.value:

                            order_id = str(order['clientAlgoId'])
                            tp = Decimal(order['triggerPrice'])

                            match (order['positionSide'], order['side']):
                                case (PositionSide.LONG.value, Side.SELL.value):
                                    match order['orderType']:
                                        case AlgoOrderType.STOP_MARKET.value:
                                            if showLog:
                                                logger.info(f"[LONG-OPEN-ORDER] Stop-Market price: {tp}")
                                            self.positions.long_stop_loss = tp
                                            self.positions.long_stop_loss_order_id = order_id

                                        case AlgoOrderType.TAKE_PROFIT_MARKET.value:
                                            if showLog:
                                                logger.info(f"[LONG-OPEN-ORDER] Take-Profit price: {tp}")
                                            self.positions.long_take_profit = tp
                                            self.positions.long_take_profit_order_id = order_id

                                case (PositionSide.SHORT.value, Side.BUY.value):
                                    match order['orderType']:
                                        case AlgoOrderType.STOP_MARKET.value:
                                            if showLog:
                                                logger.info(f"[SHORT-OPEN-ORDER] Stop-Market price: {tp}")
                                            self.positions.short_stop_loss = tp
                                            self.positions.short_stop_loss_order_id = order_id

                                        case AlgoOrderType.TAKE_PROFIT_MARKET.value:
                                            if showLog:
                                                logger.info(f"[SHORT-OPEN-ORDER] Take-Profit price: {tp}")
                                            self.positions.short_take_profit = tp
                                            self.positions.short_take_profit_order_id = order_id
                        case _:
                                logger.warning(f"Unknown algo order status. {order['algoStatus']}")

            # self.positions.long_fee, self.positions.short_fee = self.client.futures_trade_fees(symbol)

        except Exception as e:
            logger.error(f"Failed to update position: {e}", exc_info=True)

    def get_analysis_data(self) -> dict:
        """
        현재 보유한 deque 데이터를 분석용 Numpy 배열로 변환하여 반환합니다.
        (Shared Memory 효과를 위해 여기서 한 번만 변환)
        """
        return {
            'opens': np.array(self.open_prices, dtype=np.float64),
            'highs': np.array(self.high_prices, dtype=np.float64),
            'lows': np.array(self.low_prices, dtype=np.float64),
            'closes': np.array(self.close_prices, dtype=np.float64)
        }