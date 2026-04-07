import numpy as np

# 'ts'라는 키값이 정확히 필요한 이유가 여기 정의됩니다.
OHLC_DT = np.dtype([
    ('timestamp', 'i8'), 
    ('open', 'f8'), 
    ('high', 'f8'), 
    ('low', 'f8'), 
    ('close', 'f8'), 
])