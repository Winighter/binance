import logging
from collections import deque
from ..shared.typings import *
from ..config import KLINE_LIMIT
from ..shared.enums import Side, PositionSide, AlgoOrderType, AlgoOrderEventStatus, KlineInterval
import numpy as np
from ..shared.state_manager import BalanceState, PositionState
from datetime import datetime
from ..shared.models import OHLCV_DT
import pytz
from ..shared.utils import get_session_label


logger = logging.getLogger("MARKET_DATA")


class SetupError(Exception):
    """Initial setup failed."""
    pass

class MarketDataProcessor:
    def __init__(self, binance_client, symbol, kline_intervals:KlineInterval, setup_data):

        self.client = binance_client
        self.symbol = symbol
        self.kline_intervals = kline_intervals

        # 1. 수수료 데이터 초기화
        fee_data = setup_data.get('bnb_fee', [])
        self.bnb_fee_history = deque(fee_data) 
        self.total_7d_bnb_fee = sum(Decimal(str(item[1])) for item in fee_data)

        # 2. 기존 캔들 데이터 초기화
        ohlcv = setup_data.get('ohlcv', {})
        self.initialize_candle_data(ohlcv)

        # Initialize State
        self.balances = BalanceState()
        self.positions = PositionState()
        self.initialize_balance(True)
        self.initialize_position()

        # self.show_bnb_survival_report()

    def log_refined_range(self, interval_code, start_ts, count=3):
        if interval_code not in self.candles:return

        data = self.candles[interval_code]
        try:
            # 1. deque를 리스트로 변환하여 타임스탬프 인덱스 검색
            indices = np.where(data['timestamp'] == int(start_ts))[0]
            if len(indices) == 0: raise ValueError
            start_idx = indices[0]

            # 슬라이싱 작업 (NumPy는 바로 슬라이싱이 가능함)
            target_data = data[start_idx : start_idx + count]
            
            # 3. 시간 가독성 처리 (ms -> HH:MM:SS)
            readable_times = [datetime.fromtimestamp(t/1000).strftime('%H:%M:%S')for t in target_data['timestamp']]
            
            # 4. 로그 출력
            logger.info(f"[REFINE] {interval_code} | Range: {readable_times} | Highs: {target_data['high']}")
            return target_data['high']
            
        except ValueError:
            logger.error(f"[REFINE] 타임스탬프 {start_ts}를 {interval_code}에서 찾을 수 없습니다.")
            return None

    def get_analysis_data(self, interval_code) -> dict:
        """
        이미 NumPy 배열이므로, 별도의 변환 없이 컬럼명(키값)으로 접근하여 반환합니다.

        interval_code 는 데이터를 분류하는 형식의 키값이고 그에 맞는 데이터를 리턴하는 함수
        그에 맞는 데이터를 반환하는 함수이므로 분석이나 데이터를 가공하는 함수는 아니다.
        """
        if interval_code not in self.candles:
            return {}

        target = self.candles[interval_code]

        return {
            'timestamps': target['timestamp'],
            'opens': target['open'],
            'highs': target['high'],
            'lows': target['low'],
            'closes': target['close'],
            'volumes': target['volume'],
            'sessions': target['session']
        }

    def show_bnb_survival_report(self):
        """Calculates and logs the BNB survival report using ASCII characters for compatibility."""
        daily_avg = self.total_7d_bnb_fee / Decimal('7')
        current_bnb = self.balances.bnb_balance if self.balances.bnb_balance is not None else Decimal('0')
        # ASCII 기반 구분선 및 제목
        logger.info("========================================")
        logger.info(">>> [BNB FEE SYSTEM STARTUP REPORT] <<<")
        
        if daily_avg > 0:
            remaining_days = current_bnb / daily_avg if current_bnb > 0 else Decimal('0')
            # 기호 변경: • -> [-], 🚀 -> >>>
            logger.info(f" [-] Current BNB Balance    : {current_bnb:.8f} BNB")
            logger.info(f" [-] Daily Avg Consumption  : {daily_avg:.8f} BNB/day")
            logger.info(f" [-] Estimated Survival     : {remaining_days:.2f} Days")
            
            if remaining_days < 2:
                # ⚠️ 대신 [!] 또는 [WARNING] 사용
                logger.warning(" [!] Status: CRITICAL - Please top up BNB soon!")
            else:
                # ✅ 대신 [OK] 사용
                logger.info(" [+] Status: HEALTHY - Balance is sufficient.")
        else:
            logger.info(f" [-] Current BNB Balance    : {current_bnb:.8f} BNB")
            logger.info(" [-] Status: No trade history found in the last 7 days.")
            
        logger.info("========================================")

    def update_bnb_fee_realtime(self, ts, fee) -> Decimal:
        """실시간 체결 시 호출되어 7일 평균을 갱신합니다."""
        fee = Decimal(str(fee))
        
        # [A] 동일 타임스탬프 합산 로직 (사용자님 의견 반영)
        if self.bnb_fee_history and self.bnb_fee_history[-1][0] == ts:
            old_ts, old_fee = self.bnb_fee_history.pop()
            self.bnb_fee_history.append([ts, old_fee + fee])
        else:
            self.bnb_fee_history.append([ts, fee])
        
        self.total_7d_bnb_fee += fee

        # [B] 7일 지난 데이터 삭제 (Sliding Window)
        seven_days_ms = 7 * 24 * 60 * 60 * 1000
        while self.bnb_fee_history and (ts - self.bnb_fee_history[0][0] > seven_days_ms):
            _, old_fee = self.bnb_fee_history.popleft()
            self.total_7d_bnb_fee -= old_fee

        # [C] 현재의 일평균 소모량 계산 (분모)
        daily_avg = self.total_7d_bnb_fee / Decimal('7')
        
        # [D] 남은 시간(일) 계산
        if daily_avg > 0 and self.balances.bnb_balance:
            return Decimal(str(self.balances.bnb_balance / daily_avg))
        return Decimal('999') # 소모량 없으면 무한대

    def initialize_candle_data(self, ohlcv: Dict):
        """
        각 인터벌의 배수에 맞춰 deque의 maxlen을 설정하고 데이터를 채웁니다.
        """
        self.candles = {}

        valid_intervals = [x for x in self.kline_intervals if x is not None]

        for interval in valid_intervals:
            if interval is None: continue

            code = interval.code

            if code in ohlcv:
                # [핵심] setup_manager가 이미 NumPy 배열로 만들어 줬으므로 
                # 루프를 돌며 append할 필요 없이 바로 할당합니다.
                self.candles[code] = ohlcv[code]

    def update_candle_data(self, ohlcv):
        """
        봉 마감 시점에 호출되어, 해당 인터벌의 가격 데이터를 즉시 추가합니다.
        """
        try:
            interval_code = ohlcv.get('i')
            if interval_code not in self.candles:return

            new_ts = int(ohlcv.get('t'))

            session_label = get_session_label(new_ts)

            target_data = self.candles[interval_code]

            # [중요] 중복 타임스탬프 체크
            if len(target_data) > 0 and target_data['timestamp'][-1] == new_ts:
                # 이미 존재하는 봉이면 업데이트할지, 무시할지 결정 (보통 마감 데이터면 무시)
                return self.get_analysis_data(interval_code)

            # 1. 새 데이터를 튜플 형태로 만들어 NumPy 레코드 생성
            # update_candle_data 내부의 1번 로직 최적화 버전
            new_entry = np.array([
                (
                    int(ohlcv.get('t')),
                    float(ohlcv.get('o')),
                    float(ohlcv.get('h')),
                    float(ohlcv.get('l')),
                    float(ohlcv.get('c')),
                    float(ohlcv.get('v')), # 'v'가 일반적인 거래량(Base asset)입니다.
                    session_label
                )
            ], dtype=OHLCV_DT)

            # 2. 기존 배열 끝에 붙이기 (반드시 다시 할당)
            self.candles[interval_code] = np.concatenate([self.candles[interval_code], new_entry])

            return self.get_analysis_data(interval_code)

        except Exception as e:
            logger.error(f"update_candle_data 오류: {e}", exc_info=True)

    def initialize_balance(self, showLog:bool = False):
        try:
            self.balances.reset()
            self.balances.balance, self.balances.available_balance, self.balances.bnb_balance = self.client.futures_account_balance()
            if showLog:
                logger.info(f"Balance: {self.balances.balance:.2f} | Available balance: {self.balances.available_balance:.2f}")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def initialize_position(self, symbol:str = None, showLog:bool = False):
        '''
        Docstring for initialize_position
        
        :param self: Description
        :param showLog: Description
        :type showLog: bool

        Updates the open position amount and entry price.
        '''
        long_open_id = None
        short_open_id = None
        long_time = None
        short_time = None
        try:
            trade_history = self.client.futures_account_trades(self.symbol)
            if trade_history:
                for th in trade_history:
                    symbol = th.get('symbol')
                    realizedPnl = Decimal(th.get('realizedPnl'))
                    if symbol == symbol and realizedPnl == 0:
                        side = th.get('side')
                        positionSide = th.get('positionSide')
                        orderId = th.get('orderId')
                        time = th.get('time')

                        if side == Side.BUY.value and positionSide == PositionSide.LONG.value and long_open_id != orderId:
                            long_open_id = orderId
                            long_time = time

                        elif side == Side.SELL.value and positionSide == PositionSide.SHORT.value and short_open_id != orderId:
                            short_open_id = orderId
                            short_time = time

            self.positions.reset()

            positions = self.client.futures_position_information(symbol)
            match positions:
                case None:
                    raise ValueError("Position data is missing.")

                case [*positions]:
                    for pos in positions:
                        if self.symbol != pos['symbol']:
                            continue
                        amount = Decimal(pos['positionAmt'])
                        amount = abs(amount)
                        side = str(pos['positionSide'])
                        entry_price = Decimal(pos['entryPrice'])
                        if amount > 0:

                            if side == PositionSide.LONG.value:

                                if showLog:
                                    logger.info(f"{self.symbol} [Initialize LONG-Position] amount:{amount}, entry: {entry_price:.4f}")

                                self.positions.long_amount = amount
                                self.positions.long_entry_price = entry_price

                            elif side == PositionSide.SHORT.value:

                                if showLog:
                                    logger.info(f"{self.symbol} [Initialize SHORT-Position] amount:{amount}, entry: {entry_price:.4f}")

                                self.positions.short_amount = amount
                                self.positions.short_entry_price = entry_price

            orders = self.client.futures_get_open_orders()
            if orders:
                for order in orders:
                    match order['algoStatus']:
                        case AlgoOrderEventStatus.NEW.value:
                            algoId = str(order['algoId'])
                            triggerPrice = Decimal(order['triggerPrice'])

                            match (order['positionSide'], order['side']):
                                case (PositionSide.LONG.value, Side.SELL.value):
                                    match order['orderType']:
                                        case AlgoOrderType.STOP_MARKET.value:
                                            if showLog:
                                                logger.info(f"[LONG-OPEN-ORDER] Stop-Market price: {triggerPrice}")
                                            self.positions.long_stop_loss = triggerPrice
                                            self.positions.long_stop_loss_order_id = algoId

                                        case AlgoOrderType.TAKE_PROFIT_MARKET.value:
                                            if showLog:
                                                logger.info(f"[LONG-OPEN-ORDER] Take-Profit price: {triggerPrice}")
                                            self.positions.long_take_profit = triggerPrice
                                            self.positions.long_take_profit_order_id = algoId

                                case (PositionSide.SHORT.value, Side.BUY.value):
                                    match order['orderType']:
                                        case AlgoOrderType.STOP_MARKET.value:
                                            if showLog:
                                                logger.info(f"[SHORT-OPEN-ORDER] Stop-Market price: {triggerPrice}")
                                            self.positions.short_stop_loss = triggerPrice
                                            self.positions.short_stop_loss_order_id = algoId

                                        case AlgoOrderType.TAKE_PROFIT_MARKET.value:
                                            if showLog:
                                                logger.info(f"[SHORT-OPEN-ORDER] Take-Profit price: {triggerPrice}")
                                            self.positions.short_take_profit = triggerPrice
                                            self.positions.short_take_profit_order_id = algoId
                        case _:
                                logger.warning(f"Unknown algo order status. {order['algoStatus']}")

        except Exception as e:
            logger.error(f"Failed to update position: {e}", exc_info=True)
