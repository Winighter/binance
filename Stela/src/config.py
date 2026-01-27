NO_DATA_TIMEOUT = 60 # # 데이터 수신이 없을 경우 연결 끊김으로 간주하는 시간 (초)
MAX_RECONNECT_ATTEMPTS = 10  # 최대 재연결 시도 횟수
BACKOFF_FACTOR = 2           # 지수 백오프에 사용될 계수
INITIAL_RECONNECT_DELAY = 1  # 초기 재연결 대기 시간 (초)
MAX_RETRY_DELAY = 60
MAX_RETRIES = 3 # 최대 재시도 횟수
MONITOR_INTERVAL_SECONDS = 1
MAX_WORKER_THREADS = 4 # 핸들러를 처리할 워커 스레드의 최대 개수 ex) 4 or 8

KLINE_LIMIT_MULTIPLE = 2 # 15m * 70 = 1Year
KLINE_LIMIT = 500 * KLINE_LIMIT_MULTIPLE # get_klines() 호출 시 기본으로 가져올 캔들 개수
VALID_KLINES_LIMIT_MAX = 1000
POSITION_SYNC_INTERVAL = 60

SLIPPAGE_PERCENT = 0.02 # (%)
