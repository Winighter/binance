import sys
from decimal import Decimal
from typing import List, Any
from ..config import *
from ..shared.msg import get_logger
from ..shared.enums import FilterType
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
        self.volume_prices: List[Decimal] = []
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = PositionState()

    @staticmethod
    def _calculate_precision(size_str: str) -> int:
        """Calculates precision from a given stepSize or tickSize string."""
        return len(size_str.split('.')[1]) if '.' in size_str else 0

    def _setup_initial_state(self) -> tuple[List[Decimal], List[Decimal], List[Decimal], List[Decimal], Decimal]:
        """Initializes the trading bot's state, including balance, positions, and trading logic components."""
        logger.info("ROBOT STATUS: Setting up initial trading state...")
        try:
            available_usdt = self._fetch_balance()
            self._fetch_symbol_info()
            self._fetch_initial_klines()
            self._fetch_positions()
            self._setup_trading_environment()
            return self.open_prices, self.high_prices, self.low_prices, self.close_prices, self.volume_prices, available_usdt, self.leverage

        except (BinanceClientException, SetupError) as e:
            logger.critical(f"CRITICAL ERROR: Initial setup failed due to an API issue: {e}")
            sys.exit(1)
        except Exception as e:
            logger.critical(f"CRITICAL ERROR: An unexpected error occurred during setup: {e}", exc_info=True)
            sys.exit(1)

    def _fetch_balance(self) -> Decimal:
        account_balance = self.binance_client.get_futures_balance()
        for balance in account_balance:
            if balance.get('asset') == 'USDT':
                self.balance_usdt = Decimal(balance.get('balance'))
                available_usdt = Decimal(balance.get('availableBalance'))
                logger.info(f"ACCOUNT: USDT Total: {self.balance_usdt:.2f}, Free: {available_usdt:.2f}")
                return available_usdt
        raise ValueError("USDT balance not found.")

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
        if positions:
            position_info = positions[0]
            position_amount = Decimal(position_info.get('positionAmt'))
            if position_amount > 0:
                self.positions.long = Decimal(position_info.get('entryPrice'))
                self.positions.long_amount = position_amount
                logger.info(f"POSITION: Currently holding a long position. Entry Price: {self.positions.long}, Quantity: {self.positions.long_amount}")
        else:
            logger.info("POSITION: No open positions found.")

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

        self.open_prices = [Decimal(str(c[1])) for c in candles]
        self.high_prices = [Decimal(str(c[2])) for c in candles]
        self.low_prices = [Decimal(str(c[3])) for c in candles]
        self.close_prices = [Decimal(str(c[4])) for c in candles]
        self.volume_prices = [Decimal(str(c[5])) for c in candles]

        self.open_prices.pop()
        self.high_prices.pop()
        self.low_prices.pop()
        self.close_prices.pop()
        self.volume_prices.pop()

        logger.info(f"API: Successfully fetched {len(self.close_prices)} historical data points.")

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