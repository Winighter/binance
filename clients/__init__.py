"""
This package provides a client for interacting with the Binance API
and a manager for handling WebSocket connections.
"""

from .client import BinanceClient
from .websocket import WebSocketManager

__all__ = ["BinanceClient", "WebSocketManager"]