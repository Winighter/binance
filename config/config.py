SYMBOL = "XRPUSDT"
DEFAULT_LEVERAGE = 10
DEFAULT_POSITION_RATE = 50
ENABLE_SYSTEM1 = True
ENABLE_SYSTEM2 = True
ENABLE_ORDER_FILTER = True
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1375453664885473341/l9ASZS3clm_RTXMvq7kT2D3_wMC3J3uMeUwbQB0w54uBqu8zIxpYLvYCdoL2iibfvi6n'


INITIAL_LONG_LOCK_SYSTEM1 = 1
INITIAL_SHORT_LOCK_SYSTEM1 = 1
INITIAL_LONG_LOCK_SYSTEM2 = 1
INITIAL_SHORT_LOCK_SYSTEM2 = 1

DEFAULT_KLINE_INTERVAL = "5m" # Binance Client.KLINE_INTERVAL_5MINUTE 에 해당하는 문자열

# Strategy periods (from main.py for clarity)
SYSTEM1_HIGH_PERIOD_LONG = 28
SYSTEM1_LOW_PERIOD_LONG = 14
SYSTEM1_HIGH_PERIOD_SHORT = 14
SYSTEM1_LOW_PERIOD_SHORT = 28

SYSTEM2_HIGH_PERIOD_LONG = 56
SYSTEM2_LOW_PERIOD_LONG = 28
SYSTEM2_HIGH_PERIOD_SHORT = 28
SYSTEM2_LOW_PERIOD_SHORT = 56

DEFAULT_KLINE_LIMIT = 500 # get_klines() 호출 시 기본으로 가져올 캔들 개수

# Stop Loss
ATR_MULTIPLIER = 2.0
PROFIT_PNL_THRESHOLD = 0.0 # 0% 이상 이익일 경우 필터 적용
ORDER_PLACEMENT_RETRY_DELAY = 5 # 주문 실패 시 재시도 대기 시간 (초)

# Max data length for indicators/strategies (derived from periods)
# Consider making this a function or calculating dynamically in main,
# or just setting a sufficiently large buffer.
# For example, max period used + some buffer
DATA_HISTORY_BUFFER = max(SYSTEM1_HIGH_PERIOD_LONG, SYSTEM1_LOW_PERIOD_LONG,
                          SYSTEM1_HIGH_PERIOD_SHORT, SYSTEM1_LOW_PERIOD_SHORT,
                          SYSTEM2_HIGH_PERIOD_LONG, SYSTEM2_LOW_PERIOD_LONG,
                          SYSTEM2_HIGH_PERIOD_SHORT, SYSTEM2_LOW_PERIOD_SHORT) + 5