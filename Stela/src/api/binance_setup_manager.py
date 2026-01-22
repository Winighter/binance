import sys
import time
from ..config import *
from ..shared.typings import *
from ..shared.msg import get_logger
from ..shared.enums import MarginType
from ..shared.errors import BinanceClientException
from ..shared.enums import MarginType, OrderType, AssetType, Side, AlgoOrderType, PositionSide


logger = get_logger("SETUP_MANAGER")

class SetupError(Exception):
    """Initial setup failed."""
    pass

class BinanceSetupManager:

    def __init__(self, binance_client, symbol: str, leverage: int, kline_interval):
        self.client = binance_client
        self.symbol = symbol
        self.leverage = leverage
        self.kline_interval = kline_interval
        self.open_prices: List[Decimal] = []
        self.high_prices: List[Decimal] = []
        self.low_prices: List[Decimal] = []
        self.close_prices: List[Decimal] = []


    def _setup_initial_state(self) -> tuple[list[List[Decimal]], int, int]:
        """Initializes the trading bot's state, including balance, positions, and trading logic components."""
        try:
            symbol_precision = self._fetch_symbol_info()
            self._fetch_massive_klines()
            self._setup_trading_environment()
            ohlc_prices = []
            for o, h, l, c in zip(self.open_prices, self.high_prices, self.low_prices, self.close_prices):
                ohlc_prices.append([o, h, l, c])
            
            bnb_fee_data = self.client.futures_trade_fees(self.symbol)

            symbol_precision.update({'ohlc_prices':ohlc_prices, 'bnb_fee_data':bnb_fee_data})

            return symbol_precision

        except (BinanceClientException, SetupError) as e:
            logger.critical(f"CRITICAL ERROR: Initial setup failed due to an API issue: {e}")
            sys.exit(1)
        except Exception as e:
            logger.critical(f"CRITICAL ERROR: An unexpected error occurred during setup: {e}", exc_info=True)
            sys.exit(1)

    # 기존 _fetch_initial_klines를 다음과 같이 변경하거나 추가하세요.
    def _fetch_massive_klines(self):
        """KLINE_LIMIT에 도달할 때까지 현재 캔들을 포함한 과거 데이터를 반복 수집합니다."""
        try:
            from ..config import KLINE_LIMIT  # 설정된 개수 가져오기

            all_candles = []
            # 15분봉(15m) 기준, 목표 개수만큼 과거로 거슬러 올라간 시작 시간 계산 (ms 단위)
            # 15 * 60 * 1000 = 15분을 밀리초로 환산
            interval_ms = self.kline_interval.minutes * 60 * 1000
            start_time_ms = int(time.time() * 1000) - (KLINE_LIMIT * interval_ms)

            last_time = start_time_ms
            while len(all_candles) < KLINE_LIMIT:
                # 남은 개수 계산 (한 번에 최대 1000개씩 요청 권장)
                remaining = KLINE_LIMIT - len(all_candles)
                fetch_limit = min(remaining, 1000)

                # 바이낸스 공식 API 호출
                candles = self.client.client.futures_klines(
                    symbol=self.symbol,
                    interval=self.kline_interval.code,
                    limit=fetch_limit,
                    startTime=last_time
                )

                if not candles:
                    break

                all_candles.extend(candles)
                
                # 마지막 캔들의 시간을 다음 요청의 시작 시간으로 설정 (+1ms로 중복 방지)
                last_time = candles[-1][0] + 1
                
                # API 과부하 방지를 위한 미세 대기
                time.sleep(0.1)

            # 수집된 데이터 중 최신 데이터부터 KLINE_LIMIT만큼 슬라이싱
            final_candles = all_candles[-KLINE_LIMIT:]

            final_candles.pop()

            # 기존 리스트에 데이터 할당
            self.open_prices = [Decimal(str(c[1])) for c in final_candles]
            self.high_prices = [Decimal(str(c[2])) for c in final_candles]
            self.low_prices = [Decimal(str(c[3])) for c in final_candles]
            self.close_prices = [Decimal(str(c[4])) for c in final_candles]

            logger.info(f"Successfully fetched total {len(final_candles)+1} candles (Current included).")

        except Exception as e:
            logger.error(f"Failed to fetch initial klines: {e}")
            raise SetupError(f"Initial kline fetch failed: {e}")

    def _fetch_symbol_info(self):
        symbols_info = self.client.futures_exchange_info(symbol=self.symbol)
        if not symbols_info:
            logger.critical("FATAL ERROR: Failed to retrieve symbol information. Terminating the program.")
            raise SetupError("Failed to retrieve symbol information from API.")
        symbol_precision = {}
        for f in symbols_info.get('filters'):
            
            match f.get('filterType'):
                
                case 'PRICE_FILTER':
                    symbol_precision.update({'tickSize':f.get('tickSize')})

                case 'LOT_SIZE':
                    symbol_precision.update({'minQty':f.get('minQty')})
                    symbol_precision.update({'stepSize':f.get('stepSize')})

                case 'MIN_NOTIONAL':
                    symbol_precision.update({'notional':f.get('notional')})

        return symbol_precision

    def _setup_trading_environment(self, showLog:bool = False):
        """Setting up leverage and position mode."""
        leverage_to_set = self.leverage
        try:
            if showLog:
                logger.info(f"Attempting to change leverage to {leverage_to_set}x...")
            self.client.futures_change_leverage(symbol=self.symbol, leverage=leverage_to_set)
            self.client.futures_change_margin_type(self.symbol, MarginType.CROSSED)
            self.client.futures_change_position_mode()

        except BinanceClientException as e:
            logger.critical(f"FATAL SETUP ERROR: Failed to set up the trading environment. Error: {e}")
            raise SetupError(f"Failed to set up trading environment: {e}") from e