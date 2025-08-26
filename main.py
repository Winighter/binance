import time, threading, queue, signal, logging
import settings as app_config
from src.shared.msg import *
from src.strategy import *
from src.shared import *
from src.core import *
from src.api import *


logger = get_logger("MAIN")


class Binance:

    def __init__(self):
        logger.info("ROBOT STATUS: Initializing Binance trading system...")
        self.symbol = app_config.SYMBOL
        # self.data_fetch_lock = threading.Lock()
        self._stop_event = threading.Event()

        self.positions = PositionState()
        self.indicators = Indicators()
        self.strategy = SupertrendStrategy()

        client_manager = ClientManager(
            app_config=app_config,
            kline_handler=None,
            user_handler=None
            )

        self.binance_client, self.trading_manager, self.ws_manager, self.kline_queue, self.user_queue = client_manager.initialize_clients()
        setup_manager = BinanceSetupManager(self.symbol, self.binance_client, self.trading_manager)
        high_prices, low_prices, close_prices, available_usdt = setup_manager._setup_initial_state()

        self.trading_engine = TradingEngine(
            binance_client=self.binance_client,
            trading_manager=self.trading_manager,
            positions=self.positions,
            indicators=self.indicators,
            strategy=self.strategy,
            symbol=self.symbol,
            available_usdt=available_usdt,
            high_prices=high_prices,
            low_prices=low_prices,
            close_prices=close_prices
        )

        self.ws_manager.stream_handler = self.trading_engine.process_stream_data
        self.ws_manager.user_handler = self.trading_engine.process_user_data

        logger.info("ROBOT STATUS: Binance trading system has been initialized.")

    def run(self):

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        processor_thread = threading.Thread(target=self._process_queues, daemon=True)
        processor_thread.start()

        try:
            self.ws_manager.start()

            while not self._stop_event.is_set():
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt. Setting stop event...")
            self._stop_event.set()
            
        finally:
            logger.info("ROBOT STATUS: Main loop has stopped. Cleaning up connections...")
            self.ws_manager.stop()
            processor_thread.join()
            logger.info("ROBOT STATUS: Cleanup complete. Program terminated.")

    def _process_queues(self):
        try:
            while not self._stop_event.is_set():
                try:
                    user_data = self.user_queue.get(timeout=0.1)
                    self.trading_engine.process_user_data(user_data)
                except queue.Empty:
                    pass

                try:
                    kline_data = self.kline_queue.get(timeout=0.1)
                    self.trading_engine.process_stream_data(kline_data)
                except queue.Empty:
                    pass

                if self.kline_queue.empty() and self.user_queue.empty():
                    time.sleep(0.01)

        except Exception as e:
            logger.critical(f"An unrecoverable error occurred in the main processing thread: {e}", exc_info=True)
            self._stop_event.set()

    def _handle_shutdown(self, signal, frame):
        logger.info("ROBOT STATUS: Shutdown signal received. Gracefully shutting down...")
        self._stop_event.set()

if __name__ == '__main__':
    discord_handler = DiscordHandler()
    discord_handler.setLevel(logging.ERROR)
    logger.addHandler(discord_handler)

    bot = Binance()
    bot.run()