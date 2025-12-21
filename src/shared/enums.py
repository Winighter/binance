from enum import Enum

class FutureClientPeriod(Enum):
    _5M = '5m'
    _15M = '15m'
    _30M = '30m'
    _1H = '1h'
    _2H = '2h'
    _4H = '4h'
    _6H = '6h'
    _12H = '12h'
    _1D = '1d'

class StructureTurn(Enum):
    HIGH = 'HIGH'
    LOW = 'LOW'

class AssetType(Enum):
    FDUSD = 'FDUSD'
    LDUSDT = 'LDUSDT'
    BFUSD = 'BFUSD'
    BNB = 'BNB'
    ETH = 'ETH'
    BTC = 'BTC'
    USDT = 'USDT'
    USDC = 'USDC'

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
    SHORT = "SHORT"
    TEST = 'TEST'

class FilterType(Enum):
    PRICE_FILTER = "PRICE_FILTER"
    LOT_SIZE = "LOT_SIZE"

class OrderSignal(Enum):
    NO_SIGNAL = 'NO_SIGNAL'
    OPEN_POSITION = 'OPEN_POSITION'
    CLOSE_POSITION = 'CLOSE_POSITION'
    UPDATE_STOP_LOSS = 'UPDATE_STOP_LOSS'
    UPDATE_TAKE_PROFIT = 'UPDATE_TAKE_PROFIT'


class ZoneType(Enum):
    DEMAND_SUPPLY = 'DEMAND_SUPPLY'
    WICK = 'WICK'
    REVERSAL = 'REVERSAL'

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