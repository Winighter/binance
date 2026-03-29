import time, sys
from ..shared.typings import *
import numpy as np
from ..shared.models import OHLCV_DT
from ..shared.msg import get_logger
from ..shared.errors import BinanceClientException
from ..shared.enums import MarginType, OrderType, AssetType, Side, AlgoOrderType, PositionSide
from settings import *
from ..config import KLINE_LIMIT  # 설정된 개수 가져오기
from ..shared.utils import get_session_label


logger = get_logger("SETUP_MANAGER")

class SetupError(Exception):
    """Initial setup failed."""
    pass

class BinanceSetupManager:

    def __init__(self, binance_client, symbol: str, leverage: int, kline_intervals:List):
        self.client = binance_client
        self.symbol = symbol
        self.leverage = leverage
        self.kline_intervals = kline_intervals

    def _setup_initial_state(self):
        """Initializes the trading bot's state, including balance, positions, and trading logic components."""
        try:
            symbol_precision = self._fetch_symbol_info()
            self._fetch_massive_klines()
            self._setup_trading_environment()
            bnb_fee = self.client.futures_trade_fees(self.symbol)
            symbol_precision.update({'ohlcv':self.ohlcv, 'bnb_fee':bnb_fee})

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
            self.ohlcv = {}
            valid_intervals = [x for x in self.kline_intervals if x is not None]
            max_interval = max(valid_intervals, key=lambda x: x.minutes)

            for interval_obj in valid_intervals:
                if interval_obj is None: continue

                code = interval_obj.code
                minutes = interval_obj.minutes
                required_limit = interval_obj.get_required_count(KLINE_LIMIT, max_interval)

                all_candles = []
                interval_ms = minutes * 60 * 1000
                start_time_ms = int(time.time() * 1000) - (required_limit * interval_ms)

                last_time = start_time_ms
                while len(all_candles) < required_limit:
                    # 남은 개수 계산 (한 번에 최대 1000개씩 요청 권장)
                    remaining = required_limit - len(all_candles)
                    fetch_limit = min(remaining, 1000)

                    '''
                    self.client.client.futures_klines

                    return
                    [
                        [
                        1499040000000,      // Open time
                        "0.01634790",       // Open
                        "0.80000000",       // High
                        "0.01575800",       // Low
                        "0.01577100",       // Close
                        "148976.11427815",  // Volume
                        1499644799999,      // Close time
                        "2434.19055334",    // Quote asset volume
                        308,                // Number of trades
                        "1756.87402397",    // Taker buy base asset volume
                        "28.46694368",      // Taker buy quote asset volume
                        "17928899.62484339" // Ignore.
                        ]
                    ]
                    '''
                    # 바이낸스 공식 API 호출
                    candles = self.client.client.futures_klines(
                    symbol=self.symbol,
                    interval=code,
                    limit=fetch_limit,
                    startTime=last_time
                    )

                    if not candles:break
                    all_candles.extend(candles)
                    last_time = candles[-1][0] + 1
                    time.sleep(0.1)

                final_candles = all_candles[-required_limit:]
                if final_candles:
                    final_candles.pop()

                structured_data = np.array(
                    [
                        (
                            int(c[0]), 
                            float(c[1]),
                            float(c[2]),
                            float(c[3]),
                            float(c[4]),
                            float(c[5]),
                            get_session_label(int(c[0]))
                        )
                        for c in final_candles
                    ],
                     dtype=OHLCV_DT
                )
                self.ohlcv[code] = structured_data

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