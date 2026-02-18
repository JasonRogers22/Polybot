"""
WebSocket client for real-time Polymarket market data.
Handles orderbook updates, trades, and price changes.
"""
import asyncio
import websockets
import json
from typing import Optional, Dict, Callable, List, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderbookSnapshot:
    """Orderbook snapshot with calculated prices."""
    token_id: str
    bids: List[tuple]  # [(price, size), ...]
    asks: List[tuple]  # [(price, size), ...]
    timestamp: int
    
    @property
    def best_bid(self) -> float:
        """Best bid price."""
        return float(self.bids[0][0]) if self.bids else 0.0
    
    @property
    def best_ask(self) -> float:
        """Best ask price."""
        return float(self.asks[0][0]) if self.asks else 1.0
    
    @property
    def mid_price(self) -> float:
        """Mid-market price."""
        return (self.best_bid + self.best_ask) / 2.0
    
    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        return self.best_ask - self.best_bid
    
    @property
    def liquidity_bid(self) -> float:
        """Total liquidity on bid side (top 5 levels)."""
        return sum(float(size) for _, size in self.bids[:5])
    
    @property
    def liquidity_ask(self) -> float:
        """Total liquidity on ask side (top 5 levels)."""
        return sum(float(size) for _, size in self.asks[:5])


    def vwap_ask(self, quantity: float) -> float:
        """Volume-weighted average ask price to buy `quantity` shares.

        Returns 1.0 if there is insufficient depth (forces strategy to skip via liquidity checks).
        """
        if quantity <= 0:
            return self.best_ask
        remaining = quantity
        cost = 0.0
        filled = 0.0
        for price, size in self.asks:
            lvl_qty = min(float(size), remaining)
            if lvl_qty <= 0:
                continue
            cost += float(price) * lvl_qty
            filled += lvl_qty
            remaining -= lvl_qty
            if remaining <= 1e-9:
                break
        if filled <= 0:
            return 1.0
        if remaining > 1e-6:
            return 1.0
        return cost / filled

    def vwap_bid(self, quantity: float) -> float:
        """Volume-weighted average bid price to sell `quantity` shares."""
        if quantity <= 0:
            return self.best_bid
        remaining = quantity
        proceeds = 0.0
        filled = 0.0
        for price, size in self.bids:
            lvl_qty = min(float(size), remaining)
            if lvl_qty <= 0:
                continue
            proceeds += float(price) * lvl_qty
            filled += lvl_qty
            remaining -= lvl_qty
            if remaining <= 1e-9:
                break
        if filled <= 0:
            return 0.0
        if remaining > 1e-6:
            return 0.0
        return proceeds / filled


class MarketWebSocket:
    """WebSocket client for Polymarket market data."""
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self):
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscribed_assets: List[str] = []
        self.orderbooks: Dict[str, OrderbookSnapshot] = {}
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        
        # Event handlers
        self._book_handlers: List[Callable[[OrderbookSnapshot], Awaitable[None]]] = []
        self._trade_handlers: List[Callable[[Dict], Awaitable[None]]] = []
        self._price_change_handlers: List[Callable[[Dict], Awaitable[None]]] = []
    
    def on_book(self, handler: Callable[[OrderbookSnapshot], Awaitable[None]]):
        """Register handler for orderbook updates."""
        self._book_handlers.append(handler)
        return handler
    
    def on_trade(self, handler: Callable[[Dict], Awaitable[None]]):
        """Register handler for trade updates."""
        self._trade_handlers.append(handler)
        return handler
    
    def on_price_change(self, handler: Callable[[Dict], Awaitable[None]]):
        """Register handler for price changes."""
        self._price_change_handlers.append(handler)
        return handler
    
    async def connect(self):
        """Establish WebSocket connection."""
        try:
            self.ws = await websockets.connect(
                self.WS_URL,
                ping_interval=30,
                ping_timeout=10
            )
            logger.info("WebSocket connected")
            self.reconnect_attempts = 0
            return True
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False
    
    async def subscribe(self, asset_ids: List[str], replace: bool = False):
        """
        Subscribe to market data for assets.
        
        Args:
            asset_ids: List of token IDs to subscribe to
            replace: If True, replace existing subscriptions
        """
        if not self.ws:
            await self.connect()
        
        if replace:
            self.subscribed_assets = asset_ids
        else:
            self.subscribed_assets.extend(asset_ids)
            self.subscribed_assets = list(set(self.subscribed_assets))
        
        # Subscribe to all channels
        subscribe_msg = {
            "auth": {},
            "markets": [],
            "assets_ids": self.subscribed_assets,
            "type": "subscribe"
        }
        
        try:
            await self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to {len(self.subscribed_assets)} assets")
        except Exception as e:
            logger.error(f"Subscription failed: {e}")
    
    async def run(self, auto_reconnect: bool = True):
        """
        Run WebSocket event loop.
        
        Args:
            auto_reconnect: Automatically reconnect on disconnect
        """
        self.running = True
        
        while self.running:
            try:
                if not self.ws:
                    connected = await self.connect()
                    if not connected:
                        if auto_reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
                            self.reconnect_attempts += 1
                            await asyncio.sleep(self.reconnect_delay)
                            continue
                        else:
                            logger.error("Max reconnection attempts reached")
                            break
                    
                    # Re-subscribe after reconnection
                    if self.subscribed_assets:
                        await self.subscribe(self.subscribed_assets, replace=True)
                
                # Receive and process messages
                async for message in self.ws:
                    await self._handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self.ws = None
                
                if auto_reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
                    self.reconnect_attempts += 1
                    logger.info(f"Reconnecting... (attempt {self.reconnect_attempts})")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    break
                    
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.ws = None
                
                if auto_reconnect:
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    break
    
    async def _handle_message(self, message: str):
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # Log first 200 chars of message for debugging
            logger.debug(f"WS message: {message[:200]}")
            
            # Handle both list and dict formats
            if isinstance(data, list):
                # Batch format - process each item
                for item in data:
                    if isinstance(item, dict):
                        await self._process_message_item(item)
            elif isinstance(data, dict):
                # Single message format
                await self._process_message_item(data)
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message[:200]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
    
    async def _process_message_item(self, data: Dict):
        """Process a single message item."""
        event_type = data.get('event_type')
        
        logger.debug(f"Processing message: event_type={event_type}, asset_id={data.get('asset_id')}")
        
        if event_type == 'book':
            # Orderbook update
            await self._handle_book_update(data)
        elif event_type == 'last_trade_price':
            # Trade update
            await self._handle_trade_update(data)
        elif event_type == 'price_change':
            # Price change update
            await self._handle_price_change(data)
    
    async def _handle_book_update(self, data: Dict):
        """Handle orderbook update."""
        asset_id = data.get('asset_id')
        if not asset_id:
            return
        
        # Parse bids and asks - they come as dicts with 'price' and 'size' keys
        bids = []
        asks = []
        
        try:
            if 'bids' in data:
                for entry in data['bids']:
                    if isinstance(entry, dict):
                        price = float(entry.get('price', 0))
                        size = float(entry.get('size', 0))
                        bids.append((price, size))
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        bids.append((float(entry[0]), float(entry[1])))
            
            if 'asks' in data:
                for entry in data['asks']:
                    if isinstance(entry, dict):
                        price = float(entry.get('price', 0))
                        size = float(entry.get('size', 0))
                        asks.append((price, size))
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        asks.append((float(entry[0]), float(entry[1])))
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing book data: {e}")
            return
        
        # Create snapshot
        snapshot = OrderbookSnapshot(
            token_id=asset_id,
            bids=sorted(bids, key=lambda x: x[0], reverse=True),
            asks=sorted(asks, key=lambda x: x[0]),
            timestamp=int(datetime.now().timestamp() * 1000)
        )
        
        # Cache snapshot
        self.orderbooks[asset_id] = snapshot
        
        # Log orderbook update
        if len(bids) > 0 and len(asks) > 0:
            logger.info(
                f"Book: {asset_id[:12]}... "
                f"bid={snapshot.best_bid:.4f} "
                f"ask={snapshot.best_ask:.4f} "
                f"mid={snapshot.mid_price:.4f}"
            )
        
        # Notify handlers
        for handler in self._book_handlers:
            try:
                await handler(snapshot)
            except Exception as e:
                logger.error(f"Book handler error: {e}")
    
    async def _handle_trade_update(self, data: Dict):
        """Handle trade update."""
        for handler in self._trade_handlers:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"Trade handler error: {e}")
    
    async def _handle_price_change(self, data: Dict):
        """Handle price change."""
        for handler in self._price_change_handlers:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"Price change handler error: {e}")
    
    def get_orderbook(self, asset_id: str) -> Optional[OrderbookSnapshot]:
        """Get cached orderbook snapshot."""
        return self.orderbooks.get(asset_id)
    
    def get_mid_price(self, asset_id: str) -> Optional[float]:
        """Get cached mid price."""
        snapshot = self.orderbooks.get(asset_id)
        return snapshot.mid_price if snapshot else None
    
    async def disconnect(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket disconnected")
