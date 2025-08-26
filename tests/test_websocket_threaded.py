import pytest
import time
import queue
from ..src.core.websocket_threaded import (
    WebSocketThreadManager,
    WebSocketConnectionError,
    AuthenticationError,
    ReconnectionExhaustedError,
)
from ..src.shared.enums import WebSocketState
from unittest.mock import MagicMock, patch
from binance.exceptions import BinanceAPIException, BinanceRequestException
from ..src.shared.errors import BinanceClientException, INVALID_TIMESTAMP_CODE, RATE_LIMIT_EXCEEDED_CODE, UNKNOWN_ERROR_CODE

# 테스트에 사용될 가상 환경 변수 설정
@pytest.fixture(autouse=True)
def setup_test_env():
    # WebSocketThreadManager의 설정값을 재정의합니다.
    # 테스트에 필요한 설정값을 여기서 조정할 수 있습니다.
    with patch('clients.settings.MAX_RECONNECT_ATTEMPTS', 3), \
         patch('clients.settings.INITIAL_RECONNECT_DELAY', 0.01), \
         patch('clients.settings.BACKOFF_FACTOR', 1.5), \
         patch('clients.settings.NO_DATA_TIMEOUT', 1):
        yield

# WebSocketThreadManager 인스턴스를 생성하는 픽스처
@pytest.fixture
def ws_manager_instance():
    # MagicMock 객체를 생성하여 실제 핸들러 대신 사용합니다.
    kline_handler = MagicMock()
    user_socket_handler = MagicMock()
    kline_queue = queue.Queue()
    user_queue = queue.Queue()
    
    manager = WebSocketThreadManager(
        api_key='test_key',
        api_secret='test_secret',
        symbol='BTCUSDT',
        kline_interval='1m',
        stream_handler=kline_handler,
        user_handler=user_socket_handler,
        kline_queue=kline_queue,
        user_queue=user_queue
    )
    return manager, kline_handler, user_socket_handler, kline_queue, user_queue

def test_initial_state(ws_manager_instance):
    """
    WebSocketThreadManager의 초기 상태를 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    assert ws_manager._state == WebSocketState.DISCONNECTED
    assert ws_manager.is_running == False

@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_start_and_stop(MockTWM, ws_manager_instance):
    """
    매니저의 시작 및 중지 로직을 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # 시작 테스트
    ws_manager.start()
    assert ws_manager._state == WebSocketState.CONNECTED
    assert ws_manager.is_running == True
    MockTWM.return_value.start.assert_called_once()
    
    # 중지 테스트
    ws_manager.stop()
    assert ws_manager._state == WebSocketState.DISCONNECTED
    assert ws_manager.is_running == False
    MockTWM.return_value.stop.assert_called_once()

@patch('clients.websocket_threaded.WebSocketThreadManager._handle_reconnection')
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_monitor_connection_reconnects_on_timeout(MockTWM, MockHandleReconnection, ws_manager_instance):
    """
    데이터 수신 타임아웃 발생 시 재연결을 시도하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # 웹소켓 매니저 시작
    ws_manager.start()
    
    # 마지막 데이터 수신 시간을 과거로 설정하여 타임아웃을 유도
    ws_manager._last_data_received_time = time.time() - 100 
    
    # 모니터링 스레드 실행
    ws_manager._monitor_connection()
    
    # 재연결 로직이 한 번 호출되었는지 확인
    MockHandleReconnection.assert_called_once()
    
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_queue_processing(MockTWM, ws_manager_instance):
    """
    웹소켓 데이터가 큐에 올바르게 추가되는지 테스트합니다.
    """
    ws_manager, _, _, kline_queue, _ = ws_manager_instance

    # 가상 데이터 생성
    test_data = {'stream': 'btcusdt@kline_1m', 'data': {'k': {'T': 123456}}}
    
    # 데이터를 처리하는 메서드 호출
    ws_manager.process_stream_handler(test_data)
    
    # 데이터가 큐에 올바르게 들어갔는지 확인
    assert not kline_queue.empty()
    assert kline_queue.get() == test_data

@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_invalid_api_key_error(MockTWM, ws_manager_instance):
    """
    잘못된 API 키/시크릿으로 인한 인증 오류를 올바르게 처리하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # start() 메서드가 BinanceAPIException(-2015)을 발생시키도록 mock 설정
    MockTWM.return_value.start.side_effect = BinanceAPIException(
        message='API-key format invalid.', code=-2015
    )

    with pytest.raises(AuthenticationError):
        ws_manager.start()
    
    assert ws_manager._state == WebSocketState.FATAL_ERROR

@patch('clients.websocket_threaded.WebSocketThreadManager._handle_reconnection')
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_reconnection_exhausted_error(MockTWM, MockHandleReconnection, ws_manager_instance):
    """
    최대 재연결 시도 횟수를 초과했을 때 ReconnectionExhaustedError를 발생하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # _handle_reconnection 메서드가 ReconnectionExhaustedError를 발생시키도록 mock 설정
    MockHandleReconnection.side_effect = ReconnectionExhaustedError("test")

    with pytest.raises(ReconnectionExhaustedError):
        ws_manager.run()
    
    assert ws_manager._state == WebSocketState.FATAL_ERROR

# ✅ 새로 추가된 테스트 케이스
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_handle_reconnection_error_authentication(MockTWM, ws_manager_instance):
    """
    _handle_reconnection_error 메서드가 API 인증 오류를 올바르게 처리하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # BinanceAPIException with code -2015 (invalid API key)
    e = BinanceAPIException(message="Invalid API-key, IP, or permissions for action.", code=-2015)
    
    with pytest.raises(AuthenticationError):
        ws_manager._handle_reconnection_error(e)
    
    assert ws_manager._state == WebSocketState.FATAL_ERROR

# ✅ 새로 추가된 테스트 케이스
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_handle_reconnection_error_binance_fatal(MockTWM, ws_manager_instance):
    """
    _handle_reconnection_error 메서드가 기타 바이낸스 API 치명적 오류를 올바르게 처리하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance

    # BinanceAPIException with an unknown fatal error code
    e = BinanceAPIException(message="Unknown fatal error.", code=UNKNOWN_ERROR_CODE)

    with pytest.raises(BinanceClientException):
        ws_manager._handle_reconnection_error(e)
    
    assert ws_manager._state == WebSocketState.FATAL_ERROR

# ✅ 새로 추가된 테스트 케이스
@patch('clients.websocket_threaded.ThreadedWebsocketManager')
def test_handle_reconnection_error_unexpected_exception(MockTWM, ws_manager_instance):
    """
    _handle_reconnection_error 메서드가 예상치 못한 일반 예외를 올바르게 처리하는지 테스트합니다.
    """
    ws_manager, _, _, _, _ = ws_manager_instance
    
    # 일반적인 예외
    e = ValueError("An unexpected value error occurred.")

    with pytest.raises(WebSocketConnectionError):
        ws_manager._handle_reconnection_error(e)
    
    assert ws_manager._state == WebSocketState.FATAL_ERROR