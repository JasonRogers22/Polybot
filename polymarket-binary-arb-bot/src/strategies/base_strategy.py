"""
Base strategy interface for all trading strategies.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketState:
    """Current market state snapshot."""
    market_id: str
    condition_id: str
    token_id_yes: str
    token_id_no: str
    price_yes: float
    price_no: float
    liquidity_yes: float
    liquidity_no: float
    timestamp: int
    # executable prices and MTM helpers
    ask_yes: float = 1.0
    ask_no: float = 1.0
    bid_yes: float = 0.0
    bid_no: float = 0.0
    mid_yes: float = 0.0
    mid_no: float = 0.0
    fees_enabled: bool = False
    
    @property
    def price_sum(self) -> float:
        """Sum of YES and NO prices."""
        return self.price_yes + self.price_no


@dataclass
class StrategySignal:
    """Trading signal from strategy."""
    action: str  # "BUY_YES", "BUY_NO", "HOLD", "CLOSE"
    market_id: str
    token_id: str
    size: float
    price: float
    reason: str  # For logging/debugging
    
    @property
    def value(self) -> float:
        """USD value of the signal."""
        return self.size * self.price


class BaseStrategy(ABC):
    """Base class for all trading strategies."""
    
    def __init__(self, config: Dict, position_manager, risk_manager):
        """
        Initialize strategy.
        
        Args:
            config: Strategy configuration dict
            position_manager: PositionManager instance
            risk_manager: RiskManager instance
        """
        self.config = config
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self.is_initialized = False
        
        logger.info(f"Strategy {self.__class__.__name__} created")
    
    @abstractmethod
    async def on_market_update(self, state: MarketState) -> Optional[StrategySignal]:
        """
        Called on every market data update.
        
        Args:
            state: Current market state
            
        Returns:
            StrategySignal if action needed, None otherwise
        """
        pass
    
    @abstractmethod
    async def on_fill(self, market_id: str, token_id: str, filled_size: float, price: float):
        """
        Called when an order is filled (partial or complete).
        
        Args:
            market_id: Market identifier
            token_id: Token ID that was filled
            filled_size: Number of shares filled
            price: Fill price
        """
        pass
    
    @abstractmethod
    def get_state(self) -> Dict:
        """
        Return current strategy state (for persistence/monitoring).
        
        Returns:
            Strategy state dict
        """
        pass
    
    async def initialize(self):
        """Initialize strategy (load positions, etc.)."""
        logger.info(f"Initializing strategy {self.__class__.__name__}")
        self.is_initialized = True
    
    async def shutdown(self):
        """Clean shutdown (save state, etc.)."""
        logger.info(f"Shutting down strategy {self.__class__.__name__}")
        self.is_initialized = False
    
    def _validate_signal(self, signal: StrategySignal) -> bool:
        """
        Validate signal before returning it.
        
        Args:
            signal: Signal to validate
            
        Returns:
            True if valid
        """
        if signal.size <= 0:
            logger.warning(f"Invalid signal: size={signal.size}")
            return False
        
        if signal.price <= 0 or signal.price >= 1:
            logger.warning(f"Invalid signal: price={signal.price}")
            return False
        
        return True
