from config.msg import logger
from binance.client import Client
import config.config as app_config
from binance.exceptions import BinanceAPIException, BinanceRequestException


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret)
        self.symbol = app_config.SYMBOL.upper()
        # logger.info(f"BinanceClient initialized")

    # Helper Function
    def _safe_api_call(self, api_method, *args, **kwargs):
        try:
            response = api_method(*args, **kwargs)
            # logger.info(f"'{api_method.__name__}' API call successful.")
            return response
        except BinanceAPIException as e:
            logger.error(f"Binance API Error Occurred. (Method: {api_method.__name__}): {e}")
            return None
        except BinanceRequestException as e:
            logger.error(f"Network or Request Error Occurred. (Method: {api_method.__name__}): {e}")
            return None
        except Exception as e:
            logger.error(f"An Unexpected Error Occurred. (Method: {api_method.__name__}): {e}")
            return None

    def get_account_balance(self):
        """
        선물 계좌의 현재 잔고 정보를 검색합니다.

        Returns:
            list: 계좌 잔고 항목들의 리스트 (각 항목은 딕셔너리 형태),
                  또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_account_balance)

    def get_position_mode(self) -> bool | None:
        """
        현재 포지션 모드(양방향 또는 단방향)를 검색합니다.

        Returns:
            bool: 양방향 포지션 모드가 활성화되어 있으면 True, 단방향이면 False를 반환합니다.
                  오류가 발생하거나 예상치 못한 응답인 경우 None을 반환합니다.
        """
        response = self._safe_api_call(self.client.futures_get_position_mode)
        if response and isinstance(response, dict) and 'dualSidePosition' in response:
            return response['dualSidePosition']
        logger.error(f"포지션 모드를 가져오지 못했거나 예상치 못한 응답입니다: {response}")
        return None

    def get_orderbook_ticker(self, symbol: str):
        """
        주어진 심볼의 최신 호가 정보(최고 매수/최저 매도 가격)를 검색합니다.

        Args:
            symbol (str): 호가를 검색할 거래 심볼 (예: 'BTCUSDT').

        Returns:
            dict: 호가 정보를 담은 딕셔너리, 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_orderbook_ticker, symbol=symbol.upper())

    def get_position_information(self, symbol: str):
        """
        주어진 심볼에 대한 현재 포지션 정보를 검색합니다.

        Args:
            symbol (str): 포지션 정보를 검색할 거래 심볼 (예: 'BTCUSDT').

        Returns:
            list: 포지션 정보를 담은 딕셔너리 리스트, 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_position_information, symbol=symbol.upper())

    def change_leverage(self, symbol: str, leverage: int):
        """
        주어진 심볼의 레버리지를 변경합니다.

        Args:
            symbol (str): 레버리지를 변경할 거래 심볼 (예: 'BTCUSDT').
            leverage (int): 설정할 새 레버리지 값 (정수).

        Returns:
            dict: 레버리지 변경 응답을 담은 딕셔너리, 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_change_leverage, symbol=symbol.upper(), leverage=leverage)

    def get_klines(self, symbol: str, interval: str, limit: int = app_config.DEFAULT_KLINE_LIMIT):
        """
        주어진 심볼의 캔들스틱(K-line) 데이터를 검색합니다.

        Args:
            symbol (str): 캔들스틱 데이터를 검색할 거래 심볼 (예: 'BTCUSDT').
            interval (str): 캔들스틱의 시간 간격 (예: '1m', '5m', '1h').
            limit (int, optional): 가져올 캔들스틱 데이터의 최대 개수. 기본값은 app_config.DEFAULT_KLINE_LIMIT.

        Returns:
            list: 캔들스틱 데이터를 담은 리스트 (각 캔들은 리스트 형태), 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_klines, symbol=symbol.upper(), interval=interval, limit=limit)

    def change_position_mode(self, dual_side_position: str):
        """
        선물 계좌의 포지션 모드(양방향 또는 단방향)를 변경합니다.

        Args:
            dual_side_position (str): 'true' (양방향 모드) 또는 'false' (단방향 모드) 문자열.

        Returns:
            dict: 포지션 모드 변경 응답을 담은 딕셔너리, 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_change_position_mode, dualSidePosition=dual_side_position)

    def create_market_order(self, symbol: str, side: str, positionSide:str, quantity: float):
        """
        지정된 심볼에 대한 시장가 주문을 생성합니다.

        Args:
            symbol (str): 주문을 생성할 거래 심볼 (예: 'BTCUSDT').
            side (str): 주문 방향 ('BUY' 또는 'SELL').
            positionSide (str): 포지션 방향 ('LONG', 'SHORT', 'BOTH').
            quantity (float): 주문 수량.

        Returns:
            dict: 주문 생성 응답을 담은 딕셔너리, 또는 API 호출 실패 시 None을 반환합니다.
        """
        return self._safe_api_call(self.client.futures_create_order, symbol=symbol.upper(), side=side, type='MARKET', positionSide=positionSide, quantity=quantity)

