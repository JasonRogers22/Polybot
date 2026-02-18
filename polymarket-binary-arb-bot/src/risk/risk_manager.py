"""
Risk management system with circuit breakers, position limits, and kill switches.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Trading halted
    MANUAL = "manual"  # Manual kill switch activated


@dataclass
class RiskCheck:
    """Result of a risk check."""
    passed: bool
    reason: str = ""


class RiskManager:
    """
    Enforces risk controls at multiple levels:
    - Pre-trade: Check before order placement
    - Post-trade: Monitor after fills
    - Circuit breakers: Auto-halt on violations
    """
    
    def __init__(self, config):
        """
        Initialize risk manager.
        
        Args:
            config: RiskConfig object
        """
        self.config = config
        self.circuit_breaker_state = CircuitBreakerState.CLOSED
        
        # Position and P&L tracking
        self.realized_pnl = 0.0
        self.daily_pnl = 0.0  # realized + unrealized
        self.total_position = 0.0
        self.market_positions: dict = {}  # market_id -> position_value (cost basis)
        self.unrealized_pnl_by_market: dict = {}  # market_id -> mtm pnl using bids
        # Data freshness
        self.last_data_update = datetime.now()
        
        # Rate limiting
        self.orders_this_minute = 0
        self.minute_start = datetime.now()
        self.error_count = 0
        self.last_error_time: Optional[datetime] = None
        
        # Daily reset
        self.day_start = datetime.now().date()
        
        logger.info(f"Risk manager initialized: max_daily_loss=${self.config.max_daily_loss}")
    
    async def pre_trade_check(
        self, 
        market_id: str,
        order_size: float, 
        order_value: float
    ) -> RiskCheck:
        """
        Check if trade is allowed before execution.
        
        Args:
            market_id: Market identifier
            order_size: Size of order
            order_value: USD value of order
            
        Returns:
            RiskCheck with passed status and reason
        """
        # Check if new day (reset daily stats)
        await self._check_daily_reset()
        
        # 1. Circuit breaker check
        if self.circuit_breaker_state != CircuitBreakerState.CLOSED:
            return RiskCheck(
                False, 
                f"Circuit breaker {self.circuit_breaker_state.value}"
            )
        
        # 2. Daily loss limit
        if self.daily_pnl <= -self.config.max_daily_loss:
            await self.trigger_circuit_breaker("Daily loss limit exceeded")
            return RiskCheck(False, "Daily loss limit exceeded")
        
        # 3. Per-market position limit
        current_market_position = self.market_positions.get(market_id, 0.0)
        new_market_position = current_market_position + order_value
        
        if abs(new_market_position) > self.config.max_position_per_market:
            return RiskCheck(
                False, 
                f"Market position limit exceeded: {new_market_position:.2f} > {self.config.max_position_per_market}"
            )
        
        # 4. Total position limit
        new_total_position = self.total_position + order_value
        if abs(new_total_position) > self.config.max_position_total:
            return RiskCheck(
                False,
                f"Total position limit exceeded: {new_total_position:.2f} > {self.config.max_position_total}"
            )
        
        # 5. Stale data check
        time_since_update = (datetime.now() - self.last_data_update).total_seconds()
        if time_since_update > self.config.stale_data_timeout:
            await self.trigger_circuit_breaker(
                f"Stale data: {time_since_update:.0f}s since last update"
            )
            return RiskCheck(False, "Stale data")
        
        # 6. Rate limiting
        now = datetime.now()
        if (now - self.minute_start).total_seconds() > 60:
            self.orders_this_minute = 0
            self.minute_start = now
        
        if self.orders_this_minute >= self.config.max_orders_per_minute:
            return RiskCheck(
                False, 
                f"Rate limit: {self.orders_this_minute} orders this minute"
            )
        
        # 7. Cooldown after errors
        if self.last_error_time:
            time_since_error = (now - self.last_error_time).total_seconds()
            if time_since_error < self.config.cooldown_after_error:
                return RiskCheck(
                    False,
                    f"Cooldown: {self.config.cooldown_after_error - time_since_error:.0f}s remaining"
                )
        
        return RiskCheck(True)
    
    async def post_trade_update(
        self,
        market_id: str,
        pnl_change: float,
        position_change: float
    ):
        """
        Update risk state after trade execution.
        
        Args:
            market_id: Market identifier
            pnl_change: Change in P&L (positive or negative)
            position_change: Change in position value
        """
        self.realized_pnl += pnl_change
        self.total_position += position_change
        
        # Update market-specific position
        if market_id not in self.market_positions:
            self.market_positions[market_id] = 0.0
        self.market_positions[market_id] += position_change
        
        self.orders_this_minute += 1
        self._recompute_total_pnl()
        
        # Log risk metrics
        logger.info(
            f"Risk update: daily_pnl=${self.daily_pnl:.2f}, "
            f"total_pos=${self.total_position:.2f}, "
            f"market_pos=${self.market_positions[market_id]:.2f}"
        )
        
        # Check if daily loss limit breached post-trade
        if self.daily_pnl <= -self.config.max_daily_loss:
            await self.trigger_circuit_breaker("Daily loss limit exceeded")
    
    async def trigger_circuit_breaker(self, reason: str):
        """
        Trigger circuit breaker and halt trading.
        
        Args:
            reason: Reason for triggering
        """
        if self.circuit_breaker_state == CircuitBreakerState.CLOSED:
            logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason}")
            self.circuit_breaker_state = CircuitBreakerState.OPEN
            
            # TODO: Cancel all open orders
            # TODO: Send alerts (email, Telegram, etc.)
    
    async def manual_kill_switch(self):
        """Manual kill switch - stops all trading immediately."""
        logger.critical("🛑 MANUAL KILL SWITCH ACTIVATED")
        self.circuit_breaker_state = CircuitBreakerState.MANUAL
        
        # TODO: Cancel all open orders
        # TODO: Optionally close positions if configured
    
    def update_data_timestamp(self):
        """Called when new market data received."""
        self.last_data_update = datetime.now()
    
    async def _check_daily_reset(self):
        """Check if we need to reset daily counters."""
        today = datetime.now().date()
        if today > self.day_start:
            logger.info("New trading day - resetting daily counters")
            self.realized_pnl = 0.0
            self.unrealized_pnl_by_market = {}
            self.daily_pnl = 0.0
            self.orders_this_minute = 0
            self.day_start = today
    
    def record_error(self):
        """Record an error for cooldown purposes."""
        self.error_count += 1
        self.last_error_time = datetime.now()
        logger.warning(f"Error recorded (count: {self.error_count})")
    

    def _recompute_total_pnl(self) -> None:
        """Recompute total daily P&L as realized + unrealized."""
        self.daily_pnl = float(self.realized_pnl) + float(sum(self.unrealized_pnl_by_market.values()))

    def update_mark_to_market(self, market_id: str, position, bid_yes: float, bid_no: float):
        """Update unrealized P&L for a market using liquidation bids."""
        try:
            mtm = position.mark_to_market_pnl(bid_yes=bid_yes, bid_no=bid_no)
        except Exception as e:
            logger.debug(f"MTM update failed for {market_id}: {e}")
            return
        self.unrealized_pnl_by_market[market_id] = mtm
        self._recompute_total_pnl()

    def get_status(self) -> dict:
        """Get current risk status."""
        return {
            'circuit_breaker': self.circuit_breaker_state.value,
            'daily_pnl': self.daily_pnl,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl_by_market': self.unrealized_pnl_by_market,
            'total_position': self.total_position,
            'market_positions': self.market_positions,
            'orders_this_minute': self.orders_this_minute,
            'time_since_data': (datetime.now() - self.last_data_update).total_seconds(),
            'loss_limit_remaining': self.config.max_daily_loss + self.daily_pnl
        }
    
    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed."""
        return self.circuit_breaker_state == CircuitBreakerState.CLOSED
