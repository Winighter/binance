import time, threading, queue, signal, logging
import settings as app_config
from src.shared.msg import DiscordHandler
from src.strategy import *
from src.shared import *
from src.core import *
from src.api import *


logger = DiscordHandler.get_logger("MAIN")


class Binance:

    def __init__(self):
        logger.info("ROBOT STATUS: Initializing Binance trading system...")
        self.symbol = app_config.SYMBOL
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
        setup_manager = BinanceSetupManager(
            self.symbol, self.binance_client, self.trading_manager,
            app_config.LEVERAGE, app_config.KLINE_INTERVAL
            )
        open_prices, high_prices, low_prices, close_prices, available_usdt = setup_manager._setup_initial_state()

        self.trading_engine = TradingEngine(
            trading_manager=self.trading_manager,
            binance_client=self.binance_client,
            indicators=self.indicators,
            positions=self.positions,
            strategy=self.strategy,
            symbol=self.symbol,
            low_prices=low_prices,
            open_prices=open_prices,
            high_prices=high_prices,
            close_prices=close_prices,
            available_usdt=available_usdt,
            long_atr_stop_loss=None,
            short_atr_stop_loss=None,
            model_filter_threshold=0.9
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
            if hasattr(self, 'discord_handler'):
                self.discord_handler.stop()
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