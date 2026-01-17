import sys, queue
from binance.client import Client

from src.api.client import BinanceClient
from src.api.binance_setup_manager import BinanceSetupManager
from src.shared.msg import get_logger

from src.core.websocket_threaded import WebSocketThreadManager
from src.core.market_data import MarketDataProcessor
from src.core.trading_engine import TradingEngine
from src.core.order_manager import OrderManager

from binance.exceptions import BinanceAPIException, BinanceRequestException


logger = get_logger("CLIENT_MANAGER")

class ClientManager:

    @staticmethod
    def get_key():
        key_file = sys.argv[1] if len(sys.argv) > 1 else 'binance.key'
        with open(key_file, 'r') as f:
            lines = f.readlines()
            access = lines[0].strip()
            secret = lines[1].strip()
            return access, secret

    @staticmethod
    def initialize_clients(symbol, kline_interval, leverage, stop_event):
        try:
            access, secret = ClientManager.get_key()
            client = Client(access, secret)
            binance_client = BinanceClient(client=client)
            binance_client.set_stop_event(stop_event) # BinanceClient에 전달 (client.py의 재시도 중단용)
            
            setup_data = BinanceSetupManager(binance_client, symbol, leverage, kline_interval)._setup_initial_state()
            market_data = MarketDataProcessor(binance_client, symbol, kline_interval, setup_data)
            order_manager = OrderManager(binance_client, setup_data, market_data, symbol)
            trading_engine = TradingEngine(
                binance_client=binance_client,
                market_data=market_data,
                order_manager=order_manager,
                symbol=symbol,
                leverage=leverage,
                kline_interval=kline_interval,
                setup_data=setup_data
            )
            # Websocket
            kline_queue = queue.Queue()
            user_queue = queue.Queue()
            ws_manager = WebSocketThreadManager(
                api_key=access,
                api_secret=secret,
                symbol=symbol,
                kline_interval=kline_interval,
                stream_handler=None,
                user_handler=None,
                kline_queue=kline_queue,
                user_queue=user_queue,
                stop_event=stop_event # WebSocketThreadManager에 전달 (websocket_threaded.py의 워치독 중단용)
            )
            return (market_data, trading_engine, ws_manager, kline_queue, user_queue)

        except (BinanceAPIException, BinanceRequestException, FileNotFoundError, IndexError) as e:
            logger.critical(f"Fatal error: An unexpected error occurred during client initialization: {e}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logger.critical(f"Critical error: Failed to initialize client due to an unknown cause: {e}", exc_info=True)
            sys.exit(1)