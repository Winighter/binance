import time, threading, signal, logging
from src.shared.msg import *
from src.core import *
from settings import *
from src.core.client_manager import ClientManager
from src.shared.enums import KlineInterval


logger = get_logger("MAIN")


class Binance:

    def __init__(self):
        self.symbol = SYMBOL
        self.leverage = LEVERAGE
        kline_intervals = KLINE_INTERVALS # [LTF, MTF, HTF]

        interval_objs = []
        for interval in kline_intervals:
            if interval is None:
                interval_objs.append(None)
                continue

            # 객체면 그대로, 문자열이면 get_by_code로 변환
            obj = KlineInterval.get_by_code(interval)
            if obj is None:
                raise ValueError(f"Invalid interval found in list: {interval}")
            interval_objs.append(obj)

        if interval_objs[0] is None:
            raise ValueError("LTF cannot be None.")

        if interval_objs[1] is None:
            raise ValueError("MTF cannot be None.")

        if ENABLE_DISCORD_ALERTS and not ENABLE_SIMULATION:
            stela_msg("Stela Started", f"{self.symbol} {self.leverage}x", MsgColorCode.BLUE)

        self.last_sync_time = time.time()
        self._stop_event = threading.Event()

        self.market_data, self.trading_engine, self.ws_manager, self.kline_queue, self.user_queue = ClientManager.initialize_clients(self.symbol, interval_objs, self.leverage, self._stop_event, ENABLE_SIMULATION)

        if not ENABLE_SIMULATION:
            self.trading_engine.kline_queue = self.kline_queue
            self.ws_manager.process_stream_handler = self.trading_engine.process_stream_data
            self.ws_manager.process_user_handler = self.trading_engine.process_user_data

    def run(self):
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        try:
            if not ENABLE_SIMULATION:
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

            logger.info("ROBOT STATUS: Cleanup complete. Program terminated.")

    def _handle_shutdown(self, signal, frame):
        logger.info("ROBOT STATUS: Shutdown signal received. Gracefully shutting down...")
        self._stop_event.set()

if __name__ == '__main__':
    discord_handler = DiscordHandler()
    discord_handler.setLevel(logging.ERROR)
    logger.addHandler(discord_handler)

    bot = Binance()
    bot.run()