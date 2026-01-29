"""
[Archive] Original Fee-adjusted Logic
Original Location: src/core/trading_engine.py -> calculate_logic()
Description: 수수료 0.045%를 역산하여 지갑 잔고 기준 순수익 1:1을 맞추는 초정밀 로직.
"""

# 기존 코드 복사본...
def legacy_calculate_logic_v1(self, side: PositionSide, sl_raw: Decimal, entry_raw: Decimal):
    """
    [Archive] 지갑 잔고 기준 수수료/슬리피지 완전 역산 모델 (V1.0)

    이 메소드는 거래 시 발생하는 모든 비용(수수료 0.045% * 2)과 
    예상 슬리피지를 가격에 미리 녹여내어, 익절 시 '내 손에 쥐어지는 순수익'이 
    손절 시 '내 지갑에서 깎이는 순손실'과 설정한 RR 비율(예: 1:1)대로 
    정확히 일치하도록 설계된 초정밀 수학 모델입니다.

    장점:
    -----
    1. 지갑 보호 최적화: 수수료를 '비용'이 아닌 '손실의 일부'로 계산하여 
    익절 시 수수료를 다 제하고도 목표 수익금을 완벽히 보전합니다.
    2. 수학적 정교함: 가격 변동폭이 클 때, 수수료를 떼고도 정확히 RR 1:1을 
    맞추는 가장 정밀한 역산 공식(분모에 1-fee 적용)을 사용합니다.
    3. 심리적 안정감: 익절이 발생했을 때 지갑 잔고가 늘어나는 폭과 
    손절 시 줄어드는 폭이 대칭을 이루므로 자금 관리가 직관적입니다.

    단점:
    -----
    1. 익절가 괴물 현상: 손절가와 진입가의 거리(변동폭)가 수수료율(0.09%)에 
    가까워질수록, 수수료를 메꾸기 위해 익절가가 기하급수적으로 멀어집니다.
    2. 낮은 체결률: 수수료를 다 벌어오려다 보니 차트상의 거리가 1:1을 넘어 
    1:2, 1:10까지 벌어질 수 있어 익절 타겟 도달이 어려워집니다.
    3. 수수료 민감도: 초단타(Scalping)처럼 변동폭이 극도로 좁은 전략에서는 
    로직 오작동처럼 보일 정도로 비현실적인 익절가를 제시합니다.

    변수 설명:
    ----------
    - side: PositionSide.LONG 또는 SHORT
    - sl_raw: 전략에서 도출된 가공 전 손절가 (Stop Loss)
    - entry_raw: 현재 진입 가격 (Entry Price)
    """
    entry = Decimal(str(entry_raw))
    raw_sl = Decimal(str(sl_raw))
    slippage_amount = Decimal(str(entry * self.slippage_percent))

    max_loss_limit_ratio = Decimal(str(MAX_STOP_LOSS_RATIO)) / 100
    rr_ratio = Decimal(str(RISK_REWARD_RAITO))
    fee_rate = Decimal('0.00045')
    total_fee_rate = fee_rate * 2 # 왕복 수수료 (0.0009 = 0.09%)

    if side == PositionSide.LONG:
        # Long Stop Loss
        max_sl_price = (sl_raw + (entry * fee_rate)) / (1 - fee_rate)
        result_sl = max(raw_sl, max_sl_price) + slippage_amount

        # Long Take Profit
        net_loss = (entry - result_sl) + (entry + result_sl) * fee_rate
        target_net_profit = net_loss * rr_ratio
        result_tp = (entry * (1 + fee_rate) + target_net_profit) / (1 - fee_rate)
        result_tp = result_tp - slippage_amount

    elif side == PositionSide.SHORT:
        # Short Stop Loss
        max_sl_price = (sl_raw - (entry * fee_rate)) / (1 + fee_rate)
        result_sl = min(raw_sl, max_sl_price) - slippage_amount

        # Short Take Profit
        net_loss = (result_sl - entry) + (entry + result_sl) * fee_rate
        target_net_profit = net_loss * rr_ratio
        result_tp = (entry * (1 - fee_rate) - target_net_profit) / (1 + fee_rate)
        result_tp = result_tp + slippage_amount

    is_long_valid = (side == PositionSide.LONG and result_tp > entry > result_sl)
    is_short_valid = (side == PositionSide.SHORT and result_sl > entry > result_tp)

    min_distance = entry * total_fee_rate
    actual_distance = abs(result_tp - entry)
    actual_loss_ratio = net_loss / entry

    if not (is_long_valid or is_short_valid) or (actual_distance <= min_distance) or (actual_loss_ratio > max_loss_limit_ratio):
        return None, None, None

    def_sl = round_step_size(sl_raw, self.tickSize)
    final_sl = round_step_size(result_sl, self.tickSize)
    final_tp = round_step_size(result_tp, self.tickSize)

    return def_sl, final_sl, final_tp