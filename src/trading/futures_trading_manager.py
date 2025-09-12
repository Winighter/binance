from ..shared.msg import get_logger
from ..core.client_manager import BinanceClient
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from binance.exceptions import BinanceAPIException
from ..shared.enums import OrderSide, PositionSide
from settings import LEVERAGE


logger = get_logger("FUTURES_TRADING_MANAGER")

class FuturesTradingManager:

    ALLOWED_ORDER_SIDES = {'BUY', 'SELL'}
    ALLOWED_POSITION_SIDES = {'LONG', 'SHORT', 'BOTH'}
    
    def __init__(self, binance_client: BinanceClient, default_position_rate: int):
        self.binance_client = binance_client
        self._symbol_info_cache: Dict[str, Dict[str, Any]] = {}
        self._leverage_cache: Dict[str, Decimal] = {}
        self._default_position_rate = (Decimal(str(default_position_rate)) / Decimal('100'))
        self._leverage_cache_time: Dict[str, datetime] = {}
        self._leverage_cache_timeout = timedelta(hours=1)
        logger.info("FuturesTradingManager instance created.")

    def change_symbol_leverage(self, symbol: str, leverage: int) -> dict | None:
        return self.binance_client.futures_change_leverage(symbol=symbol, leverage=leverage)

    def get_leverage(self, symbol: str) -> Decimal:
        now = datetime.now()
        if symbol in self._leverage_cache and (now - self._leverage_cache_time.get(symbol, now)).total_seconds() < self._leverage_cache_timeout.total_seconds():
            return self._leverage_cache[symbol]
        try:
            positions = self.binance_client.futures_position_information()
            leverage = Decimal('1')
            for pos in positions:
                if pos['symbol'] == symbol:
                    leverage = Decimal(pos['leverage'])
                    break
            self._leverage_cache[symbol] = leverage
            self._leverage_cache_time[symbol] = now
            return leverage
        except BinanceAPIException as e:
            logger.warning(f"Failed to fetch position information from Binance. Using default leverage of 1: {e}")
            return Decimal('1')

    def get_market_precision(self, symbol: str) -> dict:
        if symbol not in self._symbol_info_cache:
            try:
                info = self.binance_client.futures_exchange_info()
                for item in info['symbols']:
                    if item['symbol'] == symbol:
                        self._symbol_info_cache[symbol] = {
                            'quantity_precision': item['quantityPrecision'],
                            'price_precision': item['pricePrecision']
                        }
                        break
                if symbol not in self._symbol_info_cache:
                    logger.error(f"Error fetching symbol information: Could not find information for symbol {symbol}.")
                    raise ValueError(f"Symbol {symbol} not found in exchange info.")
            except BinanceAPIException as e:
                logger.error(f"Failed to fetch symbol info: {e}", exc_info=True)
                raise
        
        return self._symbol_info_cache.get(symbol, {'quantity_precision': 2, 'price_precision': 2})

    def calculate_quantity(self, balance_usdt: Decimal, price: Decimal, symbol: str) -> Decimal:
        leverage = LEVERAGE
        position_capital_usdt = balance_usdt * self._default_position_rate
        position_size_usdt = position_capital_usdt * leverage
        quantity_precision = self.get_market_precision(symbol)['quantity_precision']
        quantity = position_size_usdt / price

        return round(quantity, quantity_precision)

    def cancel_order(self, symbol: str, order_id: int) -> Optional[dict] | None:
        try:
            result = self.binance_client.cancel_order(
                symbol=symbol,
                orderId=order_id
            )
            logger.info(f"Order ID {order_id} canceled successfully.")
            return result
        except BinanceAPIException as e:
            if e.code == -2011:
                logger.warning(f"Order ID {order_id} is already canceled or filled.")
                return None
            else:
                logger.error(f"Error canceling order: {e}", exc_info=True)
                raise e

    @staticmethod
    def _get_enum_value(enum_obj, enum_type):
        """Enumeration 값 또는 문자열을 반환하는 헬퍼 함수"""
        return enum_obj.value if isinstance(enum_obj, enum_type) else enum_obj

    def create_market_order(self, symbol: str, side: str, positionSide: str, quantity: Decimal) -> Optional[dict]:

        side = self._get_enum_value(side, OrderSide) # ✅ 헬퍼 함수 사용
        positionSide = self._get_enum_value(positionSide, PositionSide) # ✅ 헬퍼 함수 사용

        if side not in self.ALLOWED_ORDER_SIDES:
            raise ValueError(f"Invalid side: {side}. Must be one of {self.ALLOWED_ORDER_SIDES}")
        
        if positionSide not in self.ALLOWED_POSITION_SIDES:
            raise ValueError(f"Invalid positionSide: {positionSide}. Must be one of {self.ALLOWED_POSITION_SIDES}")

        try:
            logger.info(f"Submitting MARKET order. Symbol: {symbol}, Side: {side}, Quantity: {quantity}")
            order = self.binance_client.create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity,
                positionSide=positionSide
            )
            logger.info(f"MARKET order submitted. Order ID: {order['orderId']}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Error creating market order: {e}", exc_info=True)
            raise

    def _create_market_order_with_stop_price(self, symbol: str, side: str, order_type: str, quantity: Decimal, stop_price: Decimal, positionSide: str) -> Optional[dict]:
        try:
            side = self._get_enum_value(side, OrderSide)
            positionSide = self._get_enum_value(positionSide, PositionSide)

            precision = self.get_market_precision(symbol)['price_precision']
            adjusted_stop_price = round(stop_price, precision)

            order = self.binance_client.create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                stopPrice=adjusted_stop_price,
                timeInForce='GTC',
                positionSide=positionSide
            )
            logger.info(f"{order_type} order submitted successfully. Symbol: {symbol}, Side: {side}, Quantity: {quantity}, Price: {adjusted_stop_price}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Failed to create {order_type} order: {e}", exc_info=True)
            raise

    def create_stop_market_order(self, symbol: str, side: str, quantity: Decimal, stop_price: Decimal, positionSide: str) -> Optional[dict]:
        return self._create_market_order_with_stop_price(symbol, side, 'STOP_MARKET', quantity, stop_price, positionSide)