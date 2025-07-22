# binance_ws_manager.py
from binance import ThreadedWebsocketManager
from config.msg import logger
# websocket.py
# ...
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
        # logger.debug("Connection status updated: connected, last received at %s", self.last_received_time) # 디버그 로깅

    def _wrap_message_handler(self, msg):
        self._update_connection_status()
        self.message_handler(msg)

    def start(self):
        self.twm.start()
        # logger.info("Starting WebSocket Manager...")

        self.twm.start_futures_user_socket(self._wrap_message_handler)
        self.twm.start_futures_multiplex_socket(self._wrap_message_handler,
                                                  [f'{self.symbol}@kline_{self.kline_interval}'])

        self._stop_event.clear() # 이벤트 초기화
        self._connection_check_thread = threading.Thread(target=self._monitor_connection)
        self._connection_check_thread.daemon = True
        self._connection_check_thread.start()
        # logger.info("WebSocket Manager started and connection monitoring initiated.")

    def _monitor_connection(self):
        last_reconnect_attempt = 0
        RECONNECT_INTERVAL = 30 # 재연결 시도 간격 (초)
        NO_DATA_TIMEOUT = 60 # 데이터 수신 없음 감지 시간 (초)

        while not self._stop_event.is_set(): # 종료 이벤트가 설정되지 않은 동안 반복
            time.sleep(1) # 1초마다 확인

            current_time = time.time()

            # 연결 플래그 및 데이터 수신 시간 확인
            if not self.is_connected_flag or (self.last_received_time is not None and (current_time - self.last_received_time > NO_DATA_TIMEOUT)):
                if not self.is_connected_flag:
                    logger.warning("Connection Status: Disconnected. Attempting reconnect.")
                else:
                    logger.warning("Warning: No data received for more than %d seconds. Possible connection issues. Initiating reconnect.", NO_DATA_TIMEOUT)

                if current_time - last_reconnect_attempt > RECONNECT_INTERVAL:
                    logger.info("Attempting to reconnect WebSocket...")
                    self.stop() # 기존 연결 정리
                    # stop() 호출 후 ThreadedWebsocketManager가 완전히 정리될 시간을 줍니다.
                    time.sleep(5) # 재연결 전 잠시 대기
                    self.start() # 다시 시작하여 재연결 시도
                    last_reconnect_attempt = current_time
                    self.is_connected_flag = False # 재연결 시도 후 초기화
                else:
                    logger.debug("Reconnection attempt throttled. Waiting for %d seconds.", RECONNECT_INTERVAL - (current_time - last_reconnect_attempt))
            else:
                # 연결이 정상일 경우 last_reconnect_attempt 초기화는 필요 없음.
                # 연결이 끊겼을 때만 재연결 시도 시간을 업데이트
                pass

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