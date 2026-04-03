import logging
from ..shared.typings import *
from ..strategies.trading_params import MIN_RISK_REWARD_RAITO, MAX_STOP_LOSS_RATIO
from src.shared.utils import *
from ..shared.enums import PositionSide

logger = logging.getLogger("TRADING_SIMULATOR")

class TradeSimulator:
    def __init__(self, order_manager, symbol, leverage:int):
        self.order_manager = order_manager
        self.symbol = symbol
        self.leverage = Decimal(str(10))
        self.rr_ratio = Decimal(str(MIN_RISK_REWARD_RAITO))
        self.max_sl_ratio = Decimal(str(MAX_STOP_LOSS_RATIO))
        self.fee_rate = Decimal('0.00045') 
        self.PCT_100 = Decimal('100')
        self.sim_balance = Decimal('100')
        self.show_detail = bool(False)

    def run(self, execute_signals:List, highs, lows, stepSize):

        '''
        signal = [index, stop loss, entry, take profit]
        '''
        self.stepSize = stepSize
        self.tl = len(lows)

        # 2. 통합 시뮬레이션 실행
        stats = self._calculate_combined_outcomes(execute_signals, highs, lows)

        # 3. 요약 출력
        self._print_summary(stats['LONG'], stats['SHORT'])

    def _calculate_combined_outcomes(self, execute_signals: List, highs: List[Decimal], lows: List[Decimal]) -> Dict[str, Any]:
        stats = {
            "LONG": self._init_stats_dict(),
            "SHORT": self._init_stats_dict()
        }
        total_len = len(highs)
        trade_events = []

        total_fee_rate = self.fee_rate * 2
        
        # 동일 포지션 중복 진입 방지를 위한 마지막 청산 인덱스 관리
        last_exit_idx = -1

        # 1. 신호를 진입 시점(index) 순으로 정렬하여 검토
        sorted_signals = sorted(execute_signals, key=lambda x: x[1])

        for side, index, entry, stop_loss, take_profit in sorted_signals:

            position_side = side.value

            # logger.info(f"{side, total_len-index, entry, stop_loss, take_profit}")

            total_sl_fee = (entry + stop_loss) * self.fee_rate
            total_tp_fee = (entry + take_profit) * self.fee_rate

            # # [중복 제거 로직] 현재 포지션이 종료되기 전의 동일 방향 신호는 무시 
            if index <= last_exit_idx:
                continue

            result, end_idx, pnl_unit, profit_pct = "PENDING", -1, Decimal('0'), Decimal('0')

            # 시장 움직임 시뮬레이션
            for i in range(index + 1, total_len):

                low = lows[i]
                high = highs[i]

                if position_side == "LONG":
                    if stop_loss >= low:
                        result, end_idx = "SL", i
                        # logger.info(f"{"SL"} {total_len-index}-{total_len-i} | {(stop_loss - entry)}")
                        # price_change_pct = (stop_loss - entry) / entry
                        # profit_pct = (price_change_pct - total_fee_rate) * self.leverage * self.PCT_100
                        # pnl_unit = (stop_loss - entry) - (entry * total_fee_rate) # 단위당 순수익

                        pnl_unit = (stop_loss - entry) - total_sl_fee
                        profit_pct = (pnl_unit / entry) * self.PCT_100 * self.leverage
                        break

                    elif take_profit <= high:
                        result, end_idx = "TP", i
                        # logger.info(f"{"TP"} {total_len-index}-{total_len-i} {(take_profit - entry)}")
                        # price_change_pct = (take_profit - entry) / entry
                        # profit_pct = (price_change_pct - total_fee_rate) * self.leverage * self.PCT_100
                        # pnl_unit = (take_profit - entry) - (entry * total_fee_rate)

                        pnl_unit = ((take_profit - entry) - total_tp_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100 * self.leverage
                        break

                elif position_side == 'SHORT':
                    if stop_loss <= high:
                        result, end_idx = "SL", i
                        # logger.info(f"{"SL"} {total_len-index}-{total_len-i} {(entry - stop_loss)}")

                        # # 단위당 수익 (진입가 - 손절가 - 왕복수수료)
                        # # # 수수료는 진입가 기준 왕복(entry * fee_rate * 2)으로 계산하는 것이 일반적입니다.
                        # pnl_unit = (entry - stop_loss) - (entry * self.fee_rate * 2)
                        # # 레버리지가 적용된 실제 수익률 (%)
                        # profit_pct = (pnl_unit / entry) * self.leverage * self.PCT_100

                        pnl_unit = ((entry - stop_loss) - total_sl_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100 * self.leverage
                        break

                    elif take_profit >= low:
                        result, end_idx = "TP", i
                        # # 단위당 수익 (진입가 - 익절가 - 왕복수수료)
                        # pnl_unit = (entry - take_profit) - (entry * self.fee_rate * 2)
                        # # 레버리지가 적용된 실제 수익률 (%)
                        # profit_pct = (pnl_unit / entry) * self.leverage * self.PCT_100

                        # logger.info(f"{"TP"} {total_len-index}-{total_len-i} {(entry - take_profit)}")
                        pnl_unit = ((entry - take_profit) - total_tp_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100 * self.leverage
                        break

            # 이미 종료된 포지션 거래 내역 (아직 보유중은 제외)
            if result != "PENDING":
                # 청산 시점 업데이트 (동일 방향의 다음 진입을 막기 위함)

                last_exit_idx = end_idx

                trade_events.append({
                    "side": position_side, "index": index, "end_idx": end_idx,
                    "result": result, "profit_pct": profit_pct, "pnl_unit": pnl_unit,
                    "entry": entry, "sl": stop_loss, "tp": take_profit
                })

            # 진입은 했지만 아직 체결이 안된 종목
            if result == "PENDING":
                logger.info(f"[PENDING] {position_side} {total_len-index} entry: {entry}, sl: {stop_loss}, tp: {take_profit}")

        # 2. 거래 종료 시점(end_idx) 기준으로 다시 정렬하여 잔고 업데이트 (시간순 출력) 
        trade_events.sort(key=lambda x: x["end_idx"])

        max_length = 0

        for ev in trade_events:

            side = ev["side"]
            pnl_unit = ev["pnl_unit"]
            profit_pct = ev['profit_pct']
            s_key = side
            pos_side = PositionSide.LONG if side == "LONG" else PositionSide.SHORT

            # 1. 수량 계산
            amount = self.order_manager.get_position_quantity(pos_side, ev["entry"], ev["sl"], self.sim_balance * self.leverage)

            if amount is None or amount <= 0:
                continue

            if amount <= 5:
                logger.info(f"[X] Your Balance is broken. !!!")
                break

            # 3. 순수익(ROI) 계산: (수익금 - 수수료)
            roi = amount * ev["pnl_unit"] # 순수익 틱 * 수량
            self.sim_balance += roi # 이제 수수료가 빠진 실제 돈이 쌓입니다.

            net_profit_pct = ev["profit_pct"] # 순수익 퍼센트

            if ev["result"] == "TP":
                stats[s_key]["win_count"] += 1
                stats[s_key]["tp_sum"] += net_profit_pct
                stats[s_key]["tp_count"] += 1
            else:
                stats[s_key]["sl_sum"] += net_profit_pct
                stats[s_key]["sl_count"] += 1
            
            stats[s_key]["total_profit"] += net_profit_pct
            stats[s_key]["completed_count"] += 1

            rr_ratio = (ev['tp'] - ev['entry']) / (ev['entry'] - ev['sl']) if side == "Long" else (ev['entry'] - ev['tp']) / (ev['sl'] - ev['entry'])

            if self.show_detail:
                start_ago = total_len - ev["index"]
                end_ago = total_len - ev["end_idx"]
                
                logger.info(
                    f"🔍 [Detail] {side:5} | "
                    f"Bars Ago: {start_ago:5} -> {end_ago:5} | Bars Length: {start_ago - end_ago} | "
                    f"Quantity: {amount:.2f} | "
                    f"SL: {ev['sl']:8.4f} | Entry: {ev['entry']:8.4f} | TP: {ev['tp']:8.4f} | "
                    f"PNL: {ev['result']:2} ({ev['profit_pct']:6.2f}%) | ROI: {roi:8.4f} | "
                    f"Balance: {self.sim_balance:8.2f} | RR Ratio: {rr_ratio:4.1f}"  
                )

                if max_length < start_ago - end_ago:
                    max_length = start_ago - end_ago

        # 평균 통계 계산
        for k in ["LONG", "SHORT"]:
            s = stats[k]
            s["avg_tp"] = s["tp_sum"] / s["tp_count"] if s["tp_count"] > 0 else Decimal('0')
            s["avg_sl"] = s["sl_sum"] / s["sl_count"] if s["sl_count"] > 0 else Decimal('0')
            s["total_count"] = len([x for x in execute_signals if x[0] == k])

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