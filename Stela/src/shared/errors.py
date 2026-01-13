import dataclasses
from typing import Union

@dataclasses.dataclass
class BinanceClientException(Exception):
    """모든 바이낸스 관련 예외의 기본 클래스"""
    message: str
    code: Union[int, None] = None
    def __str__(self): 
        return f"[{self.code}] {self.message}" if self.code else self.message

# --- 봇의 행동 지침에 따른 에러 분류 ---
class BinanceFatalError(BinanceClientException): 
    """즉시 봇을 중단해야 함 (인증 실패, IP 차단 등)"""
    pass

class BinanceRetryableError(BinanceClientException): 
    """지수 백오프 후 다시 시도 (네트워크, 서버 과부하 등)"""
    pass

class BinanceBusinessError(BinanceClientException): 
    """이 요청만 건너뜀 (잔고 부족, 잘못된 파라미터 등)"""
    pass

class BinanceStateError(BinanceClientException): 
    """이미 처리된 상태 (이미 모드 설정됨, 이미 취소됨 등)"""
    pass

class BinanceConflictError(BinanceClientException): 
    """이미 처리된 상태 (이미 모드 설정됨, 이미 취소됨 등)"""
    pass

class ErrorManager:
    # 1. 봇을 즉시 꺼야 하는 치명적 코드
    FATAL_CODES = []

    # 2. 지수 백오프로 무조건 살려내야 하는 코드
    RETRYABLE_CODES = []
    
    # 3. 설정 관련 (성공으로 간주해도 되는 코드)
    STATE_CODES = [-4046, -4059]

    # 3. 설정 관련 (성공으로 간주해도 되는 코드)
    CONFLICT_CODES = [-4067]

    # 4. 사용자 친화적인 한글 메시지 매핑
    ERROR_DESCRIPTIONS = {
        -4046: "Margin type is already set to the requested mode.",
        -4059: "Position mode is already configured as requested.",
        -4067: "Cannot change position mode while there are open orders. Please cancel all orders and try again."
    }

    @classmethod
    def get_exception_class(cls, code: int):
        """에러 코드를 보고 어떤 예외 클래스로 던질지 결정"""
        if code in cls.FATAL_CODES: return BinanceFatalError
        if code in cls.RETRYABLE_CODES: return BinanceRetryableError
        if code in cls.CONFLICT_CODES: return BinanceConflictError
        if code in cls.STATE_CODES: return BinanceStateError
        return BinanceBusinessError

    @classmethod
    def get_friendly_message(cls, code: int, server_msg: str) -> str:
        """한글 설명이 있으면 반환하고, 없으면 서버가 보낸 메시지를 반환"""
        return cls.ERROR_DESCRIPTIONS.get(code, f"서버 메시지: {server_msg}")