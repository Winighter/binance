from ..shared.typings import *
import time, random, threading
from requests.exceptions import ConnectionError
from ..config import MAX_RETRIES, MAX_RETRY_DELAY
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from functools import lru_cache
from ..shared.msg import get_logger
from ..shared.enums import MarginType, OrderType, AssetType, Side, AlgoOrderType, PositionSide, KlineInterval
from ..shared.errors import *
from ..strategies.trading_params import SWING_LOOKBACK


logger = get_logger("BINANCE_CLIENT")

@lru_cache(maxsize=1)
def get_binance_client(api_key: str, api_secret: str):
    official_client = Client(api_key, api_secret, requests_params={'timeout': 20})
    return BinanceClient(client=official_client)


class SetupError(Exception):
    """Initial setup failed."""
    pass


class RateLimiter:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RateLimiter, cls).__new__(cls)
                cls._instance.used_weight = 0
                cls._instance.limit = 2400  # 바이낸스 선물 기본 제한
        return cls._instance

    def update_weight(self, response_headers):
        # 바이낸스 헤더에서 'X-MBX-USED-WEIGHT-1M' 값을 가져와 업데이트
        weight = response_headers.get('X-MBX-USED-WEIGHT-1M')
        if weight:
            self.used_weight = int(weight)

    def wait_if_needed(self):
        # 80% 사용 시 1초, 90% 사용 시 3초 쉬는 식의 유연한 대기
        if self.used_weight > 2100: # 약 90%
            logger.warning(f"Rate Limit 위험! (현재 {self.used_weight}) 3초간 대기합니다.")
            time.sleep(3)
        elif self.used_weight > 1800: # 약 75%
            time.sleep(0.5)

class BinanceClient:

    def __init__(self, client: Client):
        self.client = client
        self.max_retries = MAX_RETRIES
        self.max_retry_delay = MAX_RETRY_DELAY
        self.stop_event: threading.Event = None

    def set_stop_event(self, event):
        self.stop_event = event

    def _safe_api_call(self, func, *args, **kwargs) -> Union[Dict, list, None]:

        limiter = RateLimiter() # 싱글톤이라 어디서 호출해도 같은 객체
        attempt = 0
        method_name = getattr(func, '__name__', str(func))
        if method_name == "_request_futures_api" and len(args) >= 2:
            method_name = f"{args[0]}_{args[1]}" # 예: delete_algoOrder

        while attempt < self.max_retries:

            # 추가: 종료 신호가 발생했다면 즉시 중단
            if self.stop_event and self.stop_event.is_set():
                logger.info("Shutdown signal detected during API call. Aborting retry.")
                return None

            try:
                # 1. 실행 전 가중치 체크 (Adaptive Throttling)
                limiter.wait_if_needed()

                # 1. API 실행 (self는 BinanceClient 인스턴스여야 하므로 staticmethod를 해제하거나 인자를 조절해야 함)
                response = func(*args, **kwargs)

                if attempt > 0:
                    logger.info(f"Network reconnected successfully after {attempt} retries.")

                # 2. 가중치 업데이트 (중요!)
                # func를 실행한 'client' 객체의 마지막 응답 헤더를 가져옵니다.
                if hasattr(self.client, 'response') and self.client.response is not None:
                    limiter.update_weight(self.client.response.headers)
                    # (선택 사항) 제대로 업데이트 되는지 로그로 확인해보고 싶다면 아래 주석 해제
                    # logger.info(f"Weight Updated: {limiter.used_weight}")

                return response

            except ConnectionError as e:
                attempt += 1
                if attempt < self.max_retries:
                    # 1. 지수 백오프 계산
                    sleep_time = min((2 ** attempt) + random.uniform(0, 1), MAX_RETRY_DELAY)
                    logger.warning(
                        f"Network connection lost: {e}. "
                        f"Retrying {attempt}/{self.max_retries} in {sleep_time:.2f}s..."
                    )
                    
                    # 2. [중요] 단순 sleep 대신 종료 신호를 감시하며 대기
                    if not self._handle_retry_sleep(sleep_time):
                        # 종료 신호가 들어오면 루프를 탈출하여 함수 종료
                        logger.info("Shutdown detected during retry sleep. Aborting.")
                        break 
                    
                    # 3. continue를 하지 않아도 while문은 다시 돕니다.
                else:
                    # 최대 재시도 횟수를 넘었을 때의 처리 (기존 else 역할)
                    logger.error(f"Max retries ({self.max_retries}) reached due to ConnectionError.")
                    raise BinanceClientException(f"Network connection lost after max retries: {e}")

            except (BinanceAPIException, BinanceRequestException) as e:
                # 예외 타입에 상관없이 'code' 속성을 안전하게 가져옵니다.
                error_code = getattr(e, 'code', None)

                # [Action 1] 성격 분류 및 메시지 추출
                exc_class = ErrorManager.get_exception_class(error_code, method_name)
                friendly_msg = ErrorManager.get_friendly_message(error_code, e.message)

                # [Action 2] 등급별 대응
                # A. 치명적 오류 (봇 즉시 종료) 1순위
                if exc_class == BinanceFatalError:
                    logger.critical(f"Fatal API error ({error_code}): {friendly_msg}. Exiting...", exc_info=True)
                    raise exc_class(message=friendly_msg, code=error_code)

                # B. 이미 설정된 상태 (성공 처리) 2순위
                elif exc_class == BinanceStateError:
                    return logger.info(f"{friendly_msg}")

                # 3. Condition (신규): 조건 미충족 (경고 필요) 3순위
                elif exc_class == BinanceConflictError:
                    logger.warning(f"{friendly_msg}")
                    return None # 또는 특수한 리턴값

                # C. 재시도 가능 오류 (지수 백오프 적용) 4순위
                elif exc_class == BinanceRetryableError:
                    attempt += 1
                    if attempt < self.max_retries:
                        sleep_time = min((2 ** attempt) + random.uniform(0, 1), MAX_RETRY_DELAY)
                        logger.warning(f"🔄 Reconnect {attempt}/{self.max_retries}: {friendly_msg}. {sleep_time:.2f}초 후 다시 시도합니다.")
                        time.sleep(sleep_time)
                        continue
                elif exc_class == BinanceBusinessError:
                    logger.warning(f"Request aborted: {friendly_msg}")
                    return None  # 루프를 돌지 않고 바로 리턴
                else:
                    logger.warning(f"New Error code: {error_code} {e.message}")

            except Exception as e:
                logger.critical(f"Unexpected error during API call: {e}. Exiting...", exc_info=True)
                raise BinanceClientException(f"Unexpected error: {e}")

            finally:
                # 4. 에러 발생 시에도 가중치 정보가 있다면 항상 업데이트 (IP 차단 방지 핵심)
                if hasattr(self.client, 'response') and self.client.response is not None:
                    limiter.update_weight(self.client.response.headers)
        return None

    def _handle_retry_sleep(self, sleep_time):
        """지정된 시간 동안 0.1초마다 종료 신호를 체크하며 기다립니다."""
        start_time = time.time()
        while time.time() - start_time < sleep_time:
            # 메인에서 전달받은 stop_event가 켜졌는지 확인
            if self.stop_event and self.stop_event.is_set():
                return False  # 종료 신호 감지 시 False 반환
            time.sleep(0.1)
        return True  # 정상적으로 시간을 다 채웠을 때 True 반환

    ### Symbol ###
    def get_symbol_ticker(self, symbol: str) -> dict | None:
        '''
        Docstring for get_spot_symbol_info
        
        :param self: Description
        :param symbol: Description
        :type symbol: str
        :return: Description
        {'symbol': 'BNBUSDT', 'price': '916.25000000'}
        '''
        response = self._safe_api_call(self.client.get_symbol_ticker, symbol=symbol)
        if response.get('symbol') == symbol:
            price = Decimal(str(response.get('price')))
            return price

    def get_futures_default_stop_loss(self, symbol:str, interval:KlineInterval, side:PositionSide, endTime):
        _, msg = interval.value
        klines = self.client.futures_klines(symbol=symbol, interval=msg, endTime=endTime, limit=5)
        prices = []
        if len(klines) >= 3:
            # klines[-1]: 진입 시점이 포함된 캔들
            # klines[-2]: 1번째 전 캔들
            # klines[-3]: 2번째 전 캔들 (우리가 찾는 기준 봉)
            target_candles = [klines[-2], klines[-3], klines[-4], klines[-5]]

            # 캔들 데이터 인덱스: 0:OpenTime, 1:Open, 2:High, 3:Low, 4:Close
            if side == PositionSide.LONG:
                # 롱 전략: 2봉 전의 저가(Low)를 SL로 사용
                for i in target_candles:
                    low = Decimal(str(i[3]))
                    prices.append(low)
                
                real_low = min(prices)
                return real_low
            else:
                for i in target_candles:
                    high = Decimal(str(i[2]))
                    prices.append(high)
                
                real_high = max(prices)
                return real_high

    def futures_exchange_info(self, symbol: str) -> dict | None:
        response = self._safe_api_call(self.client.futures_exchange_info)
        if response:
            for symbol_info in response.get('symbols', []):
                if symbol_info.get('symbol') == symbol:
                    return symbol_info
        return None

    ### Balance & Position ###
    def spot_account_balance(self, symbol:str = None) -> Dict:
        account_balance = self._safe_api_call(self.client.get_account)
        spots = {}
        for key in account_balance:
            value = account_balance.get(key)
            if key in ['canTrade', 'canWithdraw', 'canDeposit', 'balances']:
                if key == 'balances':
                    for v in value:
                        asset = str(v.get('asset'))
                        free = Decimal(str(v.get('free')))
                        if symbol:
                            if symbol == asset:
                                return free
                        if free > 0:
                            spots.update({asset:free})
        return spots

    def futures_account_balance(self, asset_type:AssetType = AssetType.USDT) -> List | None:
        account_balance = self._safe_api_call(self.client.futures_account_balance)
        '''
        'asset': 자산의 종류를 나타냅니다. 여기서는 **테더(Tether)**라는 스테이블코인입니다.
        'balance': 총 잔액을 의미합니다. 이 선물 계좌에 보유하고 있는 USDT의 총량입니다. **'crossWalletBalance'**와 동일한 값으로, 교차 마진과 관련된 총 잔액을 나타냅니다.
        'crossWalletBalance': '교차 지갑 잔액을 뜻합니다. 교차 마진 모드에서 사용 가능한 총 자산 잔액입니다. 교차 마진은 계좌 내 모든 포지션이 동일한 지갑 잔액을 공유하는 방식입니다.
        'crossUnPnl': **미실현 손익(Unrealized PnL)**을 의미합니다. PnL은 Profit and Loss의 약자입니다.
        'availableBalance': 가용 잔액 또는 사용 가능한 잔액입니다. 현재 주문을 걸거나 포지션을 여는 데 즉시 사용할 수 있는 자산의 양입니다.
        'maxWithdrawAmount': 최대 출금 가능 금액입니다. 현재 선물 계좌에서 즉시 인출할 수 있는 USDT의 최대 양입니다.
        '''
        if account_balance == []:
            logger.warning(f"This might occur with new accounts or if the API key lacks balance permissions, which could lead to errors in subsequent trading operations.")
            return None
        try:
            self.usdt = Decimal('0')
            self.a_usdt = Decimal('0')
            self.bnb = Decimal('0')

            for asset in account_balance:
                match asset.get('asset'):
                    case asset_type.value:
                        balance = asset.get('crossWalletBalance')
                        availableBalance = asset.get('availableBalance')
                        self.usdt = Decimal(str(balance))
                        self.a_usdt = Decimal(str(availableBalance))

                    case AssetType.BNB.value:
                        bnb = asset.get('crossWalletBalance')
                        self.bnb = Decimal(str(bnb))

            return self.usdt, self.a_usdt, self.bnb 
        except Exception as e:
            logger.error(f"Failed to get asset information. {e}", exc_info=True)
            raise SetupError(f"Failed to fetch balance information: {e}") from e

    def futures_position_information(self, symbol: Optional[str] = None) -> list[dict]:
        '''
        Docstring for futures_position_information
        
        :param self: Description
        :param symbol: Description
        :type symbol: Optional[str] None: All,
        :return: Description
        :rtype: list[dict]
        '''
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._safe_api_call(self.client.futures_position_information, **params)
    
    def futures_trade_fees(self, symbol: Optional[str] = None):
        total_bnb = Decimal('0')
        fee_dict = {}
        
        # 7일치 데이터를 가져오기 위해 startTime 설정 (권장)
        start_time = int((time.time() - (7 * 24 * 60 * 60)) * 1000)
        result = self._safe_api_call(self.client.futures_account_trades, symbol=symbol, startTime=start_time)
        
        if not result:
            return []

        for i in result:
            ts = i.get('time')
            fee_type = i.get('commissionAsset')
            
            if fee_type == 'BNB':
                commission = Decimal(str(i.get('commission')))
                total_bnb += commission
                
                # dict.get()을 사용하면 if/else를 줄여 더 깔끔해집니다.
                fee_dict[ts] = fee_dict.get(ts, Decimal('0')) + commission

        # --- 시간순 정렬 및 리스트 변환 ---
        # 1. 키(ts)만 추출해서 정렬합니다.
        sorted_keys = sorted(fee_dict.keys())
        
        # 2. 정렬된 키 순서대로 [[ts, fee], [ts, fee]...] 리스트를 만듭니다.
        fee_list = [[key, fee_dict[key]] for key in sorted_keys]
        
        # 로그 확인용
        # for ts, fee in fee_list:
        #     logger.info(f"Timestamp: {ts} | Fee: {fee}")
            
        return fee_list

    ### ORDER ###
    def spot_create_order_buy(self, symbol:str, quantity:Decimal):

        """Send in a new order

        Any order with an icebergQty MUST have timeInForce set to GTC.

        https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints#new-order-trade

        :param symbol: required
        :type symbol: str
        :param side: required
        :type side: str
        :param type: required
        :type type: str
        :param quantity: required
        :type quantity: decimal
        :param quoteOrderQty: amount the user wants to spend (when buying) or receive (when selling)
            of the quote asset, applicable to MARKET orders
        :type quoteOrderQty: decimal
        :param price: required
        :type price: str
        :param newClientOrderId: A unique id for the order. Automatically generated if not sent.
        :type newClientOrderId: str
        :param icebergQty: Used with LIMIT, STOP_LOSS_LIMIT, and TAKE_PROFIT_LIMIT to create an iceberg order.
        :type icebergQty: decimal
        :param newOrderRespType: Set the response JSON. ACK, RESULT, or FULL; default: RESULT.
        :type newOrderRespType: str
        :param recvWindow: the number of milliseconds the request is valid for
        :type recvWindow: int
        """
        return self._safe_api_call(self.client.create_order, symbol=symbol, side='BUY', type='MARKET', quoteOrderQty=quantity)

    def futures_account_transfer(self, asset:AssetType, amount:Decimal, type:int) -> dict:
        '''
        Docstring for futures_account_transfer
        
        :param self: Description
        :param asset: Description
        :param amount: Description
        :param type: 1: Spot -> Futures, 2: Futures -> Spot

        return: {'tranId': 12345678910123}
        '''
        return self._safe_api_call(self.client.futures_account_transfer, asset=asset, amount=amount, type=type)

    def futures_create_order(self, symbol:str, side:Side, positionSide:PositionSide, quantity:Decimal, price:Decimal):
        try:
            # check = self.futures_check_orderbook_quantity(symbol, positionSide, price, quantity)
            # if check:
            #     return self._safe_api_call(self.client.futures_create_order, symbol=symbol,side=side.value, type='MARKET', timeInForce='GTC', price=price, quantity=quantity, positionSide=positionSide.value)

            return self._safe_api_call(self.client.futures_create_order, symbol=symbol,side=side.value, type='MARKET', quantity=quantity, positionSide=positionSide.value)


        except BinanceClientException as e:
            logger.warning(f"Failed Order book Amount {e}")

    def futures_account_trades(self, symbol):
        return self._safe_api_call(self.client.futures_account_trades, symbol=symbol)

    def futures_get_open_orders(self, **params):

        """Get all open orders on a symbol.

        https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Current-All-Open-Orders

        :param conditional: optional - Set to True to query algo/conditional orders
        :type conditional: bool

        """
        is_conditional = params.pop("conditional", True)

        if is_conditional:
            return self._safe_api_call(self.client._request_futures_api, "get", "openAlgoOrders", True, data=params)
        else:
            return self._safe_api_call(self.client._request_futures_api, "get", "openOrders", True, data=params)

    def futures_cancel_algo_order(self, symbol:str, algoId:str):
        """Cancel an active algo order.

        https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Cancel-Algo-Order

        :param symbol: required
        :type symbol: str
        :param algoId: optional - Either algoId or clientAlgoId must be sent
        :type algoId: int
        :param clientAlgoId: optional - Either algoId or clientAlgoId must be sent
        :type clientAlgoId: str
        :param recvWindow: optional - the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response
        {'algoId': 3000000192708847, 'clientAlgoId': 'YrT0KP9C0d00xTWYlQHk8x', 'code': '200', 'msg': 'success'}
        """
        params = {
            'symbol': symbol,
            'algoId': algoId
        }
        return self._safe_api_call(self.client._request_futures_api, "delete", "algoOrder", True, data=params)

    def futures_create_algo_order(self, symbol:str, side:Side, positionSide:PositionSide, type:AlgoOrderType, quantity:Decimal=None, price:Decimal=None, triggerPrice:Decimal=None, recvWindow:int=None):
        """Send in a new algo order (conditional order).

        https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order

        :param symbol: required
        :type symbol: str
        :param side: required - BUY or SELL
        :type side: str
        :param type: required - STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET
        :type type: str
        :param quantity: optional
        :type quantity: decimal
        :param price: optional
        :type price: decimal
        :param triggerPrice: optional - Used with STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET
        :type triggerPrice: decimal
        :param algoType: required - CONDITIONAL
        :type algoType: str
        :param recvWindow: optional - the number of milliseconds the request is valid for
        :type recvWindow: int

        :returns: API response
        "clientAlgoId" = self.CONTRACT_ORDER_PREFIX + self.uuid22()
        "algoType" = "CONDITIONAL"
        """
        try:
            params = {
                'symbol': symbol,
                'side': side.value,
                "positionSide": positionSide.value,
                'type': type.value,
                'quantity':quantity,
                'price': price,
                'triggerPrice': triggerPrice,
                'algoType': 'CONDITIONAL',
                'recvWindow': recvWindow,
            }
            return self._safe_api_call(self.client._request_futures_api, "post", "algoOrder", True, data=params)
        except Exception as e:
            logger.error(f"[X] Algo Order Failed: {str(e)}")
            raise

    def futures_order_book(self, symbol:str, limit:int = 100) -> Tuple[Dict, Dict]:
        # 5, 10, 20, 50, 100, 500, 1000
        result = self._safe_api_call(self.client.futures_order_book, symbol=symbol, limit=limit)
        bids = result.get('bids') # 매수호가
        asks = result.get('asks') # 매도호가
        return bids, asks

    def futures_check_orderbook_quantity(self, symbol, position_side: PositionSide, price:Decimal, amount:Decimal):
        bids, asks = self.futures_order_book(symbol)

        amount_cnt = Decimal('0')

        match position_side:

            case PositionSide.LONG:
                for i in range(len(bids)):
                    ob = bids[i]
                    p = Decimal(ob[0])
                    a = Decimal(ob[1])

                    if p <= price:
                        amount_cnt += a
                    
                    if amount <= amount_cnt:
                        return True

            case PositionSide.SHORT:
                for i in range(len(asks)):
                    ob = asks[i]
                    p = Decimal(ob[0])
                    a = Decimal(ob[1])

                    if p >= price:
                        amount_cnt += a

                    if amount <= amount_cnt:
                        return True

        return False

    ### function that runs only once ###
    def futures_change_leverage(self, symbol: str, leverage: int) -> dict | None:
        return self._safe_api_call(self.client.futures_change_leverage, symbol=symbol, leverage=leverage)

    def futures_get_position_mode(self):
        result = self._safe_api_call(self.client.futures_get_position_mode)
        return result

    def futures_change_position_mode(self, showLog:bool = False):
        cpm = self.futures_get_position_mode() # Current Position Mode
        if cpm.get('dualSidePosition'):
            return cpm
        else:
            result = self._safe_api_call(self.client.futures_change_position_mode, dualsideposition='true')
            if showLog:
                if result and 'dualSidePosition' in result:
                    logger.info("Successfully set futures account position mode to 'Hedge Mode'.")
                else:
                    logger.warning("Position mode change request sent, but response was empty or non-successful. It might already be in 'Hedge Mode'.")

            return result

    def futures_get_multi_assets_mode(self):
        return self._safe_api_call(self.client.futures_get_multi_assets_mode)

    def futures_change_multi_assets_mode(self):
        asset_mode = self.futures_get_multi_assets_mode()
        if asset_mode.get('multiAssetsMargin'):
            self._safe_api_call(self.client.futures_change_multi_assets_mode, multiAssetsMargin='false')
            return True

    def futures_change_margin_type(self, symbol:str, marginType:MarginType = MarginType.CROSSED, showLog:bool = False):

        '''
        Docstring for futures_change_margin_type
        
        :param self: Description
        :param symbol: Description
        :type symbol: str
        :param marginType: Description
        :type marginType: MarginType
        {'success': True, 'message': 'Already set'}
        '''
        result = self._safe_api_call(self.client.futures_change_margin_type, symbol=symbol, marginType=marginType.value)
        return result

