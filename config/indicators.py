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
                rma = (alpha * _src[len(_src)-i -1 ]) + ((1 - alpha) * (rma_list[index]))
                rma = round(rma, 4)
                rma_list.append(rma)

        result = rma_list

        if _array != None:
            result = rma_list[_array-1]
        return result

    # Relative Strength Index
    def rsi(_src:list, _length:int, _array:int = 0):

        src_list = []
        up_list = []
        down_list = []
        rsi_list = []
        real_up_list = []
        real_down_list = []

        for i in range(len(_src)):
            index = len(_src)-i-1

            if i == 0:
                src_list.append(_src[index])
            else:
                src_list.append(_src[index])
                a = max(_src[index] - src_list[i-1],0)
                a = round(a, 4)
                up_list.append(a)

                b = max(src_list[i-1] - _src[index],0)
                b = round(b, 4)
                down_list.append(b)

        for i in range(len(up_list)+1):

            if i == _length -1:

                up = []
                down = []

                for ii in range(_length):
                    up.append(up_list[ii])
                    down.append(down_list[ii])

                first_up = round(sum(up)/_length, 4)
                first_down = round(sum(down)/_length, 4)

                real_up_list.append(first_up)
                real_down_list.append(first_down)

            if i > _length-1 and i < len(up_list) and i < len(down_list):

                asup = []
                asdown = []
                for ii in range(_length):

                    index = i - ii

                    if i == index:
                        asup.append(up_list[i])
                        asdown.append(down_list[i])

                    else:
                        if ii > len(real_up_list):
                            asup.append(up_list[index])
                            asdown.append(down_list[index])
                        else:
                            u = real_up_list[i-_length]
                            d = real_down_list[i-_length]
                            asup.append(u)
                            asdown.append(d)
    
                au = Indicator.rma(asup, _length)
                ad = Indicator.rma(asdown, _length)
                real_up_list.append(au)
                real_down_list.append(ad)

                rsi = round((au / (au + ad))*100, 2)
                rsi_list.insert(0, rsi)

        result = rsi_list
        if _array != None:
            result = rsi_list[_array]

        return result

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