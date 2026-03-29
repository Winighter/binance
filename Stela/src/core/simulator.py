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
        self.sim_balance = Decimal('1000')
        self.show_detail = bool(False)

    def run(self, execute_signals:List, highs, lows, stepSize):

        '''
        signal = [index, stop loss, entry, take profit]
        '''
        self.stepSize = stepSize
        self.tl = len(lows)
        # from decimal import Decimal

        # # 1. 가격 데이터 (100.0에서 시작하여 102.0까지 상승)
        # highs = [Decimal('100.0') + (Decimal(str(i)) * Decimal('0.02')) for i in range(101)]
        # lows = [h - Decimal('0.5') for h in highs] # 손절 안 나게 설정

        # # 2. 10배 레버리지 테스트 신호
        # # [index, stop_loss, entry, take_profit]
        # long_signals = [
        #     # 101.0 진입 -> 102.0 익절 (가격 1% 상승)
        #     # 레버리지 10배 적용 시: 수익 10% - 수수료 0.9% = 약 9.1% 순수익 예상
        #     [50, Decimal('100.0'), Decimal('101.0'), Decimal('102.0')]
        # ]
        # short_signals = []

        # 수량 정밀도 설정

        # 1. 모든 신호를 하나로 통합
        combined_signals = []
        for sig in long_signals:
            combined_signals.append(("Long", sig))
        for sig in short_signals:
            combined_signals.append(("Short", sig))

        # 2. 통합 시뮬레이션 실행
        stats = self._calculate_combined_outcomes(combined_signals, highs, lows)

        # 3. 요약 출력
        self._print_summary(stats['long'], stats['short'])

    def _calculate_combined_outcomes(self, combined_signals: List, highs: List[Decimal], lows: List[Decimal]) -> Dict[str, Any]:
        stats = {
            "long": self._init_stats_dict(),
            "short": self._init_stats_dict()
        }
        total_len = len(highs)
        trade_events = []
        
        # 동일 포지션 중복 진입 방지를 위한 마지막 청산 인덱스 관리
        last_long_exit_idx = -1
        last_short_exit_idx = -1

        # 1. 신호를 진입 시점(index) 순으로 정렬하여 검토
        sorted_signals = sorted(combined_signals, key=lambda x: x[1][0])

        for side, value in sorted_signals:

            index = value[0]
            stop_loss = Decimal(str(value[1]))
            entry = Decimal(str(value[2]))
            take_profit = Decimal(str(value[3]))

            total_sl_fee = (entry + stop_loss) * self.fee_rate
            total_tp_fee = (entry + take_profit) * self.fee_rate

            # [중복 제거 로직] 현재 포지션이 종료되기 전의 동일 방향 신호는 무시 
            if side == "Long" and index <= last_long_exit_idx:
                continue
            if side == "Short" and index <= last_short_exit_idx:
                continue

            result, end_idx, profit_pct, pnl_unit = "PENDING", -1, Decimal('0'), Decimal('0')

            # 시장 움직임 시뮬레이션
            for i in range(index + 1, total_len):

                low = lows[i]
                high = highs[i]

                if side == "Long":
                    if lows[i] <= stop_loss:
                        result, end_idx = "SL", i
                        pnl_unit = ((stop_loss - entry) - total_sl_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100
                        break

                    elif highs[i] >= take_profit:
                        result, end_idx = "TP", i
                        pnl_unit = ((take_profit - entry) - total_tp_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100
                        break

                elif side == 'Short':
                    if stop_loss <= high:
                        result, end_idx = "SL", i
                        pnl_unit = ((entry - stop_loss) - total_sl_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100
                        break

                    elif take_profit >= low:
                        result, end_idx = "TP", i
                        pnl_unit = ((entry - take_profit) - total_tp_fee)
                        profit_pct = (pnl_unit / entry) * self.PCT_100
                        break

            # 이미 종료된 포지션 거래 내역 (아직 보유중은 제외)
            if result != "PENDING":
                # 청산 시점 업데이트 (동일 방향의 다음 진입을 막기 위함)
                if side == "Long":
                    last_long_exit_idx = end_idx
                elif side == 'Short':
                    last_short_exit_idx = end_idx

                trade_events.append({
                    "side": side, "index": index, "end_idx": end_idx,
                    "result": result, "profit_pct": profit_pct, "pnl_unit": pnl_unit,
                    "entry": entry, "sl": stop_loss, "tp": take_profit
                })

            # 진입은 했지만 아직 체결이 안된 종목
            # if result == "PENDING":
            #     logger.info(f"[PENDING] {side} {total_len-index}")

        # 2. 거래 종료 시점(end_idx) 기준으로 다시 정렬하여 잔고 업데이트 (시간순 출력) 
        trade_events.sort(key=lambda x: x["end_idx"])

        for ev in trade_events:
            side = ev["side"]
            pnl_unit = ev["pnl_unit"]
            s_key = side.lower()
            pos_side = PositionSide.LONG if side == "Long" else PositionSide.SHORT

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
                    f"Bars Ago: {start_ago:5} -> {end_ago:5} | "
                    f"Quantity: {amount:.2f} | "
                    f"SL: {ev['sl']:8.4f} | Entry: {ev['entry']:8.4f} | TP: {ev['tp']:8.4f} | "
                    f"PNL: {ev['result']:2} ({ev['profit_pct']:6.2f}%) | ROI: {roi:8.4f} | "
                    f"Balance: {self.sim_balance:8.2f} | RR Ratio: {rr_ratio:4.1f}"  
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