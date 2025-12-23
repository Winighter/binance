import logging
from decimal import Decimal

from ..shared.enums import OrderSignal, OrderSignal
from ..shared.state_manager import PositionState


logger = logging.getLogger("TRADING_SIGNALS")

class TradingSignals:

    def __init__(self, opens:list[Decimal], highs:list[Decimal],
        lows:list[Decimal], closes:list[Decimal], volumes:list[Decimal]):

        self.positions = PositionState()
        self.long_signal = OrderSignal.NO_SIGNAL
        self.short_signal = OrderSignal.NO_SIGNAL

        ll = self._get_lowest(lows, 14)[-2]
        sh = self._get_lowest(lows, 28)[-2]

        # EMA Condition
        self.is_long_system = lows[-2] == ll == sh
        self.is_long_candle = (opens[-1] < closes[-1]) and \
                            (opens[-2] > closes[-2]) and (volumes[-2] > volumes[-3]) and \
                            ((lows[-1] < lows[-2] and highs[-1] < highs[-2]) == False) and \
                            (highs[-2] - opens[-2] <= closes[-2] - lows[-2]) and \
                            (opens[-3] > closes[-3] or opens[-4] > closes[-4])

        self.find_long_signal()
        self.find_short_signal()

    def _get_lowest(self, src:list, period:int):

        if len(src) < period:
            return IndexError(f"Insufficient source data length.")
        result = []
        for i in range(len(src)):
            if i >= period - 1:
                l = []
                for ii in range(period):
                    l.append(src[i+ii])
                r = min(l)
                result.append(r)
                if i == len(src) - period:
                    break
        return result

    def find_long_signal(self):

        if self.positions.long is None:
            # OPEN POSITION
            if self.is_long_system and \
                self.is_long_candle:
                self.long_signal = OrderSignal.OPEN_POSITION

            # TAKE PROFIT ALL POSITION
            if False:
                self.long_signal = OrderSignal.CLOSE_POSITION

        return self.long_signal

    def find_short_signal(self):

        if self.positions.short is None:
            # OPEN POSITION
            if False:
                self.short_signal = OrderSignal.OPEN_POSITION

            # TAKE PROFIT ALL POSITION
            if False:
                self.short_signal = OrderSignal.CLOSE_POSITION

        return self.short_signal