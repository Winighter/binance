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

        if ENABLE_DISCORD_ALERTS:
            stela_msg("Stela Started", f"{SYMBOL} {self.leverage}x", MsgColorCode.BLUE)

        if isinstance(KLINE_INTERVAL, KlineInterval):
            interval_obj = KLINE_INTERVAL
        else:
            interval_obj = KlineInterval.get_by_code(KLINE_INTERVAL)
        if interval_obj is None:
            raise ValueError(f"Invalid interval in settings: {KLINE_INTERVAL}")

        self.last_sync_time = time.time()
        self._stop_event = threading.Event()

        self.market_data, self.trading_engine, self.ws_manager, self.kline_queue, self.user_queue = ClientManager.initialize_clients(self.symbol, interval_obj, self.leverage, self._stop_event)

        self.ws_manager.stream_handler = self.trading_engine.process_stream_data
        self.ws_manager.user_handler = self.trading_engine.process_user_data

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
                    kline_data = self.kline_queue.get(timeout=0.1)
                    self.trading_engine.process_stream_data(kline_data)
                except queue.Empty:
                    pass

                try:
                    user_data = self.user_queue.get(timeout=0.1)
                    self.trading_engine.process_user_data(user_data)
                except queue.Empty:
                    pass

                now = time.time()
                # 주문 부분 체결 수량 1분마다 동기화
                if now - self.last_sync_time > POSITION_SYNC_INTERVAL:
                    self.last_sync_time = now
                    try:
                        self.market_data.update_position(self.symbol)
                        # [중요] 동기화 성공/실패 여부와 상관없이 시간을 업데이트하여 무한 반복 방지
                    except Exception as e:
                        logger.error(f"Sync error: {e}")# 에러 나도 일단 시간은 뒤로 밀어야 함

                # 3. CPU 과부하 방지
                time.sleep(0.1)

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