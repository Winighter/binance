from decimal import Decimal
from typing import Dict, Any
from ..strategy.indicators import Indicators
import settings as app_config
from .__init__ import TradingStrategy # TradingStrategy 추상 클래스 임포트


class SupertrendStrategy(TradingStrategy):
    def __init__(self):
        self.indicators = Indicators()

    def get_signal(self, ohlcv_data: Dict[str, Any]) -> int:
        """
        주어진 캔들 데이터를 사용하여 Supertrend 전략 신호를 생성합니다.
        
        Args:
            ohlcv_data: 캔들 데이터가 포함된 딕셔너리.
            
        Returns:
            매수 신호(1), 매도 신호(-1), 또는 신호 없음(0)을 반환합니다.
        """
        df = self.indicators.get_ohlcv_df(ohlcv_data)
        supertrend_value = self.indicators.get_supertrend(
            df['high'], df['low'], df['close'], 
            length=app_config.SUPER_TREND_PERIOD, multiplier=app_config.SUPER_TREND_MULTIPLIER
        )

        current_supertrend = supertrend_value.iloc[-1]
        last_close = Decimal(str(df['close'].iloc[-1]))
        
        if last_close > current_supertrend and self.is_supertrend_up_from_below(supertrend_value):
            return 1
        elif last_close < current_supertrend and self.is_supertrend_down_from_above(supertrend_value):
            return -1
        
        return 0

    def is_supertrend_up_from_below(self, supertrend_values):
        """
        Supertrend 라인이 아래에서 위로 상승 반전했는지 확인합니다.
        """
        if len(supertrend_values) < 2:
            return False
        return supertrend_values.iloc[-2] > supertrend_values.iloc[-1]
        
    def is_supertrend_down_from_above(self, supertrend_values):
        """
        Supertrend 라인이 위에서 아래로 하락 반전했는지 확인합니다.
        """
        if len(supertrend_values) < 2:
            return False
        return supertrend_values.iloc[-2] < supertrend_values.iloc[-1]