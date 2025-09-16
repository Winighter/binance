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