# src/shared/typings.py
import typing as T
from decimal import Decimal, getcontext, ROUND_DOWN
from collections import deque

# 1. 별칭 정의 (중요: 여기서 이름이 틀리면 AttributeError가 납니다)
D = Decimal
ctx = getcontext
DOWN = ROUND_DOWN
deque_obj = deque  # 이 줄이 반드시 있어야 합니다!

# 2. typing 모듈의 타입들을 재선언
Union = T.Union
Dict = T.Dict
List = T.List
Any = T.Any
Optional = T.Optional
Tuple = T.Tuple
Deque = T.Deque
DefaultDict = T.DefaultDict
Callable = T.Callable
Type = T.Type

# 3. 커스텀 복합 타입
ResultData = T.Union[T.Dict[str, T.Any], T.List[T.Any], None]
Numeric = T.Union[Decimal, float, int, str]

# 4. 와일드카드(*) 호출 시 내보낼 목록 (AttributeError 방지용)
__all__ = [
    'Union', 'Dict', 'List', 'Any', 'Optional', 'Tuple', 
    'Deque', 'DefaultDict', 'Callable', 'Type',
    'D', 'Decimal', 'getcontext', 'ctx', 'ROUND_DOWN', 'DOWN',
    'deque_obj', 'ResultData', 'Numeric'
]