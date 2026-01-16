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

        self.sim_balance = Decimal('400')

        # logger.info(f"Simulation Balance: {self.sim_balance} $")


    def run(self, long_signals:List, short_signals:List, highs, lows, stepSize, show_detail=False):

        '''
        signal = [index, stop loss, entry, take profit]
        '''
        self.stepSize = stepSize

        # 1. 모든 신호를 하나로 통합
        combined_signals = []
        for sig in long_signals:
            combined_signals.append(("Long", sig))
        for sig in short_signals:
            combined_signals.append(("Short", sig))

        # 2. 통합 시뮬레이션 실행
        stats = self._calculate_combined_outcomes(combined_signals, highs, lows, show_detail)

        # 3. 요약 출력
        self._print_summary(stats['long'], stats['short'])

    def _calculate_combined_outcomes(self, combined_signals: List, highs: List[Decimal], lows: List[Decimal], show_detail: bool) -> Dict[str, Any]:
        stats = {
            "long": self._init_stats_dict(),
            "short": self._init_stats_dict()
        }
        total_len = len(highs)
        trade_events = []
        
        # 동일 포지션 중복 진입 방지를 위한 마지막 청산 인덱스 관리
        last_long_exit_idx = -1
        last_short_exit_idx = -1

        # 1. 신호를 진입 시점(start_idx) 순으로 정렬하여 검토
        sorted_signals = sorted(combined_signals, key=lambda x: x[1][0])

        for side, sig in sorted_signals:
            start_idx = int(sig[0])

            # [중복 제거 로직] 현재 포지션이 종료되기 전의 동일 방향 신호는 무시 
            if side == "Long" and start_idx <= last_long_exit_idx:
                continue
            if side == "Short" and start_idx <= last_short_exit_idx:
                continue

            sig_sl = Decimal(str(sig[1]))
            sig_entry = Decimal(str(sig[2]))
            sig_tp = Decimal(str(sig[3]))

            # logger.info(f"[{side}-{total_len-start_idx}] SL: {sig_sl} | Entry: {sig_entry} | TP: {sig_tp}")

            result, end_idx, profit_pct, pnl_unit = "PENDING", -1, Decimal('0'), Decimal('0')

            # 시장 움직임 시뮬레이션
            for i in range(start_idx + 1, total_len):
                if side == "Long":
                    if lows[i] <= sig_sl:
                        result, end_idx = "SL", i
                        profit_pct = ((sig_sl - sig_entry) / sig_entry) * self.PCT_100 * self.leverage
                        pnl_unit = (sig_sl - sig_entry)
                        # logger.info(f"{side} [{total_len-start_idx}-{total_len-i}] {result}: {sig_sl} | Exit: {lows[i]}")
                        break
                    elif highs[i] >= sig_tp:
                        result, end_idx = "TP", i
                        profit_pct = ((sig_tp - sig_entry) / sig_entry) * self.PCT_100 * self.leverage
                        pnl_unit = (sig_tp - sig_entry)
                        # logger.info(f"{side} [{total_len-start_idx}-{total_len-i}] {result}: {sig_tp} | Exit: {highs[i]}")
                        break
                else: # Short
                    if highs[i] >= sig_sl:
                        result, end_idx = "SL", i
                        profit_pct = ((sig_entry - sig_sl) / sig_entry) * self.PCT_100 * self.leverage
                        pnl_unit = (sig_entry - sig_sl)
                        # logger.info(f"{side} [{total_len-start_idx}-{total_len-i}] {result}: {sig_sl} | Exit: {highs[i]}")
                        break
                    elif lows[i] <= sig_tp:
                        result, end_idx = "TP", i
                        profit_pct = ((sig_entry - sig_tp) / sig_entry) * self.PCT_100 * self.leverage
                        pnl_unit = (sig_entry - sig_tp)
                        # logger.info(f"{side} [{total_len-start_idx}-{total_len-i}] {result}: {sig_tp} | Exit: {lows[i]}")
                        break

            # 이미 종료된 포지션 거래 내역 (아직 보유중은 제외)
            if result != "PENDING":
                # 청산 시점 업데이트 (동일 방향의 다음 진입을 막기 위함)
                if side == "Long":
                    last_long_exit_idx = end_idx
                else:
                    last_short_exit_idx = end_idx

                trade_events.append({
                    "side": side, "start_idx": start_idx, "end_idx": end_idx,
                    "result": result, "profit_pct": profit_pct, "pnl_unit": pnl_unit,
                    "entry": sig_entry, "sl": sig_sl, "tp": sig_tp
                })
            # if result == "PENDING":
            #     logger.info(f"{side} {total_len-start_idx}")

        # 2. 거래 종료 시점(end_idx) 기준으로 다시 정렬하여 잔고 업데이트 (시간순 출력) 
        trade_events.sort(key=lambda x: x["end_idx"])

        for ev in trade_events:
            side = ev["side"]
            s_key = side.lower()
            pos_side = PositionSide.LONG if side == "Long" else PositionSide.SHORT

            amount = self.get_position_quantity(pos_side, ev["entry"], ev["sl"])
            roi = amount * ev["pnl_unit"]
            self.sim_balance += roi

            if ev["result"] == "TP":
                stats[s_key]["win_count"] += 1
                stats[s_key]["tp_sum"] += ev["profit_pct"]
                stats[s_key]["tp_count"] += 1
            else:
                stats[s_key]["sl_sum"] += ev["profit_pct"]
                stats[s_key]["sl_count"] += 1
            
            stats[s_key]["total_profit"] += ev["profit_pct"]
            stats[s_key]["completed_count"] += 1

            if show_detail:
                start_ago = total_len - ev["start_idx"]
                end_ago = total_len - ev["end_idx"]
                logger.info(
                    f"🔍 [Detail] {side:5} | "
                    f"Bars Ago: {start_ago:5} -> {end_ago:5} | "
                    f"Quantity: {amount:.2f} | "
                    f"SL: {ev['sl']:8.4f} | Entry: {ev['entry']:8.4f} | TP: {ev['tp']:8.4f} | "
                    f"Result: {ev['result']:2} ({ev['profit_pct']:6.2f}%) | PNL: {ev['pnl_unit']:.4f} | ROI: {roi:.4f} | "
                    f"Balance: {self.sim_balance:.2f} | "
                )

        # 평균 통계 계산
        for k in ["long", "short"]:
            s = stats[k]
            s["avg_tp"] = s["tp_sum"] / s["tp_count"] if s["tp_count"] > 0 else Decimal('0')
            s["avg_sl"] = s["sl_sum"] / s["sl_count"] if s["sl_count"] > 0 else Decimal('0')
            s["total_count"] = len([x for x in combined_signals if x[0].lower() == k])

        return stats

    def _init_stats_dict(self):
        return {
            "win_count": Decimal('0'), "total_count": 0, "completed_count": 0,
            "total_profit": Decimal('0'), "tp_sum": Decimal('0'), "sl_sum": Decimal('0'),
            "tp_count": Decimal('0'), "sl_count": Decimal('0'), "avg_tp": Decimal('0'), "avg_sl": Decimal('0')
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
