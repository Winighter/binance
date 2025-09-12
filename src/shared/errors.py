import dataclasses
from typing import Union, Dict

@dataclasses.dataclass
class BinanceClientException(Exception):
    message: str
    code: Union[int, None] = None

class BinanceRateLimitExceededError(BinanceClientException):
    pass

class BinanceInvalidTimestampError(BinanceClientException):
    pass

class BinanceInvalidSymbolError(BinanceClientException):
    pass

class BinanceAPIRequestError(BinanceClientException):
    def __init__(self, message, code=None):
        super().__init__(message, code=code)

# Standardizes error codes.
UNKNOWN_ERROR_CODE = -1000
RATE_LIMIT_EXCEEDED_CODE = -1003
INVALID_TIMESTAMP_CODE = -1021
BAD_PARAMETER_CODE = -1102
MARGIN_INSUFFICIENT_CODE = -2019
INVALID_SYMBOL_CODE = -1121
POSITION_MODE_ALREADY_SET_CODE = -4059


# A dictionary mapping error codes to exception classes.
# errors.py
...
# A dictionary mapping error codes to exception classes.
# Note: Maps to the class itself, not an instance.
ERROR_MAP: Dict[Union[int, str], BinanceClientException] = {
    "default": BinanceAPIRequestError,
    RATE_LIMIT_EXCEEDED_CODE: BinanceRateLimitExceededError,
    INVALID_TIMESTAMP_CODE: BinanceInvalidTimestampError,
    INVALID_SYMBOL_CODE: BinanceInvalidSymbolError,
    BAD_PARAMETER_CODE: BinanceAPIRequestError,
    MARGIN_INSUFFICIENT_CODE: BinanceAPIRequestError,
    UNKNOWN_ERROR_CODE: BinanceAPIRequestError,
    POSITION_MODE_ALREADY_SET_CODE: BinanceAPIRequestError,
}
...