from .indicators import *

from . supertrend_strategy import *

from abc import ABC, abstractmethod

class TradingStrategy(ABC):
    """모든 트레이딩 전략이 상속받아야 하는 추상 기본 클래스."""
    @abstractmethod
    def get_signal(self, ohlcv_data: dict) -> int:
        """캔들 데이터에 기반하여 매수(1), 매도(-1), 또는 신호 없음(0)을 반환합니다."""
        pass