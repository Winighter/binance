import sys
from decimal import Decimal
from typing import List, Any
from ..config import *
from ..shared.msg import get_logger
from ..shared.enums import FilterType, AssetType
from ..shared.state_manager import PositionState
from ..shared.errors import BinanceClientException

logger = get_logger("SETUP_MANAGER")

class SetupError(Exception):
    """Initial setup failed."""
    pass

class BinanceSetupManager:

    def __init__(
            self, symbol: str, binance_client: Any, trading_manager: Any,
            leverage: int, kline_interval: str, hedge_mode: bool = True
        ):
        self.symbol = symbol
        self.kline_interval = kline_interval
        self.leverage = leverage
        self.hedge_mode = hedge_mode
        self.price_precision: int = 0
        self.quantity_precision: int = 0
        self.open_prices: List[Decimal] = []
        self.high_prices: List[Decimal] = []
        self.low_prices: List[Decimal] = []
        self.close_prices: List[Decimal] = []
        self.volumes: List[Decimal] = []
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = PositionState()

    @staticmethod
    def _calculate_precision(size_str: str) -> int:
        """Calculates precision from a given stepSize or tickSize string."""
        return len(size_str.split('.')[1]) if '.' in size_str else 0

    def _setup_initial_state(self) -> tuple[list[List[Decimal]], int, int]:
        """Initializes the trading bot's state, including balance, positions, and trading logic components."""
        logger.info("ROBOT STATUS: Setting up initial trading state...")
        try:
            self._fetch_symbol_info()
            self._fetch_initial_klines()
            self._fetch_positions()
            self._setup_trading_environment()
            ohlc_prices = []
            for o, h, l, c in zip(self.open_prices, self.high_prices, self.low_prices, self.close_prices):
                ohlc_prices.append([o, h, l, c])
            return ohlc_prices, self.leverage

        except (BinanceClientException, SetupError) as e:
            logger.critical(f"CRITICAL ERROR: Initial setup failed due to an API issue: {e}")
            sys.exit(1)
        except Exception as e:
            logger.critical(f"CRITICAL ERROR: An unexpected error occurred during setup: {e}", exc_info=True)
            sys.exit(1)

    def _fetch_balance(self, asset_type:AssetType = AssetType.USDT) -> List | None:
        account_balance = self.binance_client.get_futures_balance()
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
            for asset in account_balance:
                if asset_type.value == asset.get('asset'):
                    balance = asset.get('balance')
                    availableBalance = asset.get('availableBalance')
                    return Decimal(str(balance)), Decimal(str(availableBalance))
        except Exception as e:
            logger.error(f"Failed to get asset information. {e}" ,exc_info=True)
            raise SetupError(f"Failed to fetch balance information: {e}") from e

    def _fetch_symbol_info(self):
        self.symbols_info = self.binance_client.get_symbol_info(symbol=self.symbol)
        if not self.symbols_info:
            logger.critical("FATAL ERROR: Failed to retrieve symbol information. Terminating the program.")
            raise SetupError("Failed to retrieve symbol information from API.")

        logger.info("INFO: %s symbol information inquiry successful." % self.symbol)

        filters_dict = {f['filterType']: f for f in self.symbols_info['filters']}
        self.price_precision = self._calculate_precision(filters_dict.get(FilterType.PRICE_FILTER.value, {}).get('tickSize', '1'))
        self.quantity_precision = self._calculate_precision(filters_dict.get(FilterType.LOT_SIZE.value, {}).get('stepSize', '1'))

    def _fetch_positions(self):
        positions = self.binance_client.futures_position_information(symbol=self.symbol)
        if not positions:
            return logger.info("POSITION: Position Not Found.")

        position_info = positions[0]
        position_amount = Decimal(position_info.get('positionAmt'))
        if position_amount > 0:
            self.positions.long = Decimal(position_info.get('entryPrice'))
            self.positions.long_amount = position_amount
            logger.info(f"POSITION: Currently holding a long position. Entry Price: {self.positions.long}, Quantity: {self.positions.long_amount}")

    def _fetch_initial_klines(self):
        """
        Loads a sufficient number of historical kline data from Binance API
        before starting the real-time WebSocket feed.
        """
        logger.info("API: Fetching initial historical kline data...")
        candles = self.binance_client.get_klines(
            symbol=self.symbol,
            interval=self.kline_interval,
            limit=KLINE_LIMIT
            )
        if not candles:
            logger.error("SYSTEM ERROR: Failed to retrieve initial candle chart data from API.")
            raise SetupError("Failed to retrieve initial candle chart data.")

        candles.pop()

        self.open_prices = [Decimal(str(c[1])) for c in candles]
        self.high_prices = [Decimal(str(c[2])) for c in candles]
        self.low_prices = [Decimal(str(c[3])) for c in candles]
        self.close_prices = [Decimal(str(c[4])) for c in candles]

        logger.info(f"API: Successfully fetched {len(candles) + 1} historical data points.")

    def _setup_trading_environment(self):
        """Setting up leverage and position mode."""
        leverage_to_set = self.leverage
        try:
            logger.info(f"Attempting to change leverage to {leverage_to_set}x...")
            self.trading_manager.change_symbol_leverage(symbol=self.symbol, leverage=leverage_to_set)
            logger.info("Request to change leverage was sent successfully.")

            if self.hedge_mode:
                logger.info("Attempting to set futures account position mode to 'Hedge Mode'...")
                result = self.trading_manager.binance_client.futures_change_position_mode(dualSidePosition=True)

                if result and 'dualSidePosition' in result:
                    logger.info("Successfully set futures account position mode to 'Hedge Mode'.")
                else:
                    logger.warning("Position mode change request sent, but response was empty or non-successful. It might already be in 'Hedge Mode'.")

        except BinanceClientException as e:
            logger.critical(f"FATAL SETUP ERROR: Failed to set up the trading environment. Error: {e}")
            raise SetupError(f"Failed to set up trading environment: {e}") from e