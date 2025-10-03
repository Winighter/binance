import logging
from decimal import Decimal
import settings as app_config
from .metrics import Metrics
from ..shared.enums import LongSignal
from ..shared.state_manager import PositionState

logger = logging.getLogger("TRADING_SIGNALS")

class TradingSignals:

    def __init__(self, opens:list[Decimal], highs:list[Decimal],
        lows:list[Decimal], closes:list[Decimal], volumes:list[Decimal]):

        self.positions = PositionState()
        self.long_signal = LongSignal.NO_SIGNAL
        self.last_scaling_out_bar = -1
        self.bar_index = len(closes) - 1

        # EMA Indicators
        ema_shorts = Metrics.ema(closes, app_config.EMA_SHORT_PERIOD)
        ema_middles = Metrics.ema(closes, app_config.EMA_MIDDLE_PERIOD)
        ema_longs = Metrics.ema(closes, app_config.EMA_LONG_PERIOD)

        # Check for sufficient data
        if not ema_shorts or not ema_middles or not ema_longs:
            logger.error(f"Insufficient EMA data. Required length: {app_config.EMA_LONG_PERIOD}, Actual: {len(self.closes)}")
            return 

        ema_short = ema_shorts[-1]
        ema_middle = ema_middles[-1]
        ema_long = ema_longs[-1]

        # ATR Data
        atr_list = Metrics.atr(highs, lows, closes)
        if not atr_list:
            logger.error("Insufficient ATR data. Aborting strategy.")
            return

        atr_value = atr_list[-1]

        # Keltner Channel Data
        kc_ema = ema_middle
        kc_upper, _, _ = Metrics.keltner_channels(kc_ema, atr_value, app_config.kc_multiplier)

        # sharing Conditions (self.)
        self.is_kc_breakout = closes[-1] > kc_upper
        self.is_bullish_alignment = ema_short > ema_middle > ema_long # EMA 3개 선 정배열
        self.is_ignore_entry_signal = (closes[-1] - lows[-1]) >= (atr_value * app_config.atr_multiplier) # 진입 시 무시해야 하는 조건
        self.is_bullish_high_low = highs[-1] > highs[-2] and lows[-1] > lows[-2] # 현재 모든 고가, 저가가 이전 봉보다 높다
        self.highest_volume = volumes[-1] == max(volumes[-1], volumes[-2], volumes[-3]) # 최근 3봉 중 가장 높은 거래량
        self.three_white_soldiers = opens[-1] < closes[-1] and opens[-2] < closes[-2] and opens[-3] < closes[-3]
        self.is_take_profit_all_position = opens[-1] > ema_long > closes[-1] and ema_short > ema_long and ema_middle > ema_long
        # Combined Bullish Trend
        self.is_bullish_ema_trend = self.three_white_soldiers and \
                                    self.is_bullish_high_low and \
                                    self.highest_volume and \
                                    self.is_bullish_alignment and \
                                    closes[-1] > ema_short
 
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
                logger.info(f"To be added later...")
                self.long_signal = LongSignal.ADD_POSITION

            # TAKE PROFIT ALL POSITION
            if self.is_take_profit_all_position:
                self.long_signal = LongSignal.TAKE_PROFIT

        return self.long_signal