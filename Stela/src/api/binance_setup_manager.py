import os, sys, time
import numpy as np
from ..config import KLINE_LIMIT
from ..shared.typings import *
from ..shared.models import OHLC_DT
from ..shared.msg import get_logger
from ..shared.enums import MarginType
from ..shared.errors import BinanceClientException
from concurrent.futures import ThreadPoolExecutor


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
        self.ohlc = {}
        self.cache_dir = "cache_data"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _setup_initial_state(self):
        """Initializes the trading bot's state, including balance, positions, and trading logic components."""
        try:
            symbol_precision = self._fetch_symbol_info()
            self._fetch_massive_klines()
            self._setup_trading_environment()
            bnb_fee = self.client.futures_trade_fees(self.symbol)
            symbol_precision.update({'ohlc':self.ohlc, 'bnb_fee':bnb_fee})
            return symbol_precision

        except (BinanceClientException, SetupError) as e:
            logger.critical(f"CRITICAL ERROR: Initial setup failed due to an API issue: {e}")
            sys.exit(1)
        except Exception as e:
            logger.critical(f"CRITICAL ERROR: An unexpected error occurred during setup: {e}", exc_info=True)
            sys.exit(1)

    def _fetch_massive_klines(self):
        """KLINE_LIMIT에 도달할 때까지 현재 캔들을 포함한 과거 데이터를 반복 수집합니다."""
        """병렬 수집과 로컬 캐싱을 결합하여 속도를 극대화합니다."""
        try:
            valid_intervals = [x for x in self.kline_intervals if x is not None]
            max_interval = max(valid_intervals, key=lambda x: x.minutes)

            with ThreadPoolExecutor(max_workers=len(valid_intervals)) as executor:
                list(executor.map(lambda x: self._kline_worker(x, max_interval), valid_intervals))
            for interval_obj in valid_intervals:
                if interval_obj is None: continue

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

    def _kline_worker(self, interval_obj, max_interval):
        """타임프레임별 캐시 로드 및 부족분 업데이트 워커"""

        code = interval_obj.code
        minutes = interval_obj.minutes
        required_limit = interval_obj.get_required_count(KLINE_LIMIT, max_interval)
        cache_path = os.path.join(self.cache_dir, f"{self.symbol}_{code}.npy")
        local_data = None

        if os.path.exists(cache_path):
            try:
                mmap_data = np.load(cache_path, mmap_mode='r')
                local_data_list = mmap_data.tolist()
                del mmap_data 
                local_data = local_data_list

            except Exception as e:
                logger.warning(f"[{code}] 캐시 파일 손상 감지. 삭제 후 새로 수집합니다: {e}")
                try: os.remove(cache_path)
                except: pass
                local_data = None

        all_candles = []
        if local_data is not None and len(local_data) > 0:
            all_candles = [list(d) for d in local_data]
            start_time_ms = int(all_candles[-1][0]) + 1
        else:
            interval_ms = minutes * 60 * 1000
            start_time_ms = int(time.time() * 1000) - (required_limit * interval_ms)

        last_time = start_time_ms
        current_candle_start = int(time.time() * 1000) - (int(time.time() * 1000) % (minutes * 60 * 1000))

        while True:
            candles = self.client.client.futures_klines(
                symbol=self.symbol, interval=code,
                limit=1000, startTime=last_time
            )

            if not candles: break

            all_candles.extend(candles)
            last_fetched_ts = candles[-1][0]
            last_time = last_fetched_ts + 1
            if last_fetched_ts >= current_candle_start:
                break
            
            time.sleep(0.1)

        if all_candles and len(all_candles) > 1:

            all_candles.pop()
            final_candles = all_candles[-required_limit:]

            try:
                structured_data = np.empty(len(final_candles), dtype=OHLC_DT)
                if isinstance(final_candles[0], (list, tuple)):
                    for i, candle in enumerate(final_candles):
                        structured_data[i] = (
                            int(candle[0]),
                            float(candle[1]),
                            float(candle[2]),
                            float(candle[3]),
                            float(candle[4])
                        )
                else:
                    structured_data = np.array(final_candles, dtype=OHLC_DT)

                np.save(cache_path, structured_data)
                self.ohlc[code] = structured_data

                # logger.info(f"[{code}] Data synchronized and converted: {len(structured_data)} bars")

            except Exception as e:
                logger.error(f"[{code}] 데이터 변환 오류: {e}")
        else:
            logger.warning(f"[{code}] 수집된 데이터가 부족합니다.")