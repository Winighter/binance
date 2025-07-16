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

        time_ordered_src = _src[::-1]
        
        current_rma = round(sum(time_ordered_src[:_length]) / _length, Indicators._ROUND_PRECISION)
        rma_values.append(current_rma)

        for i in range(_length, len(time_ordered_src)):
            current_rma = alpha * time_ordered_src[i] + (1 - alpha) * current_rma
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