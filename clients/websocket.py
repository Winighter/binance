from binance import ThreadedWebsocketManager
from config.msg import logger
import threading
import time

class WebSocketManager:
    def __init__(self, api_key: str, api_secret: str, kline_interval: str, symbol: str, message_handler):
        self.twm = ThreadedWebsocketManager(api_key, api_secret)
        self.kline_interval = kline_interval
        self.symbol = symbol.lower()
        self.message_handler = message_handler
        self.is_connected_flag = False
        self.last_received_time = None
        self._connection_check_thread = None
        self._stop_event = threading.Event() # 스레드 종료를 위한 이벤트

    def _update_connection_status(self):
        self.is_connected_flag = True
        self.last_received_time = time.time()

    def _wrap_message_handler(self, msg):
        self._update_connection_status()
        self.message_handler(msg)

    def start(self):
        self._stop_event.clear()
        self.twm.start()
        self.twm.start_futures_user_socket(self._wrap_message_handler)
        self.twm.start_futures_multiplex_socket(self._wrap_message_handler, [f'{self.symbol}@kline_{self.kline_interval}'])
        self._connection_check_thread = threading.Thread(target=self._monitor_connection)
        self._connection_check_thread.daemon = True
        self._connection_check_thread.start()

    def _monitor_connection(self):
        last_reconnect_attempt = 0
        RECONNECT_INTERVAL = 30
        NO_DATA_TIMEOUT = 60

        while not self._stop_event.is_set():
            time.sleep(1)
            current_time = time.time()
            # Check for disconnection or no data received for a long time
            if not self.is_connected_flag or (self.last_received_time and (current_time - self.last_received_time > NO_DATA_TIMEOUT)):
                if current_time - last_reconnect_attempt > RECONNECT_INTERVAL:
                    logger.warning("No data received or disconnected. Attempting reconnect.")
                    self.stop()
                    time.sleep(5)
                    self.start()
                    last_reconnect_attempt = current_time
                    break
                else:
                    logger.debug("Reconnection attempt throttled. Waiting...")

    def stop(self):
        self._stop_event.set() # 종료 이벤트 설정
        if self._connection_check_thread and self._connection_check_thread.is_alive():
            self._connection_check_thread.join(timeout=5) # 스레드가 종료될 때까지 최대 5초 대기
            if self._connection_check_thread.is_alive():
                logger.warning("Connection check thread did not terminate gracefully.")
        self.twm.stop()
        logger.info("Closing WebSocket Manager...")
        self.is_connected_flag = False
        self.last_received_time = None