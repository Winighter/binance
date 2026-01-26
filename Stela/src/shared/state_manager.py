from dataclasses import dataclass
from .typings import *

@dataclass
class BalanceState:
    balance: Optional[Decimal] = None
    available_balance: Optional[Decimal] = None
    bnb_balance : Optional[Decimal] = None

    def reset(self):
        """모든 포지션 상태를 None(또는 0)으로 초기화"""
        for field in self.__dataclass_fields__:
            setattr(self, field, None)

@dataclass
class PositionState:
    long_fee: Optional[Decimal] = None
    long_amount: Optional[Decimal] = None
    long_entry_price: Optional[Decimal] = None
    long_stop_loss: Optional[Decimal] = None
    long_default_stop_loss: Optional[Decimal] = None
    long_take_profit: Optional[Decimal] = None
    long_stop_loss_order_id: Optional[str] = None
    long_take_profit_order_id: Optional[str] = None

    short_take_profit_order_id: Optional[str] = None
    short_stop_loss_order_id: Optional[str] = None
    short_take_profit: Optional[Decimal] = None
    short_default_stop_loss: Optional[Decimal] = None
    short_stop_loss: Optional[Decimal] = None
    short_entry_price: Optional[Decimal] = None
    short_amount: Optional[Decimal] = None
    short_fee: Optional[Decimal] = None

    def reset(self):
        """모든 포지션 상태를 None(또는 0)으로 초기화"""
        for field in self.__dataclass_fields__:
            setattr(self, field, None)