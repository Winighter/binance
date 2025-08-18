"""
This package provides a client for interacting with the Binance API
and a manager for handling WebSocket connections.
"""

__all__ = ["BinanceClient", "WebSocketManager"]

# Binance Client
from .client import BinanceClient

# Websocket Manager
from .websocket import WebSocketManager