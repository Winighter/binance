class Indicator():

    # Simple Moving Average 
    def sma(_src:list, _length:int, _array:int = 0):

        l = _length

        result = []

        if len(_src) < l:
            return
        else:
            for i in range(len(_src)):

                src = _src[i:i+l]

                if len(src) == l:

                    sma = round(sum(src)/_length,4)

                    result.append(sma)
                else:
                    break

        if _array != None:
            result = result[_array]
           
        return result

    # Exponential Moving Average
    def ema(_src:list, _length:int, _array:int = 0):

        alpha = 2 / (_length + 1)

        ema_list = []
        sum_list = []

        for i in range(len(_src)):

            i = len(_src)-i-1

            if i == len(_src)-_length:

                first = []

                for ii in range(len(_src)-i):

                    f = _src[len(_src)-ii-1]
                    first.append(f)
                fEma = sum(first)/_length
                fEma = round(fEma, 4)
                sum_list.append(fEma)
                ema_list.append(fEma)

            if i < len(_src)-_length:

                ema = alpha * _src[i] + (1 - alpha) * sum_list[len(sum_list)-1]
                ema = round(ema, 4)
                sum_list.append(ema)
                ema_list.insert(0, ema)

        result = ema_list

        if _array != None:
            result = ema_list[_array]

        return result

    # Relative Moving Average
    def rma(_src:list, _length:int, _array:int = 0):

        alpha = round(1 / (_length), 4)

        if len(_src) == 2:
            rma = alpha * _src[0] + (1 - alpha) * _src[1]
            rma = round(rma, 4)
            return rma
        else:
            first_rma = []
            rma_list = []

            for i in range(len(_src) + 1):

                if i == _length-1:

                    for ii in range(i+1):
                        ii = (len(_src)-1 - ii)
                        first_rma.append(_src[ii])

                    first = round(sum(first_rma)/(i+1),4)
                    rma_list.append(first)

                if i > _length-1 and i < len(_src):
                    index = i - _length
                    rma = (alpha * _src[len(_src)-i -1]) + ((1 - alpha) * (rma_list[index]))
                    rma = round(rma, 4)
                    rma_list.append(rma)

            result = rma_list

            if _array != None:
                result = rma_list[_array-1]
            return result

    # Relative Strength Index
    def rsi(_src:list, _length:int, _array:int = 0):

        upward_list = []
        downward_list = []
        upper_list = []
        down_list = []
        rsi_list = []

        for i in range(len(_src)):
            index = len(_src) - i - 1
            d = max(_src[index]-_src[index-1], 0)
            u = max(_src[index-1] - _src[index], 0)
            d = round(d,4)
            u = round(u,4)
            upward_list.append(u)
            downward_list.append(d)
            if index == 1:
                break

        for i in range(len(upward_list)):

            if i == _length-1:
                u_list = []
                d_list = []
                for ii in range(_length):
                    u_list.append(upward_list[ii])
                    d_list.append(downward_list[ii])

                first_u = sum(u_list)/_length
                first_u = round(first_u, 4)
                upper_list.append(first_u)

                first_d = sum(d_list)/_length
                first_d = round(first_d, 4)
                down_list.append(first_d)

            if i >= _length:
                urm = Indicator.rma([upward_list[i], upper_list[i-_length]], _length)
                upper_list.append(urm)

                drm = Indicator.rma([downward_list[i], down_list[i-_length]], _length)
                down_list.append(drm)

            if i == len(upward_list)-1:
                break

        for i in range(len(upper_list)):
            u = upper_list[i]
            d = down_list[i]
            rs = u / d
            rs = round(rs, 4)
            res = 100 - 100 / (1 + rs)
            res = round(res, 0)
            rsi_list.insert(0, res)

        if _array != None:
            return rsi_list[_array]
        else:
            return rsi_list

    # Ribbon
    def ribbon(_src:list, _length:int = 60, _array:int = 0):

        ema_src = Indicator.ema(_src, _length, None)

        ribbon_list = []

        for i in range(len(ema_src)):
            
            r = 0

            long = ema_src[i]
            short = ema_src[i+2]

            if long < short:
                r = 1

            ribbon_list.append(r)
            
            if i == len(ema_src) - 3:
                break

        result = ribbon_list

        if _array != None:
            result = ribbon_list[_array]

        return result
    
    # Candle
    def min_max(_src:list, _array:int = 0):

        min = 0.0
        max = 0.0
        min_list = []
        max_list = []

        for i in range(90):

            index = 89 - i

            close = _src[index]

            if i == 0:
                min = close
                max = close
                min_list.insert(0, min)
                max_list.insert(0, max)
                print(max)
            else:
                if close < min:
                    min = close

                if close > max:
                    max = close

                min_list.insert(0, min)
                max_list.insert(0, max)
        # print(max_list)
        if _array != None:
            return min_list[_array], max_list[_array]
        else:
            return min_list, max_list