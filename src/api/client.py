import time, random
from ..config import *
from typing import Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from functools import lru_cache
from typing import Union, Dict
from ..shared.msg import get_logger
from ..shared.enums import KlineIntervals
from ..shared.errors import ERROR_MAP, BinanceClientException, POSITION_MODE_ALREADY_SET_CODE


logger = get_logger("BINANCE_CLIENT")

@lru_cache(maxsize=1)
def get_binance_client(api_key: str, api_secret: str):
    official_client = Client(api_key, api_secret)
    return BinanceClient(client=official_client)

class BinanceClient:

    def __init__(self, client: Client):
        self.client = client
        logger.info("BinanceClient instance created and initialized.")

    @staticmethod
    def _safe_api_call(api_method, *args, **kwargs) -> Union[Dict, list, None]:
        attempt = 0
        max_retries = MAX_RETRIES

        while attempt < max_retries:
            try:
                return api_method(*args, **kwargs)

            except (BinanceAPIException, BinanceRequestException) as e:
                # 예외 타입에 상관없이 'code' 속성을 안전하게 가져옵니다.
                error_code = getattr(e, 'code', None)
                
                # 재시도하지 않고 함수를 종료하는 비-치명적 오류
                if error_code in [-2011, POSITION_MODE_ALREADY_SET_CODE]:
                    logger.warning(f"Non-fatal API error ({error_code}): {e.message}. This is likely a non-fatal race condition or a state already set.")
                    return None
                
                # 재시도 불가능한 치명적 오류: 봇을 종료해야 함
                if error_code in [-1002, -1003]: # UNAUTHORIZED, TOO_MANY_REQUESTS
                    logger.critical(f"Fatal API error ({error_code}): {e.message}. Exiting...", exc_info=True)
                    exception_class = ERROR_MAP.get(e.code, ERROR_MAP["default"])
                    raise exception_class(message=e.message, code=e.code)

                # 그 외 재시도 가능한 일시적 오류에 대해 지수 백오프 적용
                logger.warning(f"Temporary API error ({error_code}): {e.message}. Retrying... ({attempt + 1}/{max_retries})")
                
                attempt += 1
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(min(sleep_time, MAX_RETRY_DELAY))

            except Exception as e:
                logger.critical(f"Unexpected error during API call: {e}. Exiting...", exc_info=True)
                raise BinanceClientException(f"Unexpected error: {e}")

        logger.error(f"Failed to call API method {api_method.__name__} after {max_retries} attempts.")
        return None

    def change_margin_type(self, symbol, marginType):
        return self._safe_api_call(self.client.futures_change_margin_type, symbol=symbol, marginType=marginType)
        
    def futures_account(self):
        return self._safe_api_call(self.client.futures_account)

    def futures_get_all_orders(self):
        return self._safe_api_call(self.client.futures_get_open_orders)

    def get_orderbook_ticker(self, symbol: str):
        return self._safe_api_call(self.client.futures_orderbook_ticker, symbol=symbol)

    def create_order(self, **kwargs):
        return self._safe_api_call(self.client.futures_create_order, **kwargs)

    def cancel_all_open_orders(self, symbol):
        return self._safe_api_call(self.client.futures_cancel_all_open_orders, symbol=symbol)

    def get_symbol_info(self, symbol: str) -> dict | None:

        response = self._safe_api_call(self.client.futures_exchange_info)
        if response:
            for symbol_info in response.get('symbols', []):
                if symbol_info.get('symbol') == symbol:
                    return symbol_info
        return None
        
    def futures_exchange_info(self):
        return self._safe_api_call(self.client.futures_exchange_info)

    def futures_position_information(self, symbol: Optional[str] = None) -> list[dict]:
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._safe_api_call(self.client.futures_position_information, **params)

    def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        if interval not in KlineIntervals._value2member_map_:
            logger.error(f"Invalid K-lines interval: {interval}. Allowed values: {KlineIntervals._value2member_map_}")
            raise ValueError("Invalid K-lines interval")
        
        if not (1 <= limit <= VALID_KLINES_LIMIT_MAX):
            logger.error(f"Invalid K-lines data count: {limit}. Please enter a value between 1 and {VALID_KLINES_LIMIT_MAX}.")
            raise ValueError("Invalid K-lines data count")

        return self._safe_api_call(self.client.futures_klines, symbol=symbol, interval=interval, limit=limit)
    
    def get_futures_balance(self) -> list | None:
        return self._safe_api_call(self.client.futures_account_balance)

    def futures_change_leverage(self, symbol: str, leverage: int) -> dict | None:
        return self._safe_api_call(self.client.futures_change_leverage, symbol=symbol, leverage=leverage)

    def futures_change_position_mode(self, dualSidePosition: bool) -> dict | None:
        params = {
            'dualSidePosition': str(dualSidePosition).lower()
        }
        return self._safe_api_call(self.client.futures_change_position_mode, **params)

    def cancel_order(self, symbol: str, orderId: Union[int, str]) -> dict | None:
        return self._safe_api_call(self.client.futures_cancel_order, symbol=symbol, orderId=orderId)

