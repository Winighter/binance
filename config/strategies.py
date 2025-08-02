class Strategies():

    @staticmethod
    def system(high_prices, low_prices, _high_len, _low_len):
        """
        현재 고가가 _high_len 기간 내에서 가장 높은 값인지,
        현재 저가가 _low_len 기간 내에서 가장 낮은 값인지를 계산합니다.

        Args:
            high_prices (list): 고가 목록입니다.
            low_prices (list): 저가 목록입니다 (high_prices와 길이가 같아야 합니다).
            _high_len (int, optional): 최고 고가를 찾기 위한 조회 기간입니다. 기본값은 28입니다.
            _low_len (int, optional): 최저 저가를 찾기 위한 조회 기간입니다. 기본값은 14입니다.

        Returns:
            list: [long, short] 불리언 쌍의 목록입니다.
                  'long'은 현재 고가가 _high_len 윈도우에서 가장 높으면 True입니다.
                  'short'은 현재 저가가 _low_len 윈도우에서 가장 낮으면 True입니다.
                  목록은 오래된 것부터 최신 순서로 정렬됩니다.
        """
        result = []

        # 입력 데이터 유효성 검사
        if len(high_prices) != len(low_prices):
            raise ValueError("high_prices and low_prices must have the same length.")
        if _high_len <= 0 or _low_len <= 0:
            raise ValueError("_high_len and _low_len must be positive integers.")
        if not high_prices:
            return []

        for i in range(len(high_prices)):
            # index는 리스트의 끝에서부터 계산된 역방향 인덱스입니다.
            # 즉, high_prices[index]가 현재 시점의 고가이고, index + ii는 과거의 데이터를 참조합니다.
            index = len(low_prices) - i - 1

            # 충분한 과거 데이터가 있을 때만 계산을 수행합니다.
            if i >= max(_high_len, _low_len) - 1:

                current_high_prices_window = high_prices[index : index + _high_len]
                current_highest = max(current_high_prices_window)

                highests_window = []
                for ii in range(_high_len):
                    highests_window.append(high_prices[ii + index])
                current_highest = max(highests_window)

                lowests_window = []
                for ii in range(_low_len):
                    lowests_window.append(low_prices[ii + index])
                current_lowest = min(lowests_window)

                long_signal = (current_highest == high_prices[index])
                short_signal = (current_lowest == low_prices[index])

                result.insert(0, [long_signal, short_signal])

        return result