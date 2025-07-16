# binance_ws_manager.py
from binance import ThreadedWebsocketManager
from config.msg import logger
import time
import threading

class WebSocketManager:
    def __init__(self, api_key: str, api_secret: str, kline_interval: str, symbol: str, message_handler):
        self.twm = ThreadedWebsocketManager(api_key, api_secret)
        self.kline_interval = kline_interval
        self.symbol = symbol.lower()
        self.message_handler = message_handler
        self.is_connected_flag = False
        self.last_received_time = None
        self._connection_check_thread = None

    def _update_connection_status(self):
        self.is_connected_flag = True
        self.last_received_time = time.time()

    def _wrap_message_handler(self, msg):
        self._update_connection_status()
        self.message_handler(msg)

    def start(self):
        self.twm.start()
        # logger.info("Starting WebSocket Manager...")

        self.twm.start_futures_user_socket(self._wrap_message_handler)
        self.twm.start_futures_multiplex_socket(self._wrap_message_handler,
                                                  [f'{self.symbol}@kline_{self.kline_interval}'])

        self._connection_check_thread = threading.Thread(target=self._monitor_connection)
        self._connection_check_thread.daemon = True # 메인 스레드 종료 시 함께 종료
        self._connection_check_thread.start()

    def _monitor_connection(self):
        last_reconnect_attempt = 0
        RECONNECT_INTERVAL = 30 # 재연결 시도 간격 (초)

        while True:
            time.sleep(1) # 1초마다 확인

            # 연결 플래그 확인
            if not self.is_connected_flag:
                logger.warning("Connection Status: Disconnected or Waiting to reconnect...")
                if time.time() - last_reconnect_attempt > RECONNECT_INTERVAL:
                    logger.info("Attempting to reconnect WebSocket...")
                    self.stop() # 기존 연결 정리
                    self.start() # 다시 시작하여 재연결 시도
                    last_reconnect_attempt = time.time()
                continue # 재연결 시도했으니 다음 루프

            # 메시지 수신 시간 확인
            if self.last_received_time is not None and (time.time() - self.last_received_time > 60):
                logger.warning("Warning: No data received for more than 60 seconds. Possible connection issues. Initiating reconnect.")
                self.is_connected_flag = False # 연결 끊김으로 설정하여 재연결 트리거
                last_reconnect_attempt = time.time() # 즉시 재연결 시도 예약

            # 연결이 정상일 경우 last_reconnect_attempt 초기화
            if self.is_connected_flag and self.last_received_time is not None and (time.time() - self.last_received_time <= 60):
                last_reconnect_attempt = time.time() # 다음 재연결 시도 시간을 현재로 업데이트

    def stop(self):
        self.twm.stop()
        logger.info("Closing WebSocket Manager...")
        if self._connection_check_thread and self._connection_check_thread.is_alive():
            # 스레드 종료 신호를 보낼 수 있으나, daemon 스레드이므로 강제 종료될 것입니다.
            # 더 안전한 종료를 위해 Event 객체 등을 사용할 수 있습니다.
            pass