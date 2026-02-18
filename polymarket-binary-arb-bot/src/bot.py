"""
Main bot orchestrator - connects all components and runs trading loop.
"""
import asyncio
import signal
import logging
from typing import Optional
from datetime import datetime

from .config import Config, Mode, load_config
from .gamma_client import GammaClient
from .websocket_client import MarketWebSocket, OrderbookSnapshot
from .risk import RiskManager, PositionManager
from .strategies import BaseStrategy, BinaryParityArbStrategy, MarketState

logger = logging.getLogger(__name__)


class TradingBot:
    """
    Main trading bot orchestrator.
    
    Connects:
    - Market data (WebSocket)
    - Strategy logic
    - Risk management
    - Order execution (paper or live)
    """
    
    def __init__(self, config: Config):
        """
        Initialize trading bot.
        
        Args:
            config: Bot configuration
        """
        self.config = config
        self.mode = config.mode
        
        # Components
        self.gamma_client = GammaClient()
        self.websocket = MarketWebSocket()
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager(config.risk)
        
        # Strategy
        self.strategy: Optional[BaseStrategy] = None
        
        # State
        self.running = False
        self.markets = {}  # market_id -> market_info
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Trading bot initialized in {self.mode.value.upper()} mode")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(self.shutdown())
    
    async def initialize(self):
        """Initialize bot components."""
        logger.info("Initializing bot components...")
        
        # Show safety banner
        self._show_safety_banner()
        
        # Initialize strategy
        if self.config.strategy.name == "binary_parity_arb":
            self.strategy = BinaryParityArbStrategy(
                config=self.config.strategy.model_dump(),
                position_manager=self.position_manager,
                risk_manager=self.risk_manager
            )
        else:
            raise ValueError(f"Unknown strategy: {self.config.strategy.name}")
        
        await self.strategy.initialize()
        
        # Discover markets
        await self._discover_markets()
        
        # Setup WebSocket handlers
        self._setup_websocket_handlers()
        
        logger.info("[OK] Bot initialized successfully")
    
    def _show_safety_banner(self):
        """Show safety warning banner."""
        if self.mode == Mode.LIVE:
            logger.warning("="*60)
            logger.warning("!! LIVE TRADING ENABLED !!")
            logger.warning("You are responsible for ToS compliance")
            logger.warning("US residents may be prohibited from trading")
            logger.warning("="*60)
            import time
            time.sleep(3)
        else:
            logger.info("[PAPER] Running in PAPER mode (no real trades)")
    
    async def _discover_markets(self):
        """Discover markets to trade."""
        logger.info("Discovering markets...")

        # If a single target market filter is provided, discover ONE best match.
        target = getattr(self.config.markets, "target", None)
        if target:
            market = await self.gamma_client.discover_market(
                asset=target.asset,
                keyword=target.keyword,
                window_minutes=target.window_minutes,
                min_liquidity=target.min_liquidity,
                min_volume=target.min_volume,
                search_limit=target.search_limit,
            )
            if market:
                market_id = f"{target.asset.upper()}-target"
                self.markets[market_id] = market
                logger.info(f"Found target market: {market.get('question')} (ends: {market.get('end_date')})")
                return
            logger.warning("No target market found; falling back to focus list discovery.")

        # Default: discover per-coin 15m markets
        for coin in self.config.markets.focus:
            market = await self.gamma_client.get_current_15m_market(coin)
            if market:
                market_id = f"{coin}-15m"
                self.markets[market_id] = market
                logger.info(f"Found market: {market.get('question')} (ends: {market.get('end_date')})")
            else:
                logger.warning(f"No active 15-min market found for {coin}")

        if not self.markets:
            logger.warning("No markets found right now. Will retry in 60 seconds...")
            await asyncio.sleep(60)

            # Retry target first if configured
            if target:
                market = await self.gamma_client.discover_market(
                    asset=target.asset,
                    keyword=target.keyword,
                    window_minutes=target.window_minutes,
                    min_liquidity=target.min_liquidity,
                    min_volume=target.min_volume,
                    search_limit=target.search_limit,
                )
                if market:
                    market_id = f"{target.asset.upper()}-target"
                    self.markets[market_id] = market
                    logger.info(f"Found target market on retry: {market.get('question')}")
                    return

            for coin in self.config.markets.focus:
                market = await self.gamma_client.get_current_15m_market(coin)
                if market:
                    market_id = f"{coin}-15m"
                    self.markets[market_id] = market
                    logger.info(f"Found market on retry: {market.get('question')}")

            if not self.markets:
                raise RuntimeError("No markets found to trade after retry - try again in a few minutes")
    def _setup_websocket_handlers(self):
        """Setup WebSocket event handlers."""
        
        @self.websocket.on_book
        async def on_book_update(snapshot: OrderbookSnapshot):
            """Handle orderbook updates."""
            # Update risk manager data timestamp
            self.risk_manager.update_data_timestamp()
            
            # Find market for this token
            market_info = await self._find_market_for_token(snapshot.token_id)
            if not market_info:
                return
            
            # Get YES/NO snapshots
            market_id = market_info['market_id']
            token_ids = market_info['token_ids']
            
            yes_snapshot = self.websocket.get_orderbook(token_ids['yes'])
            no_snapshot = self.websocket.get_orderbook(token_ids['no'])
            
            if not yes_snapshot or not no_snapshot:
                return

            # Update mark-to-market P&L for risk controls using liquidation bids
            pos = self.position_manager.get_or_create_position(
                market_id=market_id,
                condition_id=market_info['condition_id'],
                yes_token_id=token_ids['yes'],
                no_token_id=token_ids['no'],
            )
            self.risk_manager.update_mark_to_market(
                market_id=market_id,
                position=pos,
                bid_yes=yes_snapshot.best_bid,
                bid_no=no_snapshot.best_bid,
            )

            # Create market state
            state = MarketState(
                market_id=market_id,
                condition_id=market_info['condition_id'],
                token_id_yes=token_ids['yes'],
                token_id_no=token_ids['no'],
                # Strategy uses executable BUY prices (depth-aware VWAP on asks)
                price_yes=yes_snapshot.vwap_ask(self.config.strategy.params.order_size),
                price_no=no_snapshot.vwap_ask(self.config.strategy.params.order_size),
                liquidity_yes=yes_snapshot.liquidity_ask,
                liquidity_no=no_snapshot.liquidity_ask,
                timestamp=snapshot.timestamp,
                ask_yes=yes_snapshot.best_ask,
                ask_no=no_snapshot.best_ask,
                bid_yes=yes_snapshot.best_bid,
                bid_no=no_snapshot.best_bid,
                mid_yes=yes_snapshot.mid_price,
                mid_no=no_snapshot.mid_price,
                fees_enabled=market_info.get('fees_enabled', False),
            )
            
            # Get strategy signal
            signal = await self.strategy.on_market_update(state)
            
            if signal:
                await self._handle_signal(signal)
    
    async def _find_market_for_token(self, token_id: str) -> Optional[dict]:
        """Find market info for a token ID."""
        for market_id, market_info in self.markets.items():
            token_ids = market_info.get('token_ids', {})
            if token_id in [token_ids.get('yes'), token_ids.get('no')]:
                return {
                    'market_id': market_id,
                    'condition_id': market_info.get('condition_id'),
                    'token_ids': token_ids,
                    'fees_enabled': market_info.get('fees_enabled', False)
                }
        return None
    
    async def _handle_signal(self, signal):
        """
        Handle trading signal from strategy.
        
        Args:
            signal: StrategySignal object
        """
        # Pre-trade risk check
        risk_check = await self.risk_manager.pre_trade_check(
            market_id=signal.market_id,
            order_size=signal.size,
            order_value=signal.value
        )
        
        if not risk_check.passed:
            logger.warning(f"[ERROR] Risk check failed: {risk_check.reason}")
            return
        
        # Execute order (paper or live)
        if self.mode == Mode.PAPER:
            await self._execute_paper_order(signal)
        else:
            await self._execute_live_order(signal)
    
    async def _execute_paper_order(self, signal):
        """
        Execute order in paper mode (simulation).
        
        Args:
            signal: StrategySignal
        """
        logger.info(
            f"[PAPER ORDER] {signal.action} {signal.size:.2f} shares "
            f"@ ${signal.price:.4f} = ${signal.value:.2f} | {signal.reason}"
        )
        
        # Simulate immediate fill
        await self.strategy.on_fill(
            market_id=signal.market_id,
            token_id=signal.token_id,
            filled_size=signal.size,
            price=signal.price
        )
    
    async def _execute_live_order(self, signal):
        """
        Execute order in live mode (real trading).
        
        Args:
            signal: StrategySignal
        """
        logger.info(
            f"[PROFIT] LIVE ORDER: {signal.action} {signal.size:.2f} shares "
            f"@ ${signal.price:.4f} = ${signal.value:.2f} | {signal.reason}"
        )
        
        # TODO: Implement actual order execution via py-clob-client
        # For now, treat as paper
        logger.warning("[WARNING] Live trading not yet implemented, executing as paper order")
        await self._execute_paper_order(signal)
    
    async def run(self):
        """Run the trading bot."""
        try:
            await self.initialize()
            
            # Collect token IDs to subscribe to
            token_ids = []
            for market_info in self.markets.values():
                token_ids.extend(market_info.get('token_ids', {}).values())
            
            # Subscribe to WebSocket
            await self.websocket.subscribe(token_ids)
            
            logger.info(f"[START] Bot started, monitoring {len(self.markets)} markets")
            
            self.running = True
            
            # Run WebSocket in background
            websocket_task = asyncio.create_task(self.websocket.run(auto_reconnect=True))
            
            # Market refresh counter
            minutes_since_refresh = 0
            
            # Status reporting loop
            while self.running:
                await asyncio.sleep(60)  # Wait 1 minute
                minutes_since_refresh += 1
                
                # Refresh markets every 15 minutes (when new 15m markets start)
                if minutes_since_refresh >= 15:
                    logger.info("[REFRESH] Checking for new 15m markets...")
                    await self._refresh_markets()
                    minutes_since_refresh = 0
                
                await self._report_status()
            
            # Wait for WebSocket to finish
            websocket_task.cancel()
            try:
                await websocket_task
            except asyncio.CancelledError:
                pass
                
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            await self.shutdown()
    
    async def _report_status(self):
        """Report current bot status."""
        risk_status = self.risk_manager.get_status()
        strategy_state = self.strategy.get_state()
        
        logger.info(
            f"[STATUS] "
            f"P&L=${risk_status['daily_pnl']:.2f}, "
            f"Pos=${risk_status['total_position']:.2f}, "
            f"Orders={risk_status['orders_this_minute']}/min, "
            f"Circuit={risk_status['circuit_breaker']}"
        )
        
        # Log position summaries
        for market_id, pos_summary in strategy_state.get('positions', {}).items():
            logger.info(
                f"  {market_id}: "
                f"YES={pos_summary['yes_qty']:.1f}@${pos_summary['yes_avg']:.4f}, "
                f"NO={pos_summary['no_qty']:.1f}@${pos_summary['no_avg']:.4f}, "
                f"pair=${pos_summary['pair_cost']:.4f}, "
                f"P&L=${pos_summary['estimated_pnl']:.2f}"
            )
    
    async def _refresh_markets(self):
        """Refresh market data to get new 15m markets when they rotate."""
        try:
            # Get current markets
            old_market_count = len(self.markets)
            old_markets = list(self.markets.keys())
            
            # Re-discover markets
            await self._discover_markets()
            
            # Check if markets changed
            new_markets = list(self.markets.keys())
            if old_markets != new_markets:
                logger.info(f"[REFRESH] Markets updated: {old_markets} -> {new_markets}")
                
                # Disconnect and reconnect WebSocket with new token IDs
                await self.websocket.disconnect()
                
                # Collect new token IDs
                token_ids = []
                for market_info in self.markets.values():
                    token_ids.extend(market_info.get('token_ids', {}).values())
                
                # Resubscribe
                await self.websocket.subscribe(token_ids)
                logger.info(f"[REFRESH] Resubscribed to {len(token_ids)} tokens")
            else:
                logger.info(f"[REFRESH] Markets unchanged, still monitoring {old_market_count} markets")
                
        except Exception as e:
            logger.error(f"Error refreshing markets: {e}", exc_info=True)
    
    async def shutdown(self):
        """Shutdown bot gracefully."""
        logger.info("Shutting down bot...")
        
        self.running = False
        
        # Disconnect WebSocket
        await self.websocket.disconnect()
        
        # Shutdown strategy
        if self.strategy:
            await self.strategy.shutdown()
        
        # Close gamma client
        if self.gamma_client.session:
            await self.gamma_client.session.close()
        
        logger.info("[OK] Bot shut down successfully")


async def main():
    """Main entry point."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load config
    config = load_config()
    
    # Create and run bot
    bot = TradingBot(config)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
