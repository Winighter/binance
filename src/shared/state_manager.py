from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class PositionState:
    long: Optional[Decimal] = None
    long_amount: Optional[Decimal] = None
    long_stop_loss: Optional[Decimal] = None
    long_entry_price: Optional[Decimal] = None
    long_take_profit: Optional[Decimal] = None
    long_stop_loss_order_id: Optional[int] = None
    long_take_profit_order_id: Optional[int] = None

    short_take_profit_order_id: Optional[int] = None
    short_stop_loss_order_id: Optional[int] = None
    short_take_profit: Optional[Decimal] = None
    short_entry_price: Optional[Decimal] = None
    short_stop_loss: Optional[Decimal] = None
    short_amount: Optional[Decimal] = None
    short: Optional[Decimal] = None