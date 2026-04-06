from src.shared.enums import KlineInterval


FUTURES_TRADING_ASSET = 'USDT'
SYMBOL = "XRPUSDT"
LEVERAGE = 1

# KLINE_INTERVAL
KLINE_INTERVALS = [KlineInterval.MINUTE_5, KlineInterval.HOUR_1, KlineInterval.HOUR_4] # [LTF, MTF, HTF]


### ENABLES ###
ENABLE_ORDER = False # 실거래 주문 실행 여부
ENABLE_SIMULATION = False # 백테스팅 시뮬레이션 실행 여부
ENABLE_DISCORD_ALERTS = False  # 디스코드 알림 활성화 여부