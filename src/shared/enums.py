from enum import Enum


class TradingMode(Enum):
    EMA_CROSS = 'EMA_CROSS'
    SUPERTREND = 'SUPERTREND'

class WebSocketState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FATAL_ERROR = "FATAL_ERROR"

# 새로운 열거형(Enum) 클래스 추가
class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class PositionSide(Enum):
    LONG = "LONG"

class FilterType(Enum):
    PRICE_FILTER = "PRICE_FILTER"
    LOT_SIZE = "LOT_SIZE"

class EmaSignal(Enum):
    LONG_OPENING_POSITION = 'LONG_OPENING_POSITION'
    LONG_WAITING_SIGNAL = 'LONG_WAITING_SIGNAL'
    LONG_SCALING_OUT = 'LONG_SCALING_OUT'
    LONG_TAKE_PROFIT = 'LONG_TAKE_PROFIT'

class KlineIntervals(Enum):
    # Second
    SECOND_1 = '1s'

    # Minute
    MINUTE_1 = '1m'
    MINUTE_3 = '3m'
    MINUTE_5 = '5m'
    MINUTE_15 = '15m'
    MINUTE_30 = '30m'

    # Hour
    HOUR_1 = '1h'
    HOUR_2 = '2h'
    HOUR_4 = '4h'
    HOUR_6 = '6h'
    HOUR_8 = '8h'
    HOUR_12 = '12h'

    # Day
    DAY_1 = '1d'
    DAY_3 = '3d'

    # Week
    WEEK_1 = '1w'

    # Month
    MONTH_1 = '1M'