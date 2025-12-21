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
        result = self._safe_api_call(self.client.futures_get_open_orders)
        if result == []:
            return None
        return result

    def get_orderbook_ticker(self, symbol: str):
        return self._safe_api_call(self.client.futures_orderbook_ticker, symbol=symbol)

    def create_order(self, **kwargs):
        return self._safe_api_call(self.client.futures_create_order, **kwargs)

    def create_test_order(self, **kwargs):
        return self._safe_api_call(self.client.futures_create_test_order, **kwargs)
        
    def cancel_all_open_orders(self, symbol):
        return self._safe_api_call(self.client.futures_cancel_all_open_orders, symbol=symbol)

    def get_symbol_info(self, symbol: str) -> dict | None:

        response = self._safe_api_call(self.client.futures_exchange_info)
        if response:
            for symbol_info in response.get('symbols', []):
                if symbol_info.get('symbol') == symbol:
                    return symbol_info
        return None

    def _futures_aggregate_trades(self, symbol:str):
        return self._safe_api_call(self.client.futures_aggregate_trades, symbol=symbol)

    def _futures_open_interest(self, symbol: str, period:str):
        '''
        symbol: 해당 데이터가 집계된 선물 계약의 거래 쌍입니다. (예: XRP/USDT)
        sumOpenInterest(총 미결제 약정 수량): 해당 심볼의 해당 시점(timestamp)에 미결제된 총 계약 수입니다. 이는 일반적으로 기초 자산 단위로 표시됩니다. (예: XRP 개수)
        sumOpenInterestValue(총 미결제 약정 가치): 해당 시점의 미결제 약정 수량(sumOpenInterest)을 현재 시장 가격으로 환산한 USDT 또는 BUSD 기준의 총 가치입니다.
        CMCCirculatingSupply(CMC 유통 공급량):암호화폐 데이터 제공업체인 **CoinMarketCap(CMC)**에서 제공하는 해당 기초 자산의 유통 공급량입니다. (선물 거래와 직접적인 관계는 없으나, 시장 분석 지표로 제공됨)
        timestamp: 해당 데이터가 기록된 시점을 밀리초(milliseconds) 단위로 나타낸 Unix 시간입니다.
        기본값 30개
        '''
        return self._safe_api_call(self.client.futures_open_interest_hist, symbol=symbol, period=period)

    def _futures_funding_rate(self, symbol: str) -> list:
        '''
        펀딩비는 과거부터 최신 순으로 데이터를 받아오며 각 데이터는 8시간 간격으로 기록된 데이터
        {'symbol': 'XRPUSDT', 'fundingTime': 1755907200004, 'fundingRate': '0.00010000', 'markPrice': '3.07401750'}
        '''
        return self._safe_api_call(self.client.futures_funding_rate, symbol=symbol)

    def futures_exchange_info(self):
        return self._safe_api_call(self.client.futures_exchange_info)

    def futures_position_information(self, symbol: Optional[str] = None) -> list[dict]:
        params = {}
        if symbol:
            params['symbol'] = symbol

        result = self._safe_api_call(self.client.futures_position_information, **params)
        if result == []:
            return None
        return result

    def get_klines(self, symbol: str, interval: str, limit: int) -> list:
        if interval not in KlineIntervals._value2member_map_:
            logger.error(f"Invalid K-lines interval: {interval}. Allowed values: {KlineIntervals._value2member_map_}")
            raise ValueError("Invalid K-lines interval")
        
        if not (1 <= limit <= VALID_KLINES_LIMIT_MAX):
            logger.error(f"Invalid K-lines data count: {limit}. Please enter a value between 1 and {VALID_KLINES_LIMIT_MAX}.")
            raise ValueError("Invalid K-lines data count")

        return self._safe_api_call(self.client.futures_klines, symbol=symbol, interval=interval, limit=limit)

    def get_mark_klines(self, symbol: str, interval: str, limit: int) -> list:
        if interval not in KlineIntervals._value2member_map_:
            logger.error(f"Invalid K-lines interval: {interval}. Allowed values: {KlineIntervals._value2member_map_}")
            raise ValueError("Invalid K-lines interval")
        
        if not (1 <= limit <= VALID_KLINES_LIMIT_MAX):
            logger.error(f"Invalid K-lines data count: {limit}. Please enter a value between 1 and {VALID_KLINES_LIMIT_MAX}.")
            raise ValueError("Invalid K-lines data count")

        return self._safe_api_call(self.client.futures_mark_price_klines, symbol=symbol, interval=interval, limit=limit)

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

    def _futures_liquidation_orders(self, symbol:str):
        return self._safe_api_call(self.client.futures_liquidation_orders,symbol=symbol)

    ### LONG SHORT RATIO FUNCTIONS ###
    def _futures_top_longshort_account_ratio(self, symbol:str, period:str) -> list:
        '''
        이 함수는 계정(Account)의 수를 기준으로 롱/숏 비율을 계산합니다.

        측정 기준: 상위(Top (잔고 기준 상위 20%)) 트레이더 그룹에 속하는 계정 중, 롱 포지션을 보유한 계정의 수 대 숏 포지션을 보유한 계정의 수의 비율입니다.
        핵심: '돈의 규모'가 아니라 **'사람의 수'**를 셉니다.
        의미: 상위 고래(Whale) 트레이더들이 어떤 포지션을 취하는 계정이 더 많은지를 보여주며, 시장 심리의 대중적인 경향을 파악할 수 있습니다.
        예를 들어, 이 비율이 2.0이라면, 숏 포지션을 가진 계정보다 롱 포지션을 가진 계정이 2배 많다는 뜻입니다.
        '''
        return self._safe_api_call(self.client.futures_top_longshort_account_ratio, symbol=symbol,period=period)

    def _futures_top_longshort_position_ratio(self, symbol:str, period:str) -> list:
        '''
        이 함수는 **포지션 규모(Volume)**를 기준으로 롱/숏 비율을 계산합니다.

        측정 기준: 상위(Top (잔고 기준 상위 20%)) 트레이더 그룹이 보유한 전체 롱 포지션의 계약 규모 대 전체 숏 포지션의 계약 규모의 비율입니다.
        핵심: '사람의 수'가 아니라 **'금액 또는 수량의 규모'**를 셉니다.
        의미: 상위 트레이더들의 실제 자금 투입 규모가 어느 방향(롱 또는 숏)으로 기울어져 있는지를 나타냅니다.
        계정 수는 적더라도 한 명의 트레이더가 막대한 규모의 롱 포지션을 잡으면 이 비율이 크게 상승할 수 있습니다.
        이는 시장의 실질적인 자금 흐름을 보여줍니다.
        '''
        return self._safe_api_call(self.client.futures_top_longshort_position_ratio, symbol=symbol,period=period)

    def _futures_taker_longshort_ratio(self, symbol:str, period:str) -> list:
        '''
        이 함수는 **체결된 거래량(Volume)**을 기준으로 롱/숏 비율을 계산합니다.

        측정 기준: 일정 시간 동안 시장가로 체결된 (Taker) 매수 거래량(Long Volume) 대 **매도 거래량(Short Volume)**의 비율입니다.
        핵심: 현재 보유 포지션이 아니라, **새롭게 시장에 유입된 매수/매도 압력(공격적인 거래)**을 측정합니다.
        의미: 현재 시장에서 **공격적인 매수세(롱)**가 강한지, **공격적인 매도세(숏)**가 강한지를 보여줍니다.
        이 수치는 **단기적인 시장의 모멘텀(추진력)**을 파악하는 데 가장 직접적인 지표입니다.
        '''
        return self._safe_api_call(self.client.futures_taker_longshort_ratio, symbol=symbol,period=period)

    def _futures_global_longshort_ratio(self, symbol:str, period:str) -> list:
        '''
        이 함수는 **전체 계정(All Accounts)**의 포지션 규모를 기준으로 롱/숏 비율을 계산합니다.

        측정 기준: 바이낸스 선물 시장에 참여하는 모든 트레이더가 보유한 전체 롱 포지션 규모 대 전체 숏 포지션 규모의 비율입니다.
        핵심: 상위 트레이더뿐만 아니라 모든 일반 트레이더의 자금을 포함합니다.
        의미: 시장 전체의 일반적인 정서와 포지션 쏠림 현상을 파악할 수 있습니다.
        상위 트레이더의 데이터와 비교하여, 개인 투자자들의 심리가 상위 트레이더와 일치하는지 또는 반대되는지를 분석하는 데 유용합니다.
        '''
        return self._safe_api_call(self.client.futures_global_longshort_ratio, symbol=symbol,period=period)