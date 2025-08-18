from enum import Enum

class LockState(Enum):
    READY_TO_OPEN = 0        # 시스템이 새로운 포지션을 열 준비가 된 상태
    AWAITING_SELL_SIGNAL = 1      # 다음 신호를 기다리는 상태
    IGNORE_NEXT_SIGNAL = -1  # 다음 신호를 무시해야 하는 상태 (예: 수익 실현 후)

class ST_SIGNAL(Enum):
    OPEN_LONG = 1        # 
    CLOSE_LONG = -1      # 
    OPEN_SHORT = -1      # 
    CLOSE_SHORT = 1      # 