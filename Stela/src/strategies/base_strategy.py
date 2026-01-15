

class BaseStrategy:
    def __init__(self):
        # 모든 전략이 공통으로 사용할 데이터 변수
        self.opens = None
        self.highs = None
        self.lows = None
        self.closes = None

    def update_data(self, data: dict):
        """
        TradingEngine으로부터 Numpy 배열을 전달받아 업데이트합니다.
        일일이 모든 전략에 만들 필요 없이 이 함수를 상속받아 사용합니다.
        """
        self.opens = data['opens']
        self.highs = data['highs']
        self.lows = data['lows']
        self.closes = data['closes']