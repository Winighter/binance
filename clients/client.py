# binance_client.py
from binance.client import Client
import config.config as app_config
from config.msg import logger

class BinanceClient:
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret)
        self.symbol = app_config.SYMBOL
        # logger.info("BinanceClient initialized.")

    def change_leverage(self, symbol: str, leverage: int):
        try:
            response = self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            # logger.info(f"Leverage setting complete: {response}")
            return response
        except Exception as e:
            logger.error(f"Leverage setting failed: {e}")
            return None

    def get_position_mode(self):
        try:
            response = self.client.futures_get_position_mode()
            # logger.info(f"get position mode complete: {response}")
            return response
        except Exception as e:
            logger.error(f"get position mode failed: {e}")
            return None

    def change_position_mode(self, dual_side_position: str):
        try:
            response = self.client.futures_change_position_mode(dualSidePosition=dual_side_position)
            # logger.info(f"position mode changed complete: {response}")
            return response
        except Exception as e:
            logger.error(f"position mode changed failed: {e}")
            return None

    def get_account_balance(self):
        try:
            balance_info = self.client.futures_account_balance()
            return balance_info
        except Exception as e:
            logger.error(f"Balance inquiry failed: {e}")
            return None

    def get_position_information(self, symbol: str):
        try:
            position_info = self.client.futures_position_information(symbol=symbol)
            return position_info
        except Exception as e:
            logger.error(f"Position information inquiry failed: {e}")
            return None

    def create_market_order(self, symbol: str, side: str, positionSide:str, quantity: float):
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                positionSide=positionSide,
                quantity=quantity
            )
            # logger.info(f"시장가 주문 성공: {order}")
            return order
        except Exception as e:
            logger.error(f"Market Order Failed: {e}")
            return None

    def get_klines(self, symbol: str, interval: str, limit: int = app_config.DEFAULT_KLINE_LIMIT):
        try:
            klines = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            return klines
        except Exception as e:
            logger.error(f"Candle data lookup failed: {e}")
            return None

    def get_orderbook_ticker(self, symbol: str):
        try:
            ticker = self.client.futures_orderbook_ticker(symbol=symbol)
            return ticker
        except Exception as e:
            logger.error(f"Orderbook Ticker Lookup Failed: {e}")
            return None