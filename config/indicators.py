class Indicators():

    _ROUND_PRECISION = 4

    @staticmethod
    def sma(_src:list, _length:int, _array:int = 0):
        """
        Calculates the Simple Moving Average (SMA) for a given source list.
        The _src list is assumed to have the most recent data at index 0,
        and older data at increasing indices.

        Args:
            _src (list): The source data list (e.g., closing prices).
                         Most recent data at index 0.
            _length (int): The period length for the SMA calculation.
            _array (int, optional): If an integer (e.g., 0 for the most recent SMA),
                                    returns the SMA value at that specific index from the result list.
                                    If None, returns the full list of SMA values. Defaults to 0.

        Returns:
            list or float: A list of SMA values (most recent at index 0) if _array is None,
                           a single SMA value if _array is specified and valid.

        Raises:
            ValueError: If insufficient data is provided for the calculation,
                        or if _array index is out of bounds.
        """
        result = []
        if len(_src) < _length:
            raise ValueError(f"Insufficient data for SMA calculation. Expected at least {_length} data points, but got {len(_src)}.")

        for i in range(len(_src) - _length + 1):
            current_window = _src[i : i + _length]
            sma_val = round(sum(current_window) / _length, Indicators._ROUND_PRECISION)
            result.append(sma_val)

        if _array is not None:
            if len(result) > _array:
                return result[_array]
            else:
                raise ValueError(f"Invalid _array index for SMA. Result list has {len(result)} elements, but index {_array} was requested.")
        return result

    @staticmethod
    def rma(_src: list, _length: int, _array: int = 0):
        """
        Calculates the Relative Moving Average (RMA).
        The _src list is assumed to have the most recent data at index 0,
        and older data at increasing indices.

        Args:
            _src (list): The source data list. Most recent data at index 0.
            _length (int): The period length for the RMA calculation.
            _array (int, optional): If an integer, returns the RMA value at that specific index
                                    (0 for the most recent RMA). If None, returns the full list of RMAs.
                                    Defaults to 0.

        Returns:
            list or float: A list of RMA values (most recent at index 0) if _array is None,
                           a single RMA value if _array is specified and valid.

        Raises:
            ValueError: If insufficient data is provided for the calculation,
                        or if _array index is out of bounds.
        """
        alpha = round(1 / _length, Indicators._ROUND_PRECISION + 2)
        rma_values = []

        if len(_src) < _length:
            raise ValueError(f"Insufficient data for RMA calculation. Expected at least {_length} data points, but got {len(_src)}.")

        time_src_reversed = _src[_length-1::-1]
        
        current_rma = round(sum(time_src_reversed) / _length, Indicators._ROUND_PRECISION)
        rma_values.append(current_rma)

        for i in range(len(_src) - _length -1, -1, -1):
            current_rma = alpha * _src[i] + (1 - alpha) * current_rma
            rma_values.append(round(current_rma, Indicators._ROUND_PRECISION))

        result = rma_values[::-1]

        if _array is not None:
            if len(result) > _array:
                return result[_array]
            else:
                raise ValueError(f"Invalid _array index for RMA. Result list has {len(result)} elements, but index {_array} was requested.")
        return result

    @staticmethod
    def atr(_high: list, _low: list, _close: list, _length: int = 28, _array: int = 0):
        """
        Calculates the Average True Range (ATR).
        _high, _low, _close lists are assumed to have the most recent data at index 0,
        and older data at increasing indices.

        Args:
            _high (list): List of high prices. Most recent data at index 0.
            _low (list): List of low prices. Most recent data at index 0.
            _close (list): List of closing prices. Most recent data at index 0.
            _length (int, optional): The period length for the ATR calculation. Defaults to 28.
            _array (int, optional): If an integer, returns the ATR value at that specific index
                                    (0 for the most recent ATR). If None, returns the full list of ATRs.
                                    Defaults to 0.

        Returns:
            list or float: A list of ATR values (most recent at index 0) if _array is None,
                           a single ATR value if _array is specified and valid.

        Raises:
            ValueError: If input lists have different lengths,
                        if insufficient data is provided for the calculation,
                        or if _array index is out of bounds.
        """
        # 1. 입력 리스트 길이 유효성 검사 강화
        if not (len(_high) == len(_low) == len(_close)):
            raise ValueError(f"Input lists for ATR must have the same length. "
                             f"High: {len(_high)}, Low: {len(_low)}, Close: {len(_close)}.")

        # 2. 최소 데이터 길이 검사
        if len(_high) < _length: # 모든 리스트 길이가 같다고 가정하므로 _high만 검사해도 됨
             raise ValueError(f"Insufficient data for ATR calculation. Expected at least {_length} data points, but got {len(_high)}.")

        tr_list = []

        for i in range(len(_high)):
            range1 = round(_high[i] - _low[i], Indicators._ROUND_PRECISION)

            # If there's no previous closing price (i.e., for the oldest data point at index len-1)
            # range2 and range3, which rely on the previous close, will be 0 as per True Range definition.
            if i + 1 < len(_close):
                range2 = round(abs(_high[i] - _close[i+1]), Indicators._ROUND_PRECISION)
                range3 = round(abs(_low[i] - _close[i+1]), Indicators._ROUND_PRECISION)
            else:
                # For the oldest data point, there is no 'previous close', so these components are 0.
                range2 = 0
                range3 = 0

            trueRange = max(range1, range2, range3)

            tr_list.append(trueRange)

        # RMA 함수가 이미 에러 핸들링을 포함하고 있으므로, 여기서는 별도의 처리 없이 호출
        atr_result = Indicators.rma(tr_list, _length, None)

        if _array is not None:
            if len(atr_result) > _array:
                return atr_result[_array]
            else:
                raise ValueError(f"Invalid _array index for ATR. Result list has {len(atr_result)} elements, but index {_array} was requested.")
        return atr_result


    @staticmethod
    def supertrend_pine_style(_high: list, _low: list, _close: list, _atr_length: int = 14, _multiplier: float = 4.0, _array: int = 0):
        """
        파인스크립트 SuperTrend 로직을 기반으로 SuperTrend 지표를 계산합니다.
        가장 최근 데이터가 인덱스 0에, 오래된 데이터는 그 뒤에 위치한다고 가정합니다.

        Args:
            _high (list): 고가 리스트. (가장 최근 데이터가 인덱스 0)
            _low (list): 저가 리스트. (가장 최근 데이터가 인덱스 0)
            _close (list): 종가 리스트. (가장 최근 데이터가 인덱스 0)
            _atr_length (int, optional): ATR 계산에 사용될 기간. 파인스크립트 기본값인 14를 따릅니다.
            _multiplier (float, optional): ATR에 곱해져 밴드 폭을 결정하는 승수. 파인스크립트 기본값인 4.0을 따릅니다.
            _array (int, optional): 정수일 경우, 해당 인덱스(0은 가장 최근 SuperTrend)의 값을 반환합니다.
                                    None일 경우, SuperTrend 값의 전체 리스트를 반환합니다. 기본값은 0.

        Returns:
            list 또는 float: _array가 None이면 SuperTrend 값의 리스트, 아니면 단일 SuperTrend 값.

        Raises:
            ValueError: 입력 리스트의 길이가 다르거나, 계산을 위한 데이터가 부족하거나, _array 인덱스가 유효하지 않을 경우 발생합니다.
        """

        # 1. 입력 유효성 검사 🛡️
        # 모든 가격 데이터 리스트의 길이가 동일한지 확인합니다.
        if not (len(_high) == len(_low) == len(_close)):
            raise ValueError(f"SuperTrend 계산을 위한 입력 리스트의 길이가 동일해야 합니다. "
                             f"고가: {len(_high)}, 저가: {len(_low)}, 종가: {len(_close)}.")
        
        # SuperTrend 계산에 필요한 최소 데이터 길이를 확인합니다.
        # ATR 계산에 _atr_length 만큼의 데이터가 필요하고, 이전 종가(`close[1]`) 참조를 위해 최소 _atr_length + 1개의 데이터가 필요합니다.
        min_data_needed = _atr_length + 1 
        if len(_high) < min_data_needed:
            raise ValueError(f"SuperTrend 계산을 위한 데이터가 부족합니다. 최소 {min_data_needed}개의 데이터 포인트가 필요하지만, {len(_high)}개를 받았습니다.")

        # 2. ATR 값 계산 📈
        # 전체 ATR 값을 계산하여 리스트로 가져옵니다. (None을 사용하여 전체 리스트 반환 요청)
        atr_values = Indicators.atr(_high, _low, _close, _atr_length, None)
        
        # 3. 데이터 순서 정렬 (오래된 -> 최근) 🔄
        # SuperTrend 계산은 일반적으로 시간 순서대로 (오래된 데이터부터) 진행되므로, 입력 리스트들을 뒤집습니다.
        # 이렇게 하면 인덱스 0이 가장 오래된 데이터가 되고, 인덱스가 증가할수록 최근 데이터가 됩니다.
        time_ordered_high = _high[::-1]
        time_ordered_low = _low[::-1]
        time_ordered_close = _close[::-1]
        time_ordered_atr = atr_values[::-1]  # <-- 이 리스트가 더 짧음

        # 4. 결과 및 중간 계산값 저장 리스트 초기화 📊
        num_atr_values = len(time_ordered_atr) 
        supertrend_values = [0] * num_atr_values
        up_band = [0] * len(time_ordered_close) 
        dn_band = [0] * len(time_ordered_close)
        trend_direction = [0] * num_atr_values # 초기값은 0

        # 신호 저장을 위한 리스트 (새로 추가)
        # 각 캔들에서의 신호: 1 = 매수, -1 = 매도, 0 = 신호 없음
        signals = [0] * num_atr_values 

        # 5. SuperTrend 핵심 로직 계산 ⚙️
        # ATR 계산이 완료된 시점부터 SuperTrend 계산을 시작합니다.
        # 파인스크립트처럼 `[1]` (이전 값)을 참조하므로, `_atr_length`부터 루프를 시작합니다.
        for i in range(num_atr_values):
            current_price_idx = i + (_atr_length - 1)

            # 5-1. 현재 캔들의 중앙 가격 (Typical Price) 계산
            median_price = (time_ordered_high[current_price_idx] + time_ordered_low[current_price_idx]) / 2

            # 5-2. 기본 밴드 (Basic Bands) 계산
            # 현재 캔들의 ATR 값을 사용하여 기본적인 상단 및 하단 밴드를 계산합니다.
            # 파인스크립트의 `up = src - (Multiplier * atr)` 및 `dn = src + (Multiplier * atr)`에 해당합니다.
            current_up_calc = round(median_price - _multiplier * time_ordered_atr[i], Indicators._ROUND_PRECISION)
            current_dn_calc = round(median_price + _multiplier * time_ordered_atr[i], Indicators._ROUND_PRECISION)
            
            # 5-3. 밴드 조정 로직 (파인스크립트의 `up := ...` 및 `dn := ...` 부분)
            # 밴드들은 단순히 계산된 값을 따르지 않고, 이전 캔들의 종가와 이전 밴드 값을 기반으로 조정됩니다.
            # 이는 밴드가 "트레일링 스톱"처럼 작동하여, 추세가 지속되는 동안에는 반대 방향으로 움직이지 않게 합니다.

            # 첫 계산 시점 또는 초기값 처리 (파인스크립트의 nz(value[1], value)에 해당)
            if i == 0:
                up_band[i] = current_up_calc
                dn_band[i] = current_dn_calc
            else:
                # 이전 캔들 종가
                prev_close = time_ordered_close[current_price_idx-1]
                # 이전 캔들의 up 밴드 (up1)
                prev_up_band = up_band[i-1] # nz(up[1], up)와 유사한 역할
                # 이전 캔들의 dn 밴드 (dn1)
                prev_dn_band = dn_band[i-1] # nz(dn[1], dn)와 유사한 역할

                # up 밴드 (상승 추세 시 하단 밴드) 조정:
                # '이전 캔들 종가가 이전 up 밴드보다 높았다면 (추세가 상승이었다면)'
                #   -> 현재 up 밴드는 '현재 계산된 up 밴드'와 '이전 up 밴드' 중 더 큰 값 (아래로 내려가지 않음)
                # '그렇지 않다면 (추세가 하락이거나 전환됐다면)'
                #   -> 현재 up 밴드는 '현재 계산된 up 밴드'
                if prev_close > prev_up_band:
                    up_band[i] = max(current_up_calc, prev_up_band)
                else:
                    up_band[i] = current_up_calc
                
                # dn 밴드 (하락 추세 시 상단 밴드) 조정:
                # '이전 캔들 종가가 이전 dn 밴드보다 낮았다면 (추세가 하락이었다면)'
                #   -> 현재 dn 밴드는 '현재 계산된 dn 밴드'와 '이전 dn 밴드' 중 더 작은 값 (위로 올라가지 않음)
                # '그렇지 않다면'
                #   -> 현재 dn 밴드는 '현재 계산된 dn 밴드'
                if prev_close < prev_dn_band:
                    dn_band[i] = min(current_dn_calc, prev_dn_band)
                else:
                    dn_band[i] = current_dn_calc
            
            # 5-4. 추세 방향 (trend) 결정 (파인스크립트의 `trend := ...` 부분)
            # 추세 방향은 현재 캔들의 종가와 이전 캔들의 밴드 값, 그리고 이전 추세 방향에 따라 결정됩니다.

            # 첫 SuperTrend 계산 시점 (_atr_length 인덱스)
            if i == 0:
                # 초기 추세는 종가가 dn_band(상단 밴드)보다 작거나 같으면 하락(-1), 아니면 상승(1)으로 설정
                if time_ordered_close[current_price_idx] <= dn_band[i]: # 파인스크립트는 여기서 dn_band[i]를 사용.
                    trend_direction[i] = -1 # 하락 추세
                else:
                    trend_direction[i] = 1  # 상승 추세
            else:
                # 이전 추세 방향
                prev_trend = trend_direction[i-1] # nz(trend[1], trend)와 유사

                # 파인스크립트 로직:
                # 1. 이전 추세가 하락(-1)이었고, 현재 종가가 이전 dn 밴드(dn_band[i-1])보다 높다면 => 상승 추세(1)로 전환
                # 2. 이전 추세가 상승(1)이었고, 현재 종가가 이전 up 밴드(up_band[i-1])보다 낮다면 => 하락 추세(-1)로 전환
                # 3. 위 조건에 해당하지 않으면 => 이전 추세 유지
                
                # 🚨 주의: 파인스크립트는 `close > dn1` 또는 `close < up1`에서 `dn1`과 `up1`이 각각 `dn[1]`과 `up[1]`(이전 캔들의 밴드)을 참조합니다.
                # 아래 파이썬 코드도 이를 반영하여 `dn_band[i-1]`과 `up_band[i-1]`을 사용합니다.
                
                if prev_trend == -1 and time_ordered_close[current_price_idx] > prev_dn_band: # 하락 -> 상승 전환 조건
                    trend_direction[i] = 1 # 상승
                elif prev_trend == 1 and time_ordered_close[current_price_idx] < prev_up_band: # 상승 -> 하락 전환 조건
                    trend_direction[i] = -1 # 하락
                else:
                    trend_direction[i] = prev_trend # 추세 유지

            # 5-5. 최종 SuperTrend 값 결정 (trend와 밴드의 결합)
            # 최종 SuperTrend 라인은 추세 방향에 따라 up_band 또는 dn_band 중 하나가 됩니다.
            # trend가 1 (상승)이면 up_band를 따르고, trend가 -1 (하락)이면 dn_band를 따릅니다.
            if trend_direction[i] == 1: # 상승 추세일 경우
                supertrend_values[i] = up_band[i] # SuperTrend 라인은 하단 밴드 (up_band)를 따름
            else: # 하락 추세일 경우 (-1)
                supertrend_values[i] = dn_band[i] # SuperTrend 라인은 상단 밴드 (dn_band)를 따름

            # 🚨 새로 추가된 신호 감지 로직 🚨
            if i > 0: # 첫 번째 캔들 이후부터 추세 변화 감지
                if trend_direction[i] != trend_direction[i-1]: # 추세 방향이 이전과 다르면
                    if trend_direction[i] == 1: # 하락(-1) -> 상승(1)으로 바뀌었으면
                        signals[i] = 1 # 매수 신호 (Buy Signal)

                    elif trend_direction[i] == -1: # 상승(1) -> 하락(-1)으로 바뀌었으면
                        signals[i] = -1 # 매도 신호 (Sell Signal)

            # 첫 번째 유효 ATR 캔들에서는 이전 추세가 없으므로 신호를 발생시키지 않거나,
            # 초기 추세 방향에 따라 첫 신호를 결정할 수도 있습니다 (예: 캔들이 시작부터 상승 추세면 1).
            # 여기서는 명확한 "변화" 시점에만 신호를 발생시키도록 구현했습니다.

        # 6. 결과 반환 방식 변경 ↩️
        # _array 값에 따라 특정 인덱스의 신호 값 또는 전체 신호 리스트를 반환합니다.
        # 기존 _array 파라미터는 SuperTrend 지표 값을 위한 것이었지만,
        # 이제는 신호 값을 반환하는 용도로 활용합니다.
        result_signals = signals[::-1]
        result_stoploss = supertrend_values[::-1]

        if _array is not None:
            if len(result_signals) > _array:
                return result_signals[_array], result_stoploss[_array] # 특정 인덱스의 신호 반환 (0: 가장 최근 신호)
            else:
                raise ValueError(f"SuperTrend 신호에 대한 유효하지 않은 _array 인덱스입니다. 결과 리스트는 {len(result_signals)}개의 요소를 가지고 있지만, 인덱스 {_array}가 요청되었습니다.")

        return result_signals, result_stoploss # 전체 신호 값 리스트 반환