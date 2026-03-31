import time, sys
from ..shared.typings import *
import numpy as np
from ..shared.models import OHLC_DT
from ..shared.msg import get_logger
from ..shared.errors import BinanceClientException
from ..shared.enums import MarginType, OrderType, AssetType, Side, AlgoOrderType, PositionSide
from settings import *
from ..config import KLINE_LIMIT  # 설정된 개수 가져오기
import os  # 캐시 디렉토리 및 파일 확인용
from concurrent.futures import ThreadPoolExecutor  # [1번] 병렬 처리를 위한 스레드 풀



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
        # [5번] 캐시 저장 경로 설정 및 생성
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

    # 기존 _fetch_initial_klines를 다음과 같이 변경하거나 추가하세요.
    def _fetch_massive_klines(self):
        """KLINE_LIMIT에 도달할 때까지 현재 캔들을 포함한 과거 데이터를 반복 수집합니다."""
        """병렬 수집과 로컬 캐싱을 결합하여 속도를 극대화합니다."""
        try:
            valid_intervals = [x for x in self.kline_intervals if x is not None]
            max_interval = max(valid_intervals, key=lambda x: x.minutes)

            with ThreadPoolExecutor(max_workers=len(valid_intervals)) as executor:
                list(executor.map(lambda x: self._kline_worker(x, max_interval), valid_intervals))

            # logger.info(f"모든 타임프레임 데이터 수집 완료: {list(self.ohlc.keys())}")

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

        # A. [5번] 로컬 캐시 로드 시도 (mmap_mode로 메모리 절약)
        if os.path.exists(cache_path):
            try:
                # 1. mmap으로 가볍게 읽기
                mmap_data = np.load(cache_path, mmap_mode='r')
                # 2. 리스트로 복사하여 메모리에 할당 (이후 mmap 연결 필요 없음)
                local_data_list = mmap_data.tolist()
                # 3. 명시적으로 mmap 연결 종료 (중요)
                del mmap_data 
                
                # B 섹션에서 사용할 수 있도록 local_data 설정
                local_data = local_data_list
            except Exception as e:
                logger.warning(f"[{code}] 캐시 파일 손상 감지. 삭제 후 새로 수집합니다: {e}")
                # 손상된 파일 삭제하여 다음 실행 시 문제 없게 함
                try: os.remove(cache_path)
                except: pass
                local_data = None

        # B. 증분 업데이트 계산 (캐시가 있으면 마지막 시간부터 수집)
        all_candles = []
        if local_data is not None and len(local_data) > 0:
            # 캐시가 있다면 튜플을 리스트로 변환하여 시작
            all_candles = [list(d) for d in local_data]
            start_time_ms = int(all_candles[-1][0]) + 1
        else:
            # 캐시가 없다면 현재 시간 기준으로 과거 데이터 범위 계산
            interval_ms = minutes * 60 * 1000
            start_time_ms = int(time.time() * 1000) - (required_limit * interval_ms)

        # C. 부족한 데이터만 바이낸스 API로 수집 (기존 루프와 동일)
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

            # 최신 봉 시작 시간까지 도달했다면 빈틈이 모두 메워진 것임
            if last_fetched_ts >= current_candle_start:
                break
            
            time.sleep(0.1)

        # D. [4번+2번] 기존 NumPy 최적화 로직 적용
        if all_candles and len(all_candles) > 1:
            # [추가] 마지막 미확정 봉 제거 (실시간 데이터와의 중복 방지)
            all_candles.pop()
            final_candles = all_candles[-required_limit:]

            try:
                structured_data = np.empty(len(final_candles), dtype=OHLC_DT)

                # 2. 데이터가 리스트인지, 이미 구조화된 배열인지 체크하여 처리
                # 만약 리스트 형태(API에서 새로 가져온 경우 등)라면
                if isinstance(final_candles[0], (list, tuple)):
                    for i, candle in enumerate(final_candles):
                        structured_data[i] = (
                            int(candle[0]),    # timestamp
                            float(candle[1]),  # open
                            float(candle[2]),  # high
                            float(candle[3]),  # low
                            float(candle[4])   # close
                        )
                else:
                    # 이미 구조화된 배열인 경우 (캐시에서 불러온 데이터가 대부분일 때)
                    structured_data = np.array(final_candles, dtype=OHLC_DT)

                np.save(cache_path, structured_data)
                self.ohlc[code] = structured_data

                # logger.info(f"[{code}] Data synchronized and converted: {len(structured_data)} bars")

            except Exception as e:
                logger.error(f"[{code}] 데이터 변환 오류: {e}")
        else:
            logger.warning(f"[{code}] 수집된 데이터가 부족합니다.")