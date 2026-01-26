import logging
from collections import deque
from ..shared.typings import *
from ..config import KLINE_LIMIT
from ..shared.enums import Side, PositionSide, AlgoOrderType, AlgoOrderEventStatus, KlineInterval
import numpy as np
from ..shared.state_manager import BalanceState, PositionState


logger = logging.getLogger("MARKET_DATA")


class SetupError(Exception):
    """Initial setup failed."""
    pass

class MarketDataProcessor:
    def __init__(self, binance_client, symbol, kline_interval:KlineInterval, setup_data):

        self.client = binance_client
        self.symbol = symbol
        self.kline_interval = kline_interval

        # 1. 수수료 데이터 초기화
        fee_data = setup_data.get('bnb_fee_data', [])
        # 캔들 방식과 동일하게 deque로 저장하되 maxlen은 주지 않습니다 (7일 기준 직접 삭제)
        self.bnb_fee_history = deque(fee_data) 

        # 초기 7일 합계 계산
        self.total_7d_bnb_fee = sum(Decimal(str(item[1])) for item in fee_data)

        # 2. 기존 캔들 데이터 초기화
        ohlc_prices = setup_data.get('ohlc_prices')
        self.initialize_candle_data(ohlc_prices=ohlc_prices, maxlen=KLINE_LIMIT)

        # Initialize State
        self.balances = BalanceState()
        self.positions = PositionState()
        self.update_balance(showLog=True)
        self.update_position(showLog=True)

        self.show_bnb_survival_report()

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

    def initialize_candle_data(self, ohlc_prices, maxlen):
        self.open_prices = deque([item[0] for item in ohlc_prices], maxlen=maxlen)
        self.high_prices = deque([item[1] for item in ohlc_prices], maxlen=maxlen)
        self.low_prices = deque([item[2] for item in ohlc_prices], maxlen=maxlen)
        self.close_prices = deque([item[3] for item in ohlc_prices], maxlen=maxlen)

    def update_candle_data(self, ohlc_data) -> Tuple[Deque[Decimal], Deque[Decimal], Deque[Decimal], Deque[Decimal]]:
        """
        Appends the latest OHLC (Open, High, Low, Close) data to the price deques.

        The function leverages the 'maxlen' property of collections.deque to 
        automatically manage the fixed-size lookback window (FIFO structure), 
        ensuring O(1) time complexity for data updates.

        Args:
            ohlc_data (dict): A dictionary containing the latest OHLC data 
                            (keys 'o', 'h', 'l', 'c').

        Returns:
            tuple: A tuple containing the updated (open_prices, high_prices, 
                low_prices, close_prices) deques.
        """
        # Append the new OHLC values. 
        # Using Decimal conversion ensures high precision for financial calculations.
        # The maxlen property automatically removes the oldest element (popleft) upon append.

        self.open_prices.append(Decimal(str(ohlc_data.get('o'))))
        self.high_prices.append(Decimal(str(ohlc_data.get('h'))))
        self.low_prices.append(Decimal(str(ohlc_data.get('l'))))
        self.close_prices.append(Decimal(str(ohlc_data.get('c'))))

        # Lookback Window Management is now handled automatically by deque's maxlen.
        # The previous O(N) checking and pop(0) logic is safely removed.

        # Return the final, updated, and fixed-size candle deques for indicator calculation.

        return self.open_prices, self.high_prices, self.low_prices, self.close_prices

    def update_balance(self, showLog:bool = True):
        try:
            self.balances.reset()
            self.balances.balance, self.balances.available_balance, self.balances.bnb_balance = self.client.futures_account_balance()
            if showLog:
                logger.info(f"Balance successfully updated. Balance: {self.balances.balance:.2f} Available balance: {self.balances.available_balance:.2f}")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def update_position(self, symbol:str = None, showLog:bool = False):
        '''
        Docstring for update_position
        
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
                                default_stop_loss = self.client.get_futures_default_stop_loss(symbol, self.kline_interval, PositionSide.LONG, long_time)

                                if showLog:
                                    logger.info(f"{self.symbol} [LONG-Position] amount:{amount}, default_stop_loss: {default_stop_loss:.4f}, entry: {entry_price:.4f}")

                                self.positions.long_amount = amount
                                self.positions.long_entry_price = entry_price
                                self.positions.long_default_stop_loss = default_stop_loss

                            elif side == PositionSide.SHORT.value:
                                default_stop_loss = self.client.get_futures_default_stop_loss(symbol, self.kline_interval, PositionSide.SHORT, short_time)

                                if showLog:
                                    logger.info(f"{self.symbol} [SHORT-Position] amount:{amount}, default_stop_loss: {default_stop_loss:.4f}, entry: {entry_price:.4f}")

                                self.positions.short_amount = amount
                                self.positions.short_entry_price = entry_price
                                self.positions.short_default_stop_loss = default_stop_loss

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

            # self.positions.long_fee, self.positions.short_fee = self.client.futures_trade_fees(symbol)

        except Exception as e:
            logger.error(f"Failed to update position: {e}", exc_info=True)

    def get_analysis_data(self) -> dict:
        """
        현재 보유한 deque 데이터를 분석용 Numpy 배열로 변환하여 반환합니다.
        (Shared Memory 효과를 위해 여기서 한 번만 변환)
        """
        return {
            'opens': np.array(self.open_prices, dtype=np.float64),
            'highs': np.array(self.high_prices, dtype=np.float64),
            'lows': np.array(self.low_prices, dtype=np.float64),
            'closes': np.array(self.close_prices, dtype=np.float64)
        }