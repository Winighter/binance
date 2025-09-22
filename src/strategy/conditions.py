import logging
from decimal import Decimal
import settings as app_config
from .indicators import Indicators
from ..shared.enums import LongSignal
from ..shared.state_manager import PositionState

logger = logging.getLogger("TRADING_STRATEGY")

class TradingStrategy:

    def __init__(self, opens:list[Decimal], highs:list[Decimal],
        lows:list[Decimal], closes:list[Decimal], volumes:list[Decimal]):

        self.positions = PositionState()

        # Long Default Signal
        self.long_signal = LongSignal.NO_SIGNAL

        # 💡 스케일링 아웃 로직을 위한 변수 추가
        self.last_scaling_out_bar = -1
        self.bar_index = len(closes) - 1

        # Candle Data
        open = opens[-1]
        low = lows[-1]
        close = closes[-1]

        # EMA Data
        ema_shorts = Indicators.ema(closes, app_config.SHORT_PERIOD)
        ema_middles = Indicators.ema(closes, app_config.MIDDLE_PERIOD)
        ema_longs = Indicators.ema(closes, app_config.LONG_PERIOD)
        ema_short = ema_shorts[-1]
        ema_middle = ema_middles[-1]
        ema_long = ema_longs[-1]

        # Keltner Channel Data
        kc_upper, _, _ = Indicators.keltner_channels(highs, lows, closes, app_config.MIDDLE_PERIOD)

        # ATR Data
        atr_values2 = Indicators.atr(highs, lows, closes)
        n2_atr = Decimal(str(atr_values2[-1]))
        atr_multi = Decimal('1.81')

        # sharing Conditions (self.)
        self.is_kc_breakout = close > kc_upper
        self.is_bullish_alignment = ema_short > ema_middle > ema_long # EMA 3개 선 정배열
        self.is_ignore_entry_signal = (close - low) >= (n2_atr * atr_multi) # 진입 시 무시해야 하는 조건
        self.is_bullish_high_low = highs[-1] > highs[-2] and low > lows[-2] # 현재 모든 고가, 저가가 이전 봉보다 높다
        self.highest_volume = volumes[-1] == max(volumes[-1], volumes[-2], volumes[-3]) # 최근 3봉 중 가장 높은 거래량
        self.three_white_soldiers = open < close and opens[-2] < closes[-2] and opens[-3] < closes[-3]
        self.is_take_profit_all_position = open > ema_long > close and ema_short > ema_long and ema_middle > ema_long
        self.is_bullish_ema_trend = self.three_white_soldiers and self.is_bullish_high_low and self.highest_volume and self.is_bullish_alignment and close > ema_short
 
        self.find_long_signal()

    def find_long_signal(self):

        if self.positions.long is None:
            # OPEN POSITION
            if self.is_kc_breakout and \
                self.is_bullish_ema_trend and \
                not self.is_ignore_entry_signal:
                self.long_signal = LongSignal.OPEN_POSITION

        elif self.positions.long is not None:
            # SCAILING OUT POSITION
            if self.is_bullish_ema_trend and \
                (self.bar_index - self.last_scaling_out_bar) >= 2:
                self.long_signal = LongSignal.SCALING_OUT
                self.last_scaling_out_bar = self.bar_index

            # ADD POSITION
            add_position_signal = False
            if add_position_signal:
                logger.info(f"추후 조건 작성 예정")
                self.long_signal = LongSignal.ADD_POSITION

            # TAKE PROFIT ALL POSITION
            if self.is_take_profit_all_position:
                self.long_signal = LongSignal.TAKE_PROFIT

        return self.long_signal