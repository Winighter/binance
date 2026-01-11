import logging
from decimal import Decimal
from typing import List, Dict, Any
from ..strategies.trading_params import RISK_REWARD_RAITO, MAX_STOP_LOSS_RATIO, MAX_POSITION_RATIO
from src.shared.utils import *
from ..shared.enums import PositionSide

logger = logging.getLogger("TRADING_SIMULATOR")

class TradeSimulator:
    def __init__(self, order_manager, symbol, leverage:int):
        self.order_manager = order_manager
        self.symbol = symbol
        self.leverage = Decimal(str(leverage))
        self.rr_ratio = Decimal(str(RISK_REWARD_RAITO))
        self.max_sl_ratio = Decimal(str(MAX_STOP_LOSS_RATIO))
        self.PCT_100 = Decimal('100')

        self.stepSize = Decimal('0')

        self.sim_balance = Decimal('700')

        # logger.info(f"Simulation Balance: {self.sim_balance} $")
        
        # 3번 개선: 출력 주기 관리를 위한 카운터
        self.run_count = 0
        self.display_interval = 1  # 10번 실행마다 1번 요약 출력 (필요시 조절 가능)

    def run(self, long_signals, short_signals, highs, lows, stepSize, show_detail=False):
        self.run_count += 1
        self.stepSize = stepSize

        # list(highs)로 복사하지 않고 deque를 직접 전달 (메모리 절약)
        long_stats = self._calculate_side_outcomes("Long", long_signals, highs, lows, show_detail)
        short_stats = self._calculate_side_outcomes("Short", short_signals, highs, lows, show_detail)

        if show_detail or (self.run_count % self.display_interval == 0):
            self._print_summary(long_stats, short_stats)

    def _calculate_side_outcomes(self, side: str, signals: List, highs: List[Decimal], lows: List[Decimal], show_detail: bool) -> Dict[str, Any]:

        win_count = Decimal('0')
        total_profit = Decimal('0')
        tp_sum = Decimal('0')
        sl_sum = Decimal('0')
        tp_count = Decimal('0')
        sl_count = Decimal('0')
        
        # 신호 정렬 및 데이터 길이 확인
        sorted_signals = sorted(signals, key=lambda x: x[0])
        total_len = len(highs) # 전체 캔들 길이
        results_count = len(sorted_signals)
        last_exit_idx = -1 

        for sig in sorted_signals:
            start_idx = int(sig[0])
            
            if start_idx <= last_exit_idx:
                continue

            sig_sl = Decimal(str(sig[1]))
            sig_entry = Decimal(str(sig[2]))
            sig_tp = Decimal(str(sig[3]))

            result = "PENDING"
            profit = Decimal('0')
            end_idx = -1 

            for i in range(start_idx + 1, total_len):
                if side == "Long":
                    if lows[i] <= sig_sl:
                        result, end_idx = "SL", i
                        profit = ((sig_sl - sig_entry) / sig_entry) * self.PCT_100 * self.leverage
                        pnl = (sig_sl - sig_entry)
                        break
                    elif highs[i] >= sig_tp:
                        result, end_idx = "TP", i
                        profit = ((sig_tp - sig_entry) / sig_entry) * self.PCT_100 * self.leverage
                        pnl = (sig_tp - sig_entry)
                        break
                else: # Short
                    if highs[i] >= sig_sl:
                        result, end_idx = "SL", i
                        profit = ((sig_entry - sig_sl) / sig_entry) * self.PCT_100 * self.leverage
                        pnl = (sig_entry - sig_sl)
                        break
                    elif lows[i] <= sig_tp:
                        result, end_idx = "TP", i
                        profit = ((sig_entry - sig_tp) / sig_entry) * self.PCT_100 * self.leverage
                        pnl = (sig_entry - sig_tp)
                        break

            if result != "PENDING":
                last_exit_idx = end_idx
                
                if result == "TP":
                    win_count += 1
                    tp_sum += profit
                    tp_count += 1
                else:
                    sl_sum += profit
                    sl_count += 1
                total_profit += profit

                if side == 'Long':
                    amount = self.get_position_quantity(PositionSide.LONG, sig_entry, sig_sl)
                elif side == 'Short':
                    amount = self.get_position_quantity(PositionSide.SHORT, sig_entry, sig_sl)
                
                roi = amount * pnl
                self.sim_balance += roi

                if show_detail:
                    # ⭐️ 헷갈리지 않게 "현재로부터 몇 봉 전인지"로 계산
                    # start_ago: 진입 시점, end_ago: 청산 시점
                    start_ago = total_len - 1 - start_idx
                    end_ago = total_len - 1 - end_idx

                    logger.info(
                        f"🔍 [Detail] {side:5} | "
                        f"BArs Ago: {start_ago:5} -> {end_ago:5} | "
                        f"Quantity: {amount:.2f} | "
                        f"SL: {sig_sl:8.4f} | Entry: {sig_entry:8.4f} | TP: {sig_tp:8.4f} | "
                        f"Result: {result:2} ({profit:6.2f}%) | PNL: {pnl:.4f} | ROI: {roi:.4f} | "
                        f"Balance: {self.sim_balance:.2f} | "
                    )

        return {
            "win_count": win_count, "total_count": results_count,
            "completed_count": tp_count + sl_count, "total_profit": total_profit,
            "avg_tp": tp_sum / tp_count if tp_count > 0 else Decimal('0'),
            "avg_sl": sl_sum / sl_count if sl_count > 0 else Decimal('0'),
            "tp_sum": tp_sum, "sl_sum": sl_sum, "tp_count": tp_count, "sl_count": sl_count
        }

    def _print_summary(self, long_stats: dict, short_stats: dict):
        def format_stats(stats, label):
            total = stats["total_count"]
            completed = stats["completed_count"]
            if total == 0: return f"{label} No Data".center(75)
            
            win_rate = (Decimal(str(stats["win_count"])) / Decimal(str(completed)) * self.PCT_100) if completed > 0 else Decimal('0')
            return (f"{label} WinRate: {win_rate:>5.1f}% | AvgTP: {stats['avg_tp']:>6.2f}% | "
                    f"AvgSL: {stats['avg_sl']:>6.2f}% | Net: {stats['total_profit']:>7.2f}% | Trades: {completed}/{total}")

        total_completed = long_stats["completed_count"] + short_stats["completed_count"]
        total_win = long_stats["win_count"] + short_stats["win_count"]
        total_tp_count = long_stats["tp_count"] + short_stats["tp_count"]
        total_sl_count = long_stats["sl_count"] + short_stats["sl_count"]
        
        total_avg_tp = (long_stats["tp_sum"] + short_stats["tp_sum"]) / Decimal(str(total_tp_count)) if total_tp_count > 0 else Decimal('0')
        total_avg_sl = (long_stats["sl_sum"] + short_stats["sl_sum"]) / Decimal(str(total_sl_count)) if total_sl_count > 0 else Decimal('0')
        total_win_rate = (Decimal(str(total_win)) / Decimal(str(total_completed)) * self.PCT_100) if total_completed > 0 else Decimal('0')
        total_net = long_stats["total_profit"] + short_stats["total_profit"]

        # 출력부 가독성 강화
        logger.info("=" * 90)
        logger.info(f"📊 [SIMULATION SUMMARY] Run #{self.run_count}")
        logger.info(f"⚙️  RR: {self.rr_ratio} | MaxSL: {self.max_sl_ratio}% | Leverage: {self.leverage}x | Balance: {self.sim_balance:.2f} | ")
        logger.info("-" * 90)
        logger.info(format_stats(long_stats, "🔵 [LONG] "))
        logger.info(format_stats(short_stats, "🔴 [SHORT]"))
        logger.info("-" * 90)
        
        profit_icon = "🚀" if total_net > 0 else "📉"
        total_msg = (f"🏆 [TOTAL] WinRate: {total_win_rate:>5.1f}% | AvgTP: {total_avg_tp:>6.2f}% | "
                     f"AvgSL: {total_avg_sl:>6.2f}% | Net: {total_net:>7.2f}% {profit_icon}")
        logger.info(total_msg)
        logger.info("=" * 90)

    def get_position_quantity(self, position:PositionSide, price: Decimal, stop_loss_price: Decimal):

        if position not in [PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f'Invalid value: {position}')
        try:
            price_leverage = self.leverage * price
            max_position_value = self.sim_balance * self.leverage * Decimal(str(MAX_POSITION_RATIO / 100))

            if position == PositionSide.LONG:
                quantity = self.order_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.sim_balance,
                    stop_loss_price=stop_loss_price,
                    position_side=position
                )
                if quantity > 0:
                    # 2. 포지션 규모(총 가치) 계산
                    position_value = quantity * price_leverage

                    # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.sim_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = round_step_size(new_quantity, self.stepSize)
                            return adjusted_quantity

                    adjusted_quantity = round_step_size(quantity, self.stepSize)
                    return adjusted_quantity
                else:
                    logger.warning(f"Order skipped for {self.symbol} due to filter constraints.")

            elif position == PositionSide.SHORT:
                quantity = self.order_manager.calculate_quantity_with_risk_management(
                    price=price,
                    symbol=self.symbol,
                    balance_usdt=self.sim_balance,
                    stop_loss_price=stop_loss_price,
                    position_side=position
                )
                if quantity > 0:
                    # 2. 포지션 규모(총 가치) 계산
                    position_value = quantity * price_leverage

                    # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
                    if position_value > max_position_value:
                        # 현재 이용가능한 자산이 있는지 확인
                        if max_position_value < (self.sim_balance * self.leverage):
                            # 상한선에 맞게 새로운 수량 계산
                            new_quantity = max_position_value / price
                            # 5. 수량 정밀도에 맞게 조정
                            adjusted_quantity = round_step_size(new_quantity, self.stepSize)
                            return adjusted_quantity

                    adjusted_quantity = round_step_size(quantity, self.stepSize)
                    return adjusted_quantity
                else:
                    logger.warning(f"Order skipped for {self.symbol} due to filter constraints.")

        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0
