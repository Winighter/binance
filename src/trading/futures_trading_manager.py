from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from binance.exceptions import BinanceAPIException
from ..shared.msg import get_logger
from ..core.client_manager import BinanceClient
from ..shared.enums import OrderSide, PositionSide
from decimal import Decimal, getcontext

# 금융 계산의 정확도를 위해 정밀도 설정
getcontext().prec = 20

logger = get_logger("FUTURES_TRADING_MANAGER")

class FuturesTradingManager:

    def __init__(self, binance_client: BinanceClient):
        self.binance_client = binance_client
        self._symbol_info_cache: Dict[str, Dict[str, Any]] = {}
        self._leverage_cache: Dict[str, Decimal] = {}
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

    def calculate_quantity_with_risk_management(
        self, 
        balance_usdt: Decimal,
        price: Decimal, 
        stop_loss_price: Decimal,
        risk_percentage: Decimal,
        symbol: str
    ) -> Decimal:
        """
        쿠라마기 자금 관리 원칙에 따라 매수 가능한 코인 수량을 계산합니다.
        (레버리지 변수 추가 버전)

        Args:
            balance_usdt (Decimal): 현재 계좌 잔고.
            price (Decimal): 진입 가격 (현재 시장 가격).
            stop_loss_price (Decimal): 손절매 가격.
            risk_percentage (Decimal): 계좌 잔고 대비 감수할 위험 비율 (예: 0.01 = 1%).
            leverage (Decimal): 레버리지 배수 (기본값: 1).
            symbol (str): 거래 심볼 (수량 정밀도 계산을 위해 필요).

        Returns:
            Decimal: 리스크 관리 원칙에 따라 계산된 매수 수량.
        """
        price = Decimal(str(price))
        balance_usdt = Decimal(str(balance_usdt))
        stop_loss_price = Decimal(str(stop_loss_price))
        risk_percentage = Decimal(str(risk_percentage))

        # 1. 최대 손실 금액 계산 (총 자산 기준)
        max_loss_amount = balance_usdt * (risk_percentage / 100)

        # 2. 단위당 예상 손실 금액 계산
        if stop_loss_price >= price:
            return Decimal('0')

        loss_per_unit = price - stop_loss_price

        # 3. 총 포지션 가치 계산
        quantity = (max_loss_amount / loss_per_unit)

        if symbol and quantity > 0:
            quantity_precision = self.get_market_precision(symbol)['quantity_precision']
            return round(quantity, quantity_precision)

        return quantity

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

    def create_market_order(self, symbol: str, side: OrderSide, positionSide: PositionSide, quantity: Decimal) -> Optional[dict]:

        if side not in [OrderSide.BUY, OrderSide.SELL]:
            raise ValueError(f"Invalid side: {side}. Must be one of {['BUY', 'SELL']}")
        
        if positionSide not in [PositionSide.BOTH, PositionSide.LONG, PositionSide.SHORT]:
            raise ValueError(f"Invalid positionSide: {positionSide}. Must be one of {['BOTH', 'LONG', 'SHORT']}")

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

    def _create_market_order_with_stop_price(self, symbol: str, side: PositionSide, order_type: str, quantity: Decimal, stop_price: Decimal, positionSide: PositionSide) -> Optional[dict]:
        try:
            precision = self.get_market_precision(symbol)['price_precision']
            adjusted_stop_price = round(stop_price, precision)

            order = self.binance_client.create_order(
                symbol=symbol,
                side=side.value,
                type=order_type,
                quantity=quantity,
                stopPrice=adjusted_stop_price,
                timeInForce='GTC',
                positionSide=positionSide.value
            )
            logger.info(f"{order_type} order submitted successfully. Symbol: {symbol}, Side: {side}, Quantity: {quantity}, Price: {adjusted_stop_price}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Failed to create {order_type} order: {e}", exc_info=True)
            raise

    def create_stop_market_order(self, symbol: str, side: str, quantity: Decimal, stop_price: Decimal, positionSide: str) -> Optional[dict]:
        return self._create_market_order_with_stop_price(symbol, side, 'STOP_MARKET', quantity, stop_price, positionSide)