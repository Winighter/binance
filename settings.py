NO_DATA_TIMEOUT = 60 # # 데이터 수신이 없을 경우 연결 끊김으로 간주하는 시간 (초)
MAX_RECONNECT_ATTEMPTS = 10  # 최대 재연결 시도 횟수
BACKOFF_FACTOR = 2           # 지수 백오프에 사용될 계수
INITIAL_RECONNECT_DELAY = 1  # 초기 재연결 대기 시간 (초)
MAX_RETRY_DELAY = 60
# Client
MAX_RETRIES = 3 # 최대 재시도 횟수
RETRY_DELAY_SECONDS = 5 # 기본 재시도 지연 시간 (초)

MONITOR_INTERVAL_SECONDS = 1

MAX_WORKER_THREADS = 4 # 핸들러를 처리할 워커 스레드의 최대 개수 ex) 4 or 8

FUTURES_TRADING_ASSET = 'USDT'
SYMBOL = "XRPUSDT"
LEVERAGE = 10
POSITION_RATE = 45
KLINE_INTERVAL = "5m" # 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
KLINE_LIMIT = 500 # get_klines() 호출 시 기본으로 가져올 캔들 개수
# DISCORD
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1375453664885473341/l9ASZS3clm_RTXMvq7kT2D3_wMC3J3uMeUwbQB0w54uBqu8zIxpYLvYCdoL2iibfvi6n'
MAX_WAITING_SECONDS = 10
### ENABLES ###
TEST_MODE = False
HEDGE_MODE = True

# SUPER TREND CONFIG
SUPERTREND_ATR_LENGTH = 14
SUPERTREND_MULTIPLIER = 4.0

# Stop Loss (Required)
ATR_LENGTH = 14
ATR_MULTIPLIER = 2.1 # 높을경우 손절확률은 낮고 손실금액이 높음, 낮으면 그반대 (최소 1.0 이상)
ORDER_PLACEMENT_RETRY_DELAY = 5 # 주문 실패 시 재시도 대기 시간 (초)

VALID_KLINES_LIMIT_MAX = 1000
VALID_KLINES_INTERVALS = {'1m', '3m', '5m', '15m', '30m'}

CIRCUIT_BREAKER_MAX_FAILURES = 3 # 연속 실패 허용 횟수
CIRCUIT_BREAKER_TIMEOUT_SECONDS = 30 # 서킷 브레이커 열림 상태 유지 시간