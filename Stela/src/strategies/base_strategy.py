class BaseStrategy:
    def __init__(self):
        self.ltf_opens = None
        self.ltf_highs = None
        self.ltf_lows = None
        self.ltf_closes = None
        self.ltf_timestamps = None
        self.ltf_sessions = None

        self.mtf_opens = None
        self.mtf_highs = None
        self.mtf_lows = None
        self.mtf_closes = None
        self.mtf_timestamps = None
        self.mtf_sessions = None

        self.htf_opens = None
        self.htf_highs = None
        self.htf_lows = None
        self.htf_closes = None
        self.htf_timestamps = None
        self.htf_sessions = None

    def update_data(self, ltf_data: dict, mtf_data: dict, htf_data: dict, mtf_ltf_ratio:int):
        """
        TradingEngine으로부터 Numpy 배열을 전달받아 업데이트합니다.
        일일이 모든 전략에 만들 필요 없이 이 함수를 상속받아 사용합니다.
        """
        self.ltf_timestamps = ltf_data['timestamps']
        self.ltf_opens = ltf_data['opens']
        self.ltf_highs = ltf_data['highs']
        self.ltf_lows = ltf_data['lows']
        self.ltf_closes = ltf_data['closes']
        self.ltf_sessions = ltf_data['sessions']

        self.mtf_timestamps = mtf_data['timestamps']
        self.mtf_opens = mtf_data['opens']
        self.mtf_highs = mtf_data['highs']
        self.mtf_lows = mtf_data['lows']
        self.mtf_closes = mtf_data['closes']
        self.mtf_sessions = mtf_data['sessions']

        self.htf_timestamps = htf_data['timestamps']
        self.htf_opens = htf_data['opens']
        self.htf_highs = htf_data['highs']
        self.htf_lows = htf_data['lows']
        self.htf_closes = htf_data['closes']
        self.htf_sessions = htf_data['sessions']