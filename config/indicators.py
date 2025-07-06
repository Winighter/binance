class Indicators():

    # Simple Moving Average 
    def sma(_src:list, _length:int, _array:int = 0):

        result = []

        if len(_src) >= _length:

            for i in range(len(_src)):

                src = _src[i:i+_length]

                if len(src) == _length:

                    sma = round(sum(src)/_length,6)

                    result.append(sma)
                else:
                    break

        if _array != None:
            result = result[_array]
           
        return result

    # Relative Moving Average
    def rma(_src:list, _length:int, _array:int = 0):

        alpha = round(1 / (_length), 6)
        sums = []
        result = []

        for i in range(len(_src)):

            index = len(_src) - i - 1

            if i >= _length - 1:

                srcs = []

                for ii in range(_length):

                    srcs.append(_src[index-ii])

                if i == _length - 1:
                    sum = Indicators.sma(srcs, _length)
                    sum = round(sum, 7)
                    sums.append(sum)
                    result.append(sum)
                else:
                    a = round(alpha * _src[len(_src)-i-_length], 7)
                    b = round((1 - alpha) * sums[i-_length], 7)
                    sum = a + b
                    sum = round(sum, 7)
                    sums.append(sum)
                    result.insert(0, sum)
        
            if index == _length - 1:
                break

        if _array != None:
            result = result[_array]
        return result

    def atr(_high, _low, _close, _length:int = 28, _array:int = 0):

        tr_list = []

        for i in range(len(_high)):

            index = len(_close) - i - 1

            if i == 0:
                trueRange = _high[index] - _low[index]
            else:
                trueRange = max(max(_high[index] - _low[index], abs(_high[index] - _close[index+1])), abs(_low[index] - _close[index+1]))

            trueRange = round(trueRange, 5)
            tr_list.insert(0, trueRange)

        result = Indicators.rma(tr_list, _length, None)

        if _array != None:
            result = result[_array]
        return result
