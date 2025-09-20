from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class PositionState:
    long: Optional[Decimal] = None
    long_amount: Optional[Decimal] = None
    long_entry_price: Optional[Decimal] = None
    long_stop_loss: Optional[Decimal] = None
    long_stop_loss_order_id: Optional[int] = None