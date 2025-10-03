from decimal import Decimal, getcontext
from typing import List, Dict, Union, Optional

# 정밀도 설정 (금융 계산을 위해 높게 설정)
getcontext().prec = 20 

class CommodityTrendReactor:
    """
    Pine Script의 'Commodity Trend Reactor' 지표의 핵심 로직을
    Decimal을 사용하여 구현한 파이썬 클래스입니다.
    CCI 계산과 트렌드 추적 로직을 포함합니다.
    """
    
    def __init__(self, cci_len: int = 25, trail_len: int = 20, upper: int = 50, lower: int = -50):
        """
        지표의 파라미터를 초기화합니다.
        
        :param cci_len: CCI 계산 기간 (Pine Script의 'len').
        :param trail_len: 트레일 라인 계산 기간 (Pine Script의 't_len').
        :param upper: CCI 상단 임계값.
        :param lower: CCI 하단 임계값.
        """
        self.cci_len = cci_len
        self.trail_len = trail_len
        self.upper = Decimal(str(upper))
        self.lower = Decimal(str(lower))
        
        # 이전 캔들의 추세 상태를 저장합니다. (True: 롱, False: 숏, None: N/A - Pine Script의 na와 유사)
        self.previous_trend: Optional[bool] = None

    def _calculate_cci(self, prices: List[Dict[str, Decimal]]) -> List[Decimal]:
        """
        Commodity Channel Index (CCI)를 계산합니다. (Pine Script와 동일한 공식 및 기간 사용)
        
        ⚠️ 수정됨: 두 번째 Pine Script의 ta.cci(close, len)에 맞춰 종가만을 사용합니다.
        
        :param prices: OHLC 데이터를 포함하는 딕셔너리 리스트.
        :return: 계산된 CCI 값의 리스트.
        """
        cci_values = []
        
        for i in range(self.cci_len, len(prices) + 1):
            # 현재 윈도우 (cci_len 기간)의 가격 데이터
            window = prices[i - self.cci_len: i]
            
            # M A (종가) 계산: Pine Script의 ta.cci(close, len)에 맞춰 종가만을 CCI 계산의 소스로 사용합니다.
            source_prices = [p['close'] for p in window]

            # S M A (Simple Moving Average of Source Price)
            sma_source = sum(source_prices) / Decimal(self.cci_len)
            
            # Mean Deviation 계산
            mean_deviation = sum(abs(price - sma_source) for price in source_prices) / Decimal(self.cci_len)
            
            # 현재 Source Price (종가)
            current_source_price = source_prices[-1]
            
            # CCI 계산: CCI = (Source_Price - SMA_Source) / (0.015 * Mean_Deviation)
            if mean_deviation == Decimal('0'):
                cci = Decimal('0')
            else:
                cci = (current_source_price - sma_source) / (Decimal('0.015') * mean_deviation)
                
            cci_values.append(cci)
            
        return cci_values

    def analyze(self, high_list: List[Decimal], low_list: List[Decimal], close_list: List[Decimal]) -> List[Dict[str, Union[Decimal, bool, str, None]]]:
        """
        주어진 가격 리스트를 분석하여 CCI, 추세, 트레일 라인 상태를 반환합니다.
        """
        
        if not (len(high_list) == len(low_list) == len(close_list)):
            raise ValueError("고가, 저가, 종가 리스트의 길이가 동일해야 합니다.")
        
        # OHLC 딕셔너리 리스트 생성
        prices: List[Dict[str, Decimal]] = [
            {'high': h, 'low': l, 'close': c} 
            for h, l, c in zip(high_list, low_list, close_list)
        ]
        
        # CCI 계산
        # analyze에서는 OHLC 딕셔너리 리스트를 그대로 전달하며,
        # _calculate_cci에서 종가만을 추출하여 사용하도록 변경되었습니다.
        cci_values = self._calculate_cci(prices)
        
        # CCI 계산이 시작되는 인덱스 (CCI_len - 1)
        start_index = self.cci_len - 1
        
        results: List[Dict[str, Union[Decimal, bool, str, None]]] = []
        
        current_trend: Optional[bool] = self.previous_trend 
        
        for i in range(len(cci_values)):
            bar_index = start_index + i
            current_cci = cci_values[i]
            previous_cci = cci_values[i-1] if i > 0 else None
            
            trend_changed = False
            
            # --- 1. 추세 (Trend) 결정 로직 (Pine Script의 crossover/crossunder) ---
            
            # cci > upper 돌파 (Long Signal)
            if current_cci > self.upper and (previous_cci is None or previous_cci <= self.upper):
                if current_trend is not True:
                    current_trend = True
                    trend_changed = True
            
            # cci < lower 하회 (Short Signal)
            elif current_cci < self.lower and (previous_cci is None or previous_cci >= self.lower):
                if current_trend is not False:
                    current_trend = False
                    trend_changed = True

            # --- 2. 트레일 라인 (Trail Line) 계산 (Pine Script의 low_ / high_ 선택) ---
            
            # 현재 윈도우 (trail_len 기간)의 고가/저가 데이터
            trail_window = prices[max(0, bar_index - self.trail_len + 1): bar_index + 1]
            
            low_ = min(p['low'] for p in trail_window) # ta.lowest(t_len)
            high_ = max(p['high'] for p in trail_window) # ta.highest(t_len)
            
            trail_line: Union[Decimal, None] = None 
            
            if current_trend is True:
                trail_line = low_ # Long trend: trail_line := low_
            elif current_trend is False:
                trail_line = high_ # Short trend: trail_line := high_
            # current_trend가 None일 경우 trail_line은 None 유지 (float(na)와 동일)

            # --- 3. 극단 상태 (Square Status) 결정 로직 ---
            square_status = "중립"
            if current_cci >= Decimal('200'):
                square_status = "과매수 극단 (▲)"
            elif current_cci <= Decimal('-200'):
                square_status = "과매도 극단 (▼)"

            # --- 결과 저장 ---
            results.append({
                "bar_index": bar_index,
                "CCI": current_cci,
                "Trend": current_trend,
                "Trend_Changed": trend_changed,
                "Trail_Line": trail_line,
                "Square_Status": square_status
            })
            
        # 마지막 추세 상태를 저장하여 다음 호출에 사용
        if results:
            self.previous_trend = results[-1]['Trend']
            
        return results