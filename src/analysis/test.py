import math
from typing import List, Optional, Tuple
from decimal import Decimal

# PriceType을 Decimal로 통일합니다.
PriceType = Decimal
DirectionType = int

class Move:
    """단일 추세(Move) 또는 되돌림(Pullback)을 나타내는 클래스"""
    def __init__(self, start_bar: int, start_price: PriceType, end_bar: int, end_price: PriceType):
        self.start_bar = start_bar
        self.start_price = start_price
        self.end_bar = end_bar
        self.end_price = end_price

    def size(self) -> PriceType:
        """추세의 크기를 퍼센트(%)로 계산 (양수: 상승, 음수: 하락)"""
        if self.start_price is None or self.end_price is None or self.start_price == Decimal('0'):
            return Decimal('0.0')
        return (self.end_price / self.start_price - Decimal('1')) * Decimal('100.0')

    def __bool__(self):
        """객체가 na(None)인지 확인"""
        return self.start_price is not None

class MoveFinder:
    """특정 방향의 추세를 감지하고 가장 큰 추세를 추적하는 핵심 클래스"""
    def __init__(self, direction: DirectionType, use_upper_bound: bool = False, is_pullback_finder: bool = False):
        self.direction = direction
        self.use_upper_bound = use_upper_bound
        
        self.start_bar: Optional[int] = None
        self.start_price: Optional[PriceType] = None
        
        self.biggest_move: Optional[Move] = None
        self.biggest_pb_lb: Optional[Move] = None
        self.biggest_pb_ub: Optional[Move] = None

        if not is_pullback_finder:
            self.pb_finder_lb: Optional[MoveFinder] = MoveFinder(-direction, False, is_pullback_finder=True)
            self.pb_finder_ub: Optional[MoveFinder] = MoveFinder(-direction, True, is_pullback_finder=True)
        else:
            self.pb_finder_lb: Optional[MoveFinder] = None
            self.pb_finder_ub: Optional[MoveFinder] = None


    def renew_pullback_finders(self):
        """새로운 추세가 시작될 때 되돌림 추적기 초기화"""
        if self.pb_finder_lb:
            self.pb_finder_lb = MoveFinder(-self.direction, False, is_pullback_finder=True)
            self.pb_finder_ub = MoveFinder(-self.direction, True, is_pullback_finder=True)

    def set_biggest_move(self, new_move: Move):
        """가장 큰 추세를 업데이트하고 되돌림 정보 저장"""
        self.biggest_move = new_move
        
        if self.pb_finder_lb and self.pb_finder_lb.biggest_move:
            self.biggest_pb_lb = self.pb_finder_lb.biggest_move
        if self.pb_finder_ub and self.pb_finder_ub.biggest_move:
            self.biggest_pb_ub = self.pb_finder_ub.biggest_move

    def update_core(self, bar_index: int, o: PriceType, h: PriceType, l: PriceType, c: PriceType):
        """단일 봉 데이터를 사용하여 MoveFinder를 업데이트하는 핵심 로직"""
        d = self.direction
        
        extreme = h if d > 0 else l
        other_extreme = l if d > 0 else h

        start = self.start_price if self.start_price is not None else o
        if d > 0:
            start = min(start, o)
        else:
            start = max(start, o)

        new_extreme = (self.start_price is None) or (d * other_extreme < d * self.start_price)
        
        bar1 = self.start_bar if self.start_bar is not None else bar_index

        if self.use_upper_bound and new_extreme:
            start = other_extreme
            bar1 = bar_index

        # Decimal 상수 사용
        move_size = d * (extreme / start - Decimal('1')) * Decimal('100.0')

        biggest_size = self.biggest_move.size() * d if self.biggest_move else Decimal('0.0')
        if move_size > biggest_size:
            self.set_biggest_move(Move(bar1, start, bar_index, extreme))
        
        if new_extreme:
            self.start_bar = bar_index
            self.start_price = other_extreme
            self.renew_pullback_finders()

    def update(self, bar_index: int, o: PriceType, h: PriceType, l: PriceType, c: PriceType):
        """되돌림 추적기를 포함하여 전체 업데이트 실행"""
        if self.pb_finder_lb:
            self.pb_finder_lb.update_core(bar_index, o, h, l, c)
            self.pb_finder_ub.update_core(bar_index, o, h, l, c)

        self.update_core(bar_index, o, h, l, c)

    def enforce_lookback(self, current_bar_index: int, lookback: int):
        """Lookback 기간을 초과한 추세 초기화"""
        if self.biggest_move and self.biggest_move.start_bar <= current_bar_index - lookback:
            self.flush()

    def flush(self):
        """추적기 상태 초기화"""
        self.biggest_move = None
        self.biggest_pb_lb = None
        self.biggest_pb_ub = None
        self.start_bar = None
        self.start_price = None
        self.renew_pullback_finders()


def directional_min_allowing_na(direction: DirectionType, a: Optional[PriceType], b: Optional[PriceType]) -> Optional[PriceType]:
    """Pine Script의 directionalMinAllowingNA 구현 (Decimal 타입 처리)"""
    if a is None:
        return b
    if b is None:
        return a
    
    if direction < 0:
        return max(a, b)
    else:
        return min(a, b)

# --- 메인 지표 실행 함수 ---

def pullback_analyzer(
    opens: List[PriceType],
    highs: List[PriceType],
    lows: List[PriceType],
    closes: List[PriceType],
    lookback: int = 50
) -> List[dict]:
    """
    Pullback Analyzer 지표의 핵심 로직을 실행하는 함수.
    """
    
    data_length = len(opens)
    if not (data_length == len(highs) == len(lows) == len(closes)):
        raise ValueError("모든 입력 가격 리스트의 길이가 동일해야 합니다.")

    # [핵심 수정 1]: 최대 인덱스 계산 (데이터를 0부터 시작하는 인덱스에서 역순 인덱스로 변환하기 위함)
    max_index = data_length - 1 

    up_finder = MoveFinder(1, is_pullback_finder=False)
    down_finder = MoveFinder(-1, is_pullback_finder=False)
    
    results = []

    for i in range(data_length):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        bar_index = i # 실제 계산 및 MoveFinder에는 0부터 시작하는 원본 인덱스를 사용
        
        # [핵심 수정 2]: 출력용 역순 인덱스 계산
        display_bar_index = max_index - bar_index
        
        up_finder.update(bar_index, o, h, l, c)
        down_finder.update(bar_index, o, h, l, c)

        up_finder.enforce_lookback(bar_index, lookback)
        down_finder.enforce_lookback(bar_index, lookback)
        
        move_up = up_finder.biggest_move
        move_down = down_finder.biggest_move
        
        result = {
            'bar_index': display_bar_index, # [수정] 역순 인덱스 사용 (마지막 봉 = 0)
            'up_move': None,
            'down_move': None,
        }
        
        if move_up:
            result['up_move'] = {
                'size': move_up.size(),
                # [핵심 수정 3]: MoveFinder의 start_bar, end_bar에 역순 변환 적용
                'start_bar': max_index - move_up.start_bar,
                'end_bar': max_index - move_up.end_bar,
                'start_price': move_up.start_price,
                'end_price': move_up.end_price,
                'pb_lb_size': abs(up_finder.biggest_pb_lb.size()) if up_finder.biggest_pb_lb else Decimal('0.0'),
                'pb_ub_size': abs(up_finder.biggest_pb_ub.size()) if up_finder.biggest_pb_ub else Decimal('0.0'),
            }
        
        if move_down:
            result['down_move'] = {
                'size': move_down.size(),
                # [핵심 수정 4]: MoveFinder의 start_bar, end_bar에 역순 변환 적용
                'start_bar': max_index - move_down.start_bar,
                'end_bar': max_index - move_down.end_bar,
                'start_price': move_down.start_price,
                'end_price': move_down.end_price,
                'pb_lb_size': abs(down_finder.biggest_pb_lb.size()) if down_finder.biggest_pb_lb else Decimal('0.0'),
                'pb_ub_size': abs(down_finder.biggest_pb_ub.size()) if down_finder.biggest_pb_ub else Decimal('0.0'),
            }
        
        results.append(result)

    return results

# PullbackAnalyzer 클래스는 호출 구조에 맞게 TradingEngine에서 인스턴스화됩니다.
class PullbackAnalyzer:
    """
    트레이딩 엔진에서 사용하기 위해 분석 결과를 인스턴스 변수로 저장하고 반환하는 클래스.
    """
    def __init__(self, opens, highs, lows, closes):
        lookback_period = 50 

        # 결과 실행
        analysis_results = pullback_analyzer(opens, highs, lows, closes, lookback_period)
        
        # 결과를 인스턴스 변수에 저장
        self.results: List[dict] = analysis_results
        self.last_result: dict = analysis_results[-1]
        
        # 출력 로직: 마지막 봉의 인덱스는 이제 0으로 표시됩니다.
        final_result = self.last_result
        # print(f"--- 마지막 봉 ({final_result['bar_index']}) 분석 결과 ---") # 'bar_index'는 이미 역순 (0)

        # if final_result['up_move']:
        #     up_move = final_result['up_move']
        #     print(f"🟢 상승 추세: {up_move['size']:.2f}% (바 {up_move['start_bar']} ~ {up_move['end_bar']})")
        #     print(f"   PB (되돌림): {up_move['pb_lb_size']:.2f}% ~ {up_move['pb_ub_size']:.2f}% (상한을 트레일링 스톱 기준으로 사용)")

        # if final_result['down_move']:
        #     down_move = final_result['down_move']
        #     print(f"🔴 하락 추세: {down_move['size']:.2f}% (바 {down_move['start_bar']} ~ {down_move['end_bar']})")
        #     print(f"   PB (되돌림): {down_move['pb_lb_size']:.2f}% ~ {down_move['pb_ub_size']:.2f}%")

    def get_last_analysis(self) -> dict:
        """가장 최근에 계산된 분석 결과를 반환합니다."""
        return self.last_result

    def get_all_results(self) -> List[dict]:
        """모든 봉에 대한 분석 결과를 반환합니다."""
        return self.results