from decimal import Decimal, getcontext


getcontext().prec = 28

class Indicators():

    @staticmethod
    def ema(prices: list[Decimal], period: int) -> list[Decimal]:

        if not prices or len(prices) < period:
            return []

        multiplier = Decimal('2') / (Decimal(period) + Decimal('1'))
        ema_list = []
        first_ema = sum(prices[0:period]) / Decimal(period)
        ema_list.append(first_ema)

        for i in range(period, len(prices)):
            current_price = prices[i]
            prev_ema = ema_list[-1]
            current_ema = (current_price - prev_ema) * multiplier + prev_ema
            ema_list.append(current_ema)
            
        return ema_list

    @staticmethod
    def atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int = 14) -> list[Decimal]:
        if not highs or not lows or not closes or len(highs) != len(lows) or len(highs) != len(closes) or len(highs) < period:
            return []

        true_ranges = []
        for i in range(len(highs)):
            h_l = highs[i] - lows[i]
            if i > 0:
                h_c_prev = abs(highs[i] - closes[i-1])
                l_c_prev = abs(lows[i] - closes[i-1])
                true_range = max(h_l, h_c_prev, l_c_prev)
            else:
                true_range = h_l
            true_ranges.append(true_range)
        
        # 첫 번째 ATR은 True Range의 단순 평균(SMA)
        atr_list = [sum(true_ranges[:period]) / Decimal(period)]

        # 이후 ATR은 지수 이동 평균(EMA)을 사용하여 계산
        for i in range(period, len(true_ranges)):
            current_atr = (atr_list[-1] * (period - 1) + true_ranges[i]) / Decimal(period)
            atr_list.append(current_atr)

        return atr_list
    
    @staticmethod
    def keltner_channels(highs, lows, closes, period):
        ma_values = Indicators.ema(closes, period)
        atr_values = Indicators.atr(highs, lows, closes)
        rangema = Decimal(str(atr_values[-1]))
        multiplier = Decimal('2.0')

        ma = Decimal(str(ma_values[-1])) # Basis
        upper = Decimal(str(ma + rangema * multiplier)) # Upper
        lower = Decimal(str(ma - rangema * multiplier)) # Lower
        return upper, ma, lower