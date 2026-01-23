import time, threading, queue, os
from ..shared.msg import get_logger, stela_msg
import concurrent.futures
from ..shared.enums import WebSocketState, MsgColorCode
from binance import ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException, BinanceRequestException
from ..config import *
from ..shared.errors import ErrorManager, BinanceRetryableError, BinanceClientException
from ..shared.typings import *


logger = get_logger("WEBSOCKET_MANAGER")

class WebSocketConnectionError(Exception):
    """Base exception for general WebSocket connection issues."""
    pass

class AuthenticationError(WebSocketConnectionError):
    """Exception for API key/secret authentication failures."""
    pass

class ReconnectionExhaustedError(WebSocketConnectionError):
    """Exception for exceeding the maximum number of reconnection attempts."""
    pass

class WebSocketThreadManager:

    def __init__(self, api_key: str, api_secret: str, symbol: str, kline_interval, kline_queue, user_queue, stop_event):
        self._state = WebSocketState.DISCONNECTED
        self._lock = threading.Lock()
        self._reconnect_attempts = 0

        self.kline_queue = kline_queue
        self.user_queue = user_queue

        with self._lock:
            self._last_data_received_time = time.time()
        self._update_queue = queue.Queue()
        self._is_monitoring_active = False
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS)
        self._stop_event = stop_event
        
        self.symbol = symbol
        interval_str = kline_interval.code if hasattr(kline_interval, 'code') else kline_interval
        self.kline_interval = interval_str
        self.is_running = False

        self.twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret)

    def _start_data_update_thread(self):
        if not hasattr(self, '_data_update_thread') or not self._data_update_thread.is_alive():
            self._data_update_thread = threading.Thread(target=self._update_last_data_time, daemon=True)
            self._data_update_thread.start()
            logger.info("Data update thread started.")

    def _update_last_data_time(self):
        while not self._stop_event.is_set():
            try:
                self._update_queue.get(timeout=1)
                with self._lock:
                    self._last_data_received_time = time.time()
                self._update_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in data update thread: {e}")

    def run(self):
        """
        웹소켓 연결을 시작하고 재연결을 시도합니다.
        """
        logger.info(f"Starting WebSocket Manager for {self.symbol}...")
        while self._state != WebSocketState.FATAL_ERROR:
            try:
                # 연결 시작
                self._connect()
                
                # 연결 성공 시, 재연결 시도 횟수 초기화
                self._reconnect_attempts = 0
                
                # 연결 모니터링
                self._monitor_connection()

            except ReconnectionExhaustedError:
                logger.critical("Maximum reconnection attempts exhausted. Transitioning to FATAL_ERROR state.")
                self._transition_to_state(WebSocketState.FATAL_ERROR)
            except Exception as e:
                logger.critical(f"An unhandled fatal error occurred: {e}", exc_info=True)
                self._transition_to_state(WebSocketState.FATAL_ERROR)

        logger.critical("WebSocket Manager is in FATAL_ERROR state. Shutting down.")

    def start(self):
        with self._lock:
            if self._state in [WebSocketState.DISCONNECTED, WebSocketState.FATAL_ERROR]:
                try:
                    self._start_threaded_websocket_manager()
                    self._start_monitoring_thread()
                    self._start_data_update_thread()
                except (AuthenticationError, ReconnectionExhaustedError) as e:
                    raise e
            else:
                logger.warning("WebSocket manager is already running or connecting.")

    def stop(self):
        with self. _lock:
            if self.is_running:
                logger.info("Stopping all WebSocket connections...")
                self.twm.stop()

                self._executor.shutdown(wait=True)

                self._stop_event.set()
                self._transition_to_state(WebSocketState.DISCONNECTED)
                self.is_running = False
                self._is_monitoring_active = False
                logger.info("WebSocket connections stopped.")
            else:
                logger.info("WebSocket manager is not running.")

    def _transition_to_state(self, new_state: WebSocketState):
        with self._lock:
            if self._state != new_state:
                logger.info(f"WebSocket state changed from {self._state.value} to {new_state.value}")
                self._state = new_state

    def _start_threaded_websocket_manager(self, showLog:bool = True):
        try:
            if not self.twm.is_alive():
                self.twm.start()

            self.twm.start_futures_user_socket(callback=self.process_user_handler)
            kline_stream = f'{self.symbol.lower()}@kline_{self.kline_interval}'
            streams = [kline_stream]

            if showLog:
                logger.info(f"Starting multiplex streams: {streams}")

            self.twm.start_futures_multiplex_socket(
                callback=self.process_stream_handler,
                streams=streams
            )
            self._transition_to_state(WebSocketState.CONNECTED)
            self.is_running = True
            
        except (BinanceAPIException, BinanceRequestException, RuntimeError) as e:
            logger.critical(f"Fatal error during WebSocket startup: {e}", exc_info=True)
            self._transition_to_state(WebSocketState.FATAL_ERROR)
            self._handle_reconnection_error(e)
            raise
        except Exception as e:
            logger.critical(f"An unexpected fatal error occurred during WebSocket startup: {e}", exc_info=True)
            self._transition_to_state(WebSocketState.FATAL_ERROR)
            raise

    def _monitor_connection(self):
        while not self._stop_event.is_set():
            time.sleep(MONITOR_INTERVAL_SECONDS)
            with self._lock:
                elapsed_time = time.time() - self._last_data_received_time

                if elapsed_time > NO_DATA_TIMEOUT:
                    # [중요] 종료 중일 때는 강제 종료(os._exit)를 실행하지 않음
                    if self._stop_event.is_set():
                        logger.info("Shutdown signal detected. Skipping watchdog termination.")
                        break

                    stela_msg(
                        title="⚠️ WebSocket Timeout Detected",
                        description=f"No data received for {NO_DATA_TIMEOUT}s.\nPM2 will restart the bot immediately.",
                        color=MsgColorCode.BLACK
                    )
                    
                    logger.critical(
                        f"🚨 [WATCHDOG] No data received for {elapsed_time:.1f}s! "
                        "Terminating process for a clean PM2 restart."
                    )
                    
                    time.sleep(0.5) # 로그 저장 시간을 벌어줌
                    os._exit(1)

    def _handle_reconnection(self):
        """
        재연결 로직을 수행합니다.
        """
        while self._reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            self._reconnect_attempts += 1
            reconnect_delay = INITIAL_RECONNECT_DELAY * (BACKOFF_FACTOR ** (self._reconnect_attempts - 1))
            logger.info(f"Attempting reconnection... Attempt {self._reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}. Waiting for {reconnect_delay:.2f} seconds.")
            time.sleep(reconnect_delay)
            
            try:
                self._start_threaded_websocket_manager()
                stela_msg(
                title="✅ Reconnection Successful",
                description=f"Successfully reconnected to {self.symbol} after {self._reconnect_attempts} attempts.",
                color=MsgColorCode.GREEN
                    )
                logger.info("Reconnection successful.")
                self._reconnect_attempts = 0
                self._transition_to_state(WebSocketState.CONNECTED)
                return
            except (BinanceAPIException, BinanceRequestException, WebSocketConnectionError) as e:
                logger.error(f"Reconnection attempt failed with error: {e}", exc_info=True)
                self._handle_reconnection_error(e)
            except Exception as e:
                logger.critical(f"Reconnection attempt failed with unexpected error: {e}", exc_info=True)
                self._transition_to_state(WebSocketState.FATAL_ERROR)
                raise
        
        logger.critical(f"Maximum reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded.")
        self._transition_to_state(WebSocketState.FATAL_ERROR)
        raise ReconnectionExhaustedError("Maximum reconnection attempts exceeded. Exiting program.")

    def _is_api_key_invalid(self, e):
        return isinstance(e, BinanceAPIException) and e.code == -2015

    def _start_monitoring_thread(self):
        if not self._is_monitoring_active:
            monitor_thread = threading.Thread(target=self._monitor_connection, daemon=True)
            monitor_thread.start()
            self._is_monitoring_active = True
    
    def _handle_reconnection_error(self, e):
        # 치명적 오류 처리
        if self._is_api_key_invalid(e):
            logger.critical("Fatal authentication error: The API key or secret is invalid.")
            self._transition_to_state(WebSocketState.FATAL_ERROR)
            raise AuthenticationError("The API key or secret is invalid.")

        if isinstance(e, BinanceAPIException):
            error_code = e.code

            # 2. ErrorManager를 통한 성격 분류 및 메시지 획득
            exc_class = ErrorManager.get_exception_class(error_code)
            friendly_msg = ErrorManager.get_friendly_message(error_code, str(e))

            # 일시적인 오류는 재연결을 시도합니다.
            if exc_class == BinanceRetryableError or isinstance(e, BinanceRequestException):
                stela_msg(
                    title="📡 [DEFCON 3] WebSocket Reconnecting",
                    description=f"Temporary API Error ({error_code}). Retrying connection...",
                    color=MsgColorCode.ORANGE
                )
                logger.warning(f"Temporary API error: {friendly_msg} (Error code: {error_code}). Will retry.")
             # 그 외의 모든 API 예외는 치명적인 것으로 간주합니다.
            else:
                stela_msg(
                    title="🚨 [DEFCON 1] WebSocket Connection Failed",
                    description=f"Fatal API Error: {e.message}. Killing process.",
                    color=MsgColorCode.RED
                )
                logger.critical(f"Fatal API error: {e.message} (Error code: {error_code}). Exiting.", exc_info=True)
                self._transition_to_state(WebSocketState.FATAL_ERROR)
                raise BinanceClientException(message=e.message, code=e.code)

        elif isinstance(e, BinanceRequestException):
            logger.warning("Network error. Will retry.")
        else:
            logger.error(f"Unexpected reconnection error: {e}", exc_info=True)
            self._transition_to_state(WebSocketState.FATAL_ERROR)
            raise WebSocketConnectionError(f"Unexpected reconnection error: {e}")

    def process_stream_handler(self, data):
        self.kline_queue.put(data)
        self._update_queue.put(True)

    def process_user_handler(self, data):
        self.user_queue.put(data)
        self._update_queue.put(True)