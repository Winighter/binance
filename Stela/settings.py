from src.shared.enums import KlineInterval


FUTURES_TRADING_ASSET = 'USDT'
SYMBOL = "XRPUSDT"
LEVERAGE = 1

# KLINE_INTERVAL
KLINE_INTERVAL = KlineInterval.MINUTE_15


### ENABLES ###
ENABLE_ORDER = True # 실거래 주문 실행 여부
ENABLE_SIMULATION = False # 백테스팅 시뮬레이션 실행 여부
ENABLE_DISCORD_ALERTS = True  # 디스코드 알림 활성화 여부