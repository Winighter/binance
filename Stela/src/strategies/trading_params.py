SWING_LOOKBACK = 3 # 스윙 포인트 양쪽 몇개를 기준으로 할건지
#############################################################
MAX_RISK_RATIO = 1 # 전체자산 기준 최대 손실 허용 비율
MIN_RISK_REWARD_RAITO = 2 # 최소 손익비 조건
MAX_STOP_LOSS_RATIO = 10 # 최대 손절가 퍼센트 (손익비가 2, 3 이어도 전체적으로 12가 가장 높은 수익률을 얻었다. 12 추천)
MAX_POSITION_RATIO = 40 # 자산 기준 최대 보유 가능 포지션 비율 (40 이하)

### Set your Guardrails ###
# These are recommended defaults. You can change them later. 
# Guardrails will block actions that break your rules.

# Max Trades per day
# Stops revenge trading and overtrading. When you hit the cap, new trades are blocked unless you override.
MAX_TRADES_PER_DAY = 5

# 일일 최대 손실
MAX_DAILY_LOSS = 500 # Uses realized PnL / When today's realized PnL hits this loss limit, the Trade button is blocked.

# 일일 최대 수익
MAX_DAILY_PROFIT = 1000 # Uses realized PnL / 

# 거래당 고정 위험 (%)
FIXED_RISK_PER_TRADE = 1 # (%) 거래당 기본 위험 설정 MAX_RISK_RATIO 와 같은 개념일듯 만약 그렇다면 1개는 없애야 함