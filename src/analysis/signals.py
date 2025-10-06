import logging
from decimal import Decimal
import settings as app_config
from .metrics import Metrics
from ..shared.enums import LongSignal
from ..shared.state_manager import PositionState
from ..analysis.dtb import process_and_get_dtb_data
from ..analysis.ctr import CommodityTrendReactor
from ..analysis.tets import calculate_trend_reversal_probability_decimal
import pandas as pd 

logger = logging.getLogger("TRADING_SIGNALS")

class TradingSignals:

    def __init__(self, opens:list[Decimal], highs:list[Decimal],
        lows:list[Decimal], closes:list[Decimal], volumes:list[Decimal]):

        self.positions = PositionState()
        self.long_signal = LongSignal.NO_SIGNAL
        # ⚙️ CTR 인스턴스 초기화 (추가)
        self.ctr_analyzer = CommodityTrendReactor(
            cci_len=25,  # 설정값으로 변경 필요 (현재는 25, 20 사용)
            trail_len=20,
            upper=50,
            lower=-50
        )

        ll = self._get_lowest(lows, 14)[-2]
        sh = self._get_lowest(lows, 28)[-2]
        # EMA Indicators
        trend_ema = Metrics.ema(closes, app_config.TREND_PERIOD)

        # Check for sufficient data
        if not trend_ema:
            logger.error(f"Insufficient EMA data. Required length: {app_config.TREND_PERIOD}, Actual: {len(closes)}")
            return 
        
        # Dynamic Trend Bands
        dtb_long, _ = self._dynamic_trend_bands(highs, lows, closes)
        self.is_dtb_long = dtb_long

        # Trend Reversal Probability
        trend_direction, _, _ = self._trend_reversal_probability(highs, lows, closes)
        self.is_trb_long = trend_direction == "SHORT"

        # Commodity Trend Reactor
        ctr_cci = self._commodity_trend_reactor(highs, lows, closes)
        self.is_ctr_long = ctr_cci < Decimal("-200")

        # EMA Condition
        self.is_long_system = lows[-2] == ll == sh
        self.is_ema_long = trend_ema[-2] > closes[-2]
        self.is_long_candle = (opens[-1] < closes[-1]) and \
                            (opens[-2] > closes[-2]) and (volumes[-2] > volumes[-3]) and \
                            ((lows[-1] < lows[-2] and highs[-1] < highs[-2]) == False) and \
                            (highs[-2] - opens[-2] <= closes[-2] - lows[-2]) and \
                            (opens[-3] > closes[-3] or opens[-4] > closes[-4])

        self.is_close_long_position = opens[-1] > closes[-1] and \
                                    opens[-2] > closes[-2] and \
                                    closes[-1] < trend_ema[-1] and \
                                    closes[-2] < trend_ema[-2] and \
                                    closes[-3] > trend_ema[-3] and \
                                    closes[-4] > trend_ema[-4]

        self.find_long_signal()

    def _commodity_trend_reactor(self, highs, lows, closes):

        analysis_results = self.ctr_analyzer.analyze(highs, lows, closes)

        # 1 이전 봉 출력
        # 가장 최신 봉 출력 (항상 존재한다고 가정)
        prev_bar = analysis_results[-2]
        # if prev_bar['Square_Status'] != "중립":
        if len(analysis_results) >= 1:
            # logger.info(f"-------------------------------------")
            # logger.info(f"Bar #{prev_bar['bar_index']}:")
            # logger.info(f"  CCI: {prev_bar['CCI']:.4f}")
            # logger.info(f"  Trend Change: {prev_bar['Trend_Changed']}")
            # logger.info(f"  Trail Line: {prev_bar['Trail_Line']:.4f}")
            # logger.info(f"  Square Status: {prev_bar['Square_Status']}")
            # logger.info(f"  Trend: {'상승 (True)' if prev_bar['Trend'] else '하락 (False)' if prev_bar['Trend'] is not None else 'N/A'}")

            return prev_bar['CCI']

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

    def _trend_reversal_probability(self, highs, lows, closes):

        result_df = calculate_trend_reversal_probability_decimal(
            high_prices=highs,
            low_prices=lows,
            close_prices=closes,
        )
        latest_metrics = result_df.iloc[-1]
        cut = latest_metrics.get('cut', Decimal('NaN'))
        current_custom_rsi = latest_metrics.get('customRSI', Decimal('NaN'))
        current_probability = latest_metrics.get('probability', Decimal('NaN'))
        current_probability = Decimal(str(current_probability)) * Decimal('100')
        if current_custom_rsi > Decimal(0):
            trend_direction = "LONG"
        elif current_custom_rsi < Decimal(0):
            trend_direction = "SHORT"
        else:
            trend_direction = "NEUTRAL"
        return trend_direction, cut, current_probability

    def _dynamic_trend_bands(self, highs, lows, closes):

        # 사용자 입력 설정
        LENGTH = 40
        MULTIPLIER = 2.0
        BAND_SIZE = 2

        # Decimal 리스트를 사용하여 프로세스 실행
        dtb_df = process_and_get_dtb_data( # 함수 이름에 맞게 변경
            high=highs, 
            low=lows, 
            close=closes, 
            length=LENGTH, 
            multi=MULTIPLIER, 
            band_size=BAND_SIZE
        )
        # 2. 최신 DTB 지표 값 가져오기
        prev_dtb = dtb_df.iloc[-2]

        dtb_lower_outer = prev_dtb['Lower_Band'] # 하단 밴드의 바깥쪽 (낮은) 경계선
        dtb_lower_inner = prev_dtb['Lower_Band1'] # 하단 밴드의 안쪽 (높은) 경계선

        dtb_upper_outer = prev_dtb['Upper_Band1'] # 상단 밴드의 (높은) 바깥쪽
        dtb_upper_inner = prev_dtb['Upper_Band']  # 상단 밴드의 (낮은) 안쪽

        # 1. 값이 nan이 아닌지 먼저 확인합니다.
        if not pd.isna(dtb_upper_inner):
            prev_close = closes[-2]
            # 2. 값이 nan이 아닐 때만 (즉, 상단 밴드가 하락 중일 때만) 로직을 실행합니다.
            if prev_close < dtb_upper_inner:
                # 캔들이 하락 중인 상단 밴드 아래에 위치함 (약세 시그널)
                # logger.info(f"하락 {dtb_upper_outer} {dtb_upper_inner}")
                return True, False
        else:
            # 3. nan일 때는 밴드가 상승 중이므로, 강세장으로 간주하고 해당 매도 로직은 실행하지 않습니다.
            # logger.info(f"상승 {dtb_lower_inner} {dtb_lower_outer}")
            return False, False
        return False, False

    def find_long_signal(self):

        if self.positions.long is None:
            # OPEN POSITION
            if self.is_long_system and \
                self.is_long_candle and \
                self.is_ema_long and \
                self.is_dtb_long and \
                self.is_trb_long and \
                self.is_ctr_long:
                self.long_signal = LongSignal.OPEN_POSITION

            # TAKE PROFIT ALL POSITION
            if self.is_close_long_position:
                self.long_signal = LongSignal.CLOSE_POSITION

        return self.long_signal