class Strategies():

    def system1(_high, _low, _array=0, _high_len=28, _low_len=14):

        result = []

        for i in range(len(_low)):

            index = len(_low) - i - 1

            if i >= max(_high_len,_low_len) - 1:

                highests = []

                for ii in range(_high_len):

                    highests.append(_high[ii+index])

                higest = max(highests)

                lowests = []

                for ii in range(_low_len):

                    lowests.append(_low[ii+index])

                lowest = min(lowests)

                long = higest == _high[index]
                short = lowest == _low[index]

                result.insert(0, [long, short])

        if _array != None:
            result = result[_array]
        return result
