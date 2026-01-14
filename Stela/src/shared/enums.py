from enum import Enum


class MsgColorCode(Enum):
    RED = 0xe74c3c
    GREEN = 0x2ecc71
    BLUE = 0x3498db
    GRAY = 0x95a5a6
    BLACK = 0x23272a
    ORANGE = 0xffa500

class MarginType(Enum):
    CROSSED = 'CROSSED'
    ISOLATED = 'ISOLATED'

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
class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP = 'STOP'
    TAKE_PROFIT = 'TAKE_PROFIT'
    LIQUIDATION = 'LIQUIDATION'

class AlgoOrderEventStatus(Enum):
    NEW = 'NEW' # 조건부 주문이 알고리즘 서비스에 성공적으로 접수되었지만 아직 실행되지 않았음을 나타냅니다.
    CANCELED = 'CANCELED' # 조건부 주문이 취소되었음을 의미합니다.
    TRIGGERING = 'TRIGGERING' # 주문이 트리거 조건을 충족하여 매칭 엔진으로 전달되었음을 나타냅니다.
    TRIGGERED = 'TRIGGERED' # 주문이 매칭 엔진에 성공적으로 접수되었음을 의미합니다.
    FINISHED = 'FINISHED' # 트리거된 조건부 주문이 매칭 엔진에서 체결되었거나 취소되었음을 나타냅니다.
    REJECTED = 'REJECTED' # 조건부 주문이 매칭 엔진에 의해 거부되었음을 나타냅니다. 예를 들어 마진 확인 실패와 같은 상황에서 발생합니다.
    EXPIRED = 'EXPIRED' # 시스템에 의해 조건부 주문이 취소되었음을 나타냅니다. 예를 들어 사용자가 GTE_GTC에 대한 기간 강제 조건부 주문을 설정한 후 해당 종목의 모든 포지션을 청산하면 시스템에 의해 조건부 주문이 취소됩니다.

class AlgoOrderType(Enum):
    STOP = 'STOP'
    TAKE_PROFIT = 'TAKE_PROFIT'
    STOP_MARKET = 'STOP_MARKET'
    TAKE_PROFIT_MARKET = 'TAKE_PROFIT_MARKET'
    TRAILING_STOP_MARKET = 'TRAILING_STOP_MARKET'

class OrderStatus(Enum):
    NEW = 'NEW'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCELED = 'CANCELED'
    EXPIRED = 'EXPIRED'
    EXPIRED_IN_MATCH = 'EXPIRED_IN_MATCH'

class PositionSide(Enum):
    '''
    Docstring for PositionSide
    Default 'BOTH' for One-way Mode; 'LONG' or 'SHORT' for Hedge Mode, It must be sent in Hedge Mode.
    '''
    BOTH = 'BOTH'
    LONG = 'LONG'
    SHORT = 'SHORT'

class OrderSignal(Enum):
    NO_SIGNAL = 'NO_SIGNAL'
    OPEN_POSITION = 'OPEN_POSITION'
    CLOSE_POSITION = 'CLOSE_POSITION'
    UPDATE_STOP_LOSS = 'UPDATE_STOP_LOSS'
    UPDATE_TAKE_PROFIT = 'UPDATE_TAKE_PROFIT'

class KlineInterval(Enum):
    '''
    - seconds: 1s
    - minutes: 1m, 3m, 5m, 15m, 30m
    - hours: 1h, 2h, 4h, 6h, 8h, 12h
    - days: 1d, 3d
    - weeks: 1w
    - months: 1M
    '''
    MINUTE_1 = (1, '1m')
    MINUTE_3 = (3, '3m')
    MINUTE_5 = (5, '5m')
    MINUTE_15 = (15, '15m')
    MINUTE_30 = (30, '30m')

    HOUR_1 = (60, '1h')
    HOUR_2 = (120, '2h')
    HOUR_4 = (240, '4h')
    HOUR_6 = (360, '6h')
    HOUR_8 = (480, '8h')
    HOUR_12 = (720, '12h')

    DAY_1 = (1440, '1d')
    DAY_3 = (4320, '3d')

    WEEK_1 = (10080, '1w')

    MONTH_1 = (43200, '1M')

    def __init__(self, minutes: int, code: str):
        self.minutes = minutes  # 숫자 계산용 (예: 5)
        self.code = code        # API 요청용 (예: '5m')

    @classmethod
    def get_by_code(cls, code: str):
    # 만약 이미 같은 타입의 Enum 객체가 인자로 들어왔다면 그대로 반환
        if isinstance(code, cls):
            return code

        for member in cls:
            if member.code == code:
                return member
        return None
    

class UserDataEventType(Enum):
    '''
    User Data Stream subscriptions allow you to receive all the events related to a given account on a WebSocket connection.
    '''
    ALGO_UPDATE = 'ALGO_UPDATE'
    ACCOUNT_UPDATE = 'ACCOUNT_UPDATE'
    ORDER_TRADE_UPDATE = 'ORDER_TRADE_UPDATE'
    ACCOUNT_CONFIG_UPDATE = 'ACCOUNT_CONFIG_UPDATE'

class UserDataEventReasonType(Enum):
    ORDER = 'ORDER' # 주문
    DEPOSIT = 'DEPOSIT' # 입금
    WITHDRAW = 'WITHDRAW' # 출금