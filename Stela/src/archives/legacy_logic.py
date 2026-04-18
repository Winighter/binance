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

def optimize_price_structure_data(self, data):

    data = self.duplicate_processing(data) # duplicate filter
    data = self.apply_price_structure_arrangement(data) # arrage filter

    return data

def apply_price_structure_arrangement(self, data):

    result = []
    dp_list = []

    for i in range(1, len(data)):
        point = data[i]
        side = point[0]

        point1 = data[i-1]
        side1 = point1[0]

        if side == side1:
            dp_list.append(point1)
            continue

        if dp_list and side != side1:
            dp_list.append(point1)
            if side1 == 'LOW':
                min_index = None
                min_price = None

                for dp_i in range(len(dp_list)):
                    dp_point = dp_list[dp_i]
                    dp_price = dp_point[2]

                    if dp_i == 0:
                        min_index = dp_i
                        min_price = dp_price

                    elif min_price >= dp_price:
                        min_index = dp_i
                        min_price = dp_price

                result.append(dp_list[min_index])
            else:
                max_index = None
                max_price = None
                for dp_i in range(len(dp_list)):
                    dp_point = dp_list[dp_i]
                    dp_price = dp_point[2]

                    if dp_i == 0:
                        max_index = dp_i
                        max_price = dp_price

                    elif max_price <= dp_price:
                        max_index = dp_i
                        max_price = dp_price

                result.append(dp_list[max_index])

            dp_list = []
            continue

        result.append(point1)

        if i == len(data) - 1:
            result.append(point)

    return result

def apply_price_structure_arrangement(self, data):

    result = []
    dp_list = []

    for i in range(1, len(data)):
        point = data[i]
        side = point[0]

        point1 = data[i-1]
        side1 = point1[0]

        if side == side1:
            dp_list.append(point1)
            continue

        if dp_list and side != side1:
            dp_list.append(point1)
            if side1 == 'LOW':
                min_index = None
                min_price = None

                for dp_i in range(len(dp_list)):
                    dp_point = dp_list[dp_i]
                    dp_price = dp_point[2]

                    if dp_i == 0:
                        min_index = dp_i
                        min_price = dp_price

                    elif min_price >= dp_price:
                        min_index = dp_i
                        min_price = dp_price

                result.append(dp_list[min_index])
            else:
                max_index = None
                max_price = None
                for dp_i in range(len(dp_list)):
                    dp_point = dp_list[dp_i]
                    dp_price = dp_point[2]

                    if dp_i == 0:
                        max_index = dp_i
                        max_price = dp_price

                    elif max_price <= dp_price:
                        max_index = dp_i
                        max_price = dp_price

                result.append(dp_list[max_index])

            dp_list = []
            continue

        result.append(point1)

        if i == len(data) - 1:
            result.append(point)

    return result

def duplicate_processing(self, data):

    result = []
    duplicate_list = []

    for i in range(2, len(data)-1):

        next_point = data[i+1]
        next_side = next_point[0]

        point = data[i]
        side = point[0]
        index = point[1]

        point1 = data[i-1]
        index1 = point1[1]

        point2 = data[i-2]
        side2 = point2[0]

        if duplicate_list != []:
            duplicate0 = duplicate_list[0]
            dup_side = duplicate0[0]

            if side == dup_side:
                dp_result = duplicate_list[1]
            else:
                dp_result = duplicate_list[0]

            result.append(dp_result)
            duplicate_list = []
            continue

        if index == index1 and next_side == side2:
            duplicate_list = [point1, point]
            continue

        result.append(point1)

        if i == len(data) - 2:
            result.append(point)
            result.append(next_point)

    return result

def identify_swing_points2(self, highs, lows, closes, timestamps, showLog:bool = False, lookback:int = SWING_LOOKBACK):

    swing_lows = []
    swing_highs = []

    firsts = []
    seconds = []
    total_len = min(len(lows), len(highs), len(closes), len(timestamps))

    if total_len < (lookback * 2 + 1):
        raise InsufficientDataError(f"거래 중단: 데이터 부족 | 현재 데이터 수: {total_len}")

    ### Pivot Point ###
    for i in range(lookback, len(lows) - lookback):

        if lows[i] == min(lows[i - lookback : i + lookback + 1]):
            swing_lows.append(['LOW', i, lows[i], timestamps[i]])

        if highs[i] == max(highs[i - lookback : i + lookback + 1]):
            swing_highs.append(['HIGH', i, highs[i], timestamps[i]])

    for i in range(1, len(swing_lows)):
        prev_low_point = swing_lows[i-1]
        prev_low_index = prev_low_point[1]
        prev_low = prev_low_point[2]

        current_low_point = swing_lows[i]
        current_low_index = current_low_point[1]
        current_low = current_low_point[2]

        if showLog:

            if prev_low < current_low:
                logger.info(f"[LOW] [{total_len-prev_low_index}-{total_len-current_low_index}] HL (Higher Low)")

            elif prev_low > current_low:
                logger.info(f"[LOW] [{total_len-prev_low_index}-{total_len-current_low_index}] LL (Lower Low)")

            elif prev_low == current_low:
                logger.info(f"[LOW] [{total_len-prev_low_index}-{total_len-current_low_index}] EL (Equal Low)")

    for i in range(1, len(swing_highs)):
        prev_high_point = swing_highs[i-1]
        prev_high_index = prev_high_point[1]
        prev_high = prev_high_point[2]

        current_high_point = swing_highs[i]
        current_high_index = current_high_point[1]
        current_high = current_high_point[2]

        if showLog:

            if prev_high < current_high:
                logger.info(f"[HIGH] [{total_len-prev_high_index}-{total_len-current_high_index}] HH (Higher High)")

            elif prev_high > current_high:
                logger.info(f"[HIGH] [{total_len-prev_high_index}-{total_len-current_high_index}] LH (Lower High)")

            elif prev_high == current_high:
                logger.info(f"[HIGH] [{total_len-prev_high_index}-{total_len-current_high_index}] EH (Equal High)")


    for side, index, price, timestamp in firsts:

        for i in range(len(lows)):
            close = closes[i]
            if index + lookback < i:
                if side == 'LOW':

                    if price >= close:
                        break

                    elif price < close:
                        data = (side, index, price, timestamp)
                        seconds.append(data)
                        break

                elif side == 'HIGH':

                    if price <= close:
                        break

                    elif price > close:
                        data = (side, index, price, timestamp)
                        seconds.append(data)
                        break

    result = self.optimize_price_structure_data(seconds)

    # if showLog:
    #     for side, index, price, ts in result:
    #         logger.info(f"[{side}] {total_len-index} {price}")

    return result

def analyze_trend_direction(self, highs, lows, closes, timestamps, showLog:bool = False, lookback = SWING_LOOKBACK):

    '''
    HTF 에서 추세 구조 파악 후 거래 범위 (swing range) 파악하기
    '''

    swing_ranges = []
    total_len = len(lows)

    # Swing Points
    swing_points = self.identify_swing_points2(highs, lows, closes, timestamps, False, lookback=3)

    # Break of Structure (BOS)
    bos = self.identify_break_of_structure(highs, lows, closes, swing_points, showLog=False)

    # Swing Ranges
    swing_range = self.identify_swing_range(highs, lows, bos, swing_points)

    for side, start, end in swing_range:
        if side == "LOW":
            swing_high = highs[start]
            for i in range(start, total_len):
                high = highs[i]
                if swing_high < high:
                    break
            premium_discount = self.analyze_premium_discount(highs[start], lows[end])
        elif side == "HIGH":
            swing_low = lows[start]
            for i in range(start, total_len):
                low = lows[i]
                if swing_low > low:
                    break
            premium_discount = self.analyze_premium_discount(lows[start], highs[end])

        minimun_entry_index = end + lookback + 1
        swing_ranges.append((side, start, end, minimun_entry_index, premium_discount))

        # if showLog:
        #     logger.info(f"[{side}] start: {total_len-start}, end: {total_len-end}, min entry: {total_len-minimun_entry_index} p/d: {premium_discount}")

    if showLog:
        for side, start, end, min, pre_dis in swing_ranges:
            logger.info(f"[{side}] Swing Start Index: {total_len-start}, Swing End Index: {total_len-end}, Min Entry Index: {total_len-min}, P/D: {pre_dis}")

    return swing_ranges

def analyze_liquidity_sweep(self, highs, lows, closes, timestamps, showLog:bool = False) -> List:
    '''
    Docstring for analyze_liquidity_sweep
    
    :param self: Description
    :param highs: Description
    :param lows: Description
    :param swing_point: Description
    :type swing_point: List
    :param showLog: Description
    :type showLog: bool
    :return: Description
    :rtype: Tuple

    유동성 제거는 종가 및 꼬리 둘다 유효하다


    Short 의 유동성은 고가 위 (고가를 포함하여 그 위의 존)
    Long 의 유동성은 저가 아래 (저가를 포함하여 그 아래의 존)
    유동성 스윕 기준은 고가 또는 저가 인정
    유동성이 존재하는 구간 및 그 구간을 휩쓴 기준도 고가 or 저가
    즉, Short 은 유동성이 있는 고가(위)를 너 높은 고가가 상향하여 휩쓴곳
    반대로 Long 은 유동성이 있는 저가(아래)를 나 낮은 저가가 하향하여 휩쓴곳  

    SSL : Sell Side Liquidity
    BSL : Buy Side Liquidity

    Tip

    Always look for inducements at POIs      

    수요 / 공급 구역 다음 즉 첫번째 스윙 지점이 BOS 가 일어난 POI 이고 2번째 스윙 고점-저점이 최고점/최저점일때
    피보나치에 맞는 프리미엄/디스카운트에 맞는데 까지 기다린다

    '''

    firsts = []
    result = []

    bsl_sweeps = {}
    ssl_sweeps = {}

    lookback = 2 # Available LQ Pivot Candle Lookback (Left & Right)

    # Swing Points
    swing_points = self.identify_swing_points2(highs, lows, closes, timestamps, False, lookback=3)

    # Break of Structure (BOS)
    bos = self.identify_break_of_structure(highs, lows, closes, swing_points, showLog=False)
    
    swing_ranges = self.identify_swing_range(highs, lows, bos, swing_points)

    total_len = len(lows)
    for side, start, end in bos:

        if lows[i] == max(highs[start : end]):
            firsts.append(['LOW', i, lows[i]])

        if highs[i] == max(highs[start : end]):
            firsts.append(['HIGH', i, highs[i]])

    for side, index, price in firsts:

        for i in range(index + lookback + 1, total_len):
            if side == 'HIGH':
                if price < highs[i]:
                    if i not in bsl_sweeps.keys():
                        bsl_sweeps.update({i : [index]})
                    elif i in bsl_sweeps.keys():
                        bsl_sweeps[i].append(index)
                    break

            if side == 'LOW':
                if price > lows[i]:
                    if i not in ssl_sweeps.keys():
                        ssl_sweeps.update({i : [index]})
                    elif i in ssl_sweeps.keys():
                        ssl_sweeps[i].append(index)
                    break

    bsl_sweeps = dict(sorted(bsl_sweeps.items()))
    ssl_sweeps = dict(sorted(ssl_sweeps.items()))

    for key in bsl_sweeps:
        value = bsl_sweeps[key]
        result.append(('BSL', key, value))

    for key in ssl_sweeps:
        value = ssl_sweeps[key]
        result.append(('SSL', key, value))

    if showLog:
        for side, sweep, lq in result:
            logger.info(f"[{side}] Sweep Index: {total_len-sweep} LQ: {lq} ")

    return result

def identify_break_of_structure(self, highs, lows, closes, swing_points, lookback, BOS_DOUBLE_CONFIRMATION:bool = False, showLog:bool = False):
    '''
    # BOS (Break of Structure)
    추세 지속을 의미

    고점 또는 저점을 현재 가격이 그 지점을 종가로 돌파후 마감한 경우
    Key Point: 모두 단순 꼬리가 아닌 종가 마감을 중요하게 여기고 있기 때문에
    꼬리가 아닌 마감된 종가를 기준으로 해야한다. <- 이건 확실한듯

    돌파 실패했을 경우 그 다음 봉이 그 꼬리를 포함해서 종가 기준으로 돌파해야한다. (CHoCH 도 동일하다)

    BOS: Bullish
    고점이 확인됬고 가격이 움직이고 난 뒤 종가가 확인된 고점을 상향돌파한 경우
    강세 추세 지속

    BOS: Bearish
    저점이 확인됬고 가격이 움직이고 난 뒤 종가가 확인된 저점을 햐향돌파한 경우
    약세 추세 지속
    '''
    result = []
    total_len = len(lows)

    for i in range(len(swing_points)):
        data = swing_points[i]
        side = data[0]
        index = data[1]
        confirm_index = index

        pivot_data = None

        for p in range(index, len(lows)):
            high = highs[p]
            low = lows[p]
            close = closes[p]

            if index + lookback < p:

                if side == "HIGH":

                    if highs[confirm_index] < close:
                        if showLog:
                            logger.info(f"{side} BOS: {total_len-confirm_index}-{total_len-p}")
                        pivot_data = (side, confirm_index, p)
                        break

                    elif BOS_DOUBLE_CONFIRMATION and highs[confirm_index] < high:

                        confirm_index = p

                elif side == 'LOW':
                    if lows[confirm_index] > close:
                        if showLog:
                            logger.info(f"{side} BOS: {total_len-confirm_index}-{total_len-p}")
                        pivot_data = (side, confirm_index, p)
                        break

                    elif BOS_DOUBLE_CONFIRMATION and lows[confirm_index] > low:
                        confirm_index = p

        if pivot_data and pivot_data not in result:
            result.append(pivot_data)

    result = sorted(result, key=lambda x: x[2])

    return result

def analyze_signal(self, opens, highs, lows, closes, poi, showLog:bool = False):

    '''
    Docstring for analyze_signal
    
    :param self: Description
    :param opens: Execute opens
    :param highs: Execute highs
    :param lows: Execute lows
    :param closes: Execute closes
    :param poi: MTF Point of Interest
    :param htf_swing_ranges: HTF Swing Ranges
    :param showLog: Description
    :type showLog: bool

    Zone Confirmation
    Demand Zone (Long) : Zone High > Low
    Supply Zone (Short) : Zone Low < High

    Zone Not Confirmation
    Demand Zone (Long) : Close >= Zone Low
    Supply Zone (Short) : Zone High <= Close


    진입하는 봉은 무조건 런던세션이나 뉴욕세션에 포함되어야 한다. 그외에는 진입X
    진입은 이전 봉마감이니까 

    '''
    total_len = len(lows)
    long_signal = {}
    short_signal = {}

    # for side, start, end, min_index, pd_price in htf_swing_ranges:
    #     if side == 'LOW':
    #         position_side = 'SHORT'
    #     elif side == 'HIGH':
    #         position_side = 'LONG'
    #     ts_data = self.match_sub_candles(self.htf_timestamps[min_index], self.mtf_timestamps, highs)
    #     first_data = ts_data[0]
    #     first_index = first_data[0] # 최소 진입 인덱스, 이 인덱스 포함해서 최소 진입 인덱스 즉 진입인덱스가 이 인덱스가 될수 있다.
    #     first_price = first_data[1]
        # logger.info(f"HTF {position_side, self.htf_tl-start, self.htf_tl-end, self.htf_tl-min_index, pd_price} | MTF {total_len-first_index, first_price}")

    long_data = defaultdict(list)
    short_data = defaultdict(list)

    for side, start, end in poi:
        '''
        side: Demand or Supply
        start: POI Index
        end: BOS-POI 확인 봉 이봉이 마감된 이후 사용 가능
        '''
        poi_type = side
        index = start # POI Index
        end_index = end # 최소 진입할수 있는 인덱스

        # logger.info(f"[POI] {poi_type} {total_len-index} {total_len-end_index}")

        ec_level = 0 # Entry Conditions Level

        for i in range(index + 1, total_len):
            open = opens[i]
            low = lows[i]
            high = highs[i]
            close = closes[i]
            body_top = max(open, close)
            body_bottom = min(open, close)

            if poi_type == 'Demand':
                dhp = highs[index] # Demand High Price
                dlp = lows[index] # Demand Low Price

                # Long Condition 2
                if ec_level == 1 and high > dhp > low:
                    ec_level = 2

                # Long Condition 3
                if ec_level == 2 and dhp < close and open < close and end_index < i:
                    # logger.info(f"[LONG] POI: {total_len-index}, Signal: {total_len-i}")
                    long_data[index].append(i)
                    break

                # Long Condition 1
                if ec_level == 0 and dhp < low:
                    ec_level = 1

                # Depth (Low probability Zone)
                if dlp >= body_top:
                    break

            elif poi_type == 'Supply':

                shp = highs[index] # Supply High Price
                slp = lows[index] # Supply Low Price

                # Short Condition 2
                if ec_level == 1 and high > slp > low:
                    ec_level = 2

                # Short Condition 3
                if ec_level == 2 and slp > close and open > close and end_index < i:
                    # logger.info(f"[SHORT] POI: {total_len-index}, Signal: {total_len-i}")
                    short_data[index].append(i)
                    break

                # Short Condition 1
                if ec_level == 0 and slp > high:
                    ec_level = 1

                # Depth (Low probability Zone)
                if shp <= body_bottom:
                    break

    # long_result = {k: min(v) for k, v in long_data.items()}
    # for key in long_result:
    #     value = long_result[key]

    #     supply_tp_index = None
    #     for supply in supply_zones:
    #         if key > supply:
    #             supply_tp_index = supply

    #     if value not in list(long_signal.keys()):
    #         if supply_tp_index:
    #             supply_tp = highs[supply_tp_index]
    #         else:
    #             supply_tp = None

    #         if showLog:
    #             logger.info(f"[LONG] Sweep Index: {total_len-key}, Signal Index: {total_len-long_result[key]} SL: {lows[key]}, Entry: {closes[value]}, TP: {supply_tp}")

    #         long_signal.update({value:[lows[key], closes[value], supply_tp]})

    # short_result = {k: min(v) for k, v in short_data.items()}
    # for key in short_result:
    #     value = short_result[key]

    #     demand_tp_index = None
    #     for demand in demand_zones:
    #         if key > demand:
    #             demand_tp_index = demand

    #     if value not in list(short_signal.keys()):
    #         if demand_tp_index:
    #             demand_tp = lows[demand_tp_index]
    #         else:
    #             demand_tp = None

    #         if showLog:
    #             logger.info(f"[SHORT] Sweep Index: {total_len-key}, Signal Index: {total_len-short_result[key]} SL: {highs[key]}, Entry: {closes[value]}, TP: {demand_tp}")

    #         short_signal.update({value:[highs[key], closes[value], demand_tp]})

    return long_signal, short_signal