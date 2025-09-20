import sys
import queue
from typing import Tuple
from ..shared.msg import get_logger
from binance.client import Client as BinanceOfficialClient
from binance.exceptions import BinanceAPIException, BinanceRequestException
from ..api.client import BinanceClient
from ..trading.futures_trading_manager import FuturesTradingManager
from ..core.websocket_threaded import WebSocketThreadManager

logger = get_logger("CLIENT_MANAGER")

class ClientManager:
    def __init__(self, app_config, kline_handler, user_handler):
        self.app_config = app_config
        self.symbol = app_config.SYMBOL
        self.user_handler = user_handler
        self.kline_handler = kline_handler

    @staticmethod
    def get_key():
        key_file = sys.argv[1] if len(sys.argv) > 1 else 'binance.key'
        with open(key_file, 'r') as f:
            lines = f.readlines()
            access_key = lines[0].strip()
            secret_key = lines[1].strip()
        return access_key, secret_key

    def initialize_clients(self) -> Tuple:
        try:
            access, secret = self.get_key()
            official_client = BinanceOfficialClient(access, secret)
            binance_client = BinanceClient(client=official_client)
            trading_manager = FuturesTradingManager(
                binance_client=binance_client,
                default_position_rate=self.app_config.POSITION_RATE
            )
            kline_queue = queue.Queue()
            user_queue = queue.Queue()
            ws_manager = WebSocketThreadManager(
                api_key=access,
                api_secret=secret,
                symbol=self.symbol,
                kline_interval=self.app_config.KLINE_INTERVAL,
                stream_handler=self.kline_handler,
                user_handler=self.user_handler,
                kline_queue=kline_queue,
                user_queue=user_queue,
            )
            logger.info("All clients and queues initialized.")
            return (binance_client, trading_manager, ws_manager, kline_queue, user_queue)
            
        except (BinanceAPIException, BinanceRequestException, FileNotFoundError, IndexError) as e:
            logger.critical(f"Fatal error: An unexpected error occurred during client initialization: {e}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logger.critical(f"Critical error: Failed to initialize client due to an unknown cause: {e}", exc_info=True)
            sys.exit(1)