from enum import Enum

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

class FilterType(Enum):
    PRICE_FILTER = "PRICE_FILTER"
    LOT_SIZE = "LOT_SIZE"

class CircuitBreakerState(Enum):
    CLOSED = 'CLOSED'
    OPEN = 'OPEN'
    HALF_OPEN = 'HALF_OPEN'