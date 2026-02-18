"""
Position manager for tracking YES/NO shares and calculating pair costs.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Tracks position for a single outcome (YES or NO)."""
    token_id: str
    quantity: float = 0.0
    total_cost: float = 0.0
    
    @property
    def average_price(self) -> float:
        """Calculate average entry price."""
        if self.quantity == 0:
            return 0.0
        return self.total_cost / self.quantity
    
    def add_shares(self, quantity: float, price: float):
        """
        Add shares to position.
        
        Args:
            quantity: Number of shares to add
            price: Price per share
        """
        cost = quantity * price
        self.quantity += quantity
        self.total_cost += cost
        
        logger.debug(
            f"Added {quantity:.2f} shares @ ${price:.4f} "
            f"(avg: ${self.average_price:.4f})"
        )
    
    def remove_shares(self, quantity: float) -> float:
        """
        Remove shares from position (e.g., after sale).
        
        Args:
            quantity: Number of shares to remove
            
        Returns:
            Cost basis of removed shares
        """
        if quantity > self.quantity:
            logger.warning(f"Attempting to remove {quantity} shares, only have {self.quantity}")
            quantity = self.quantity
        
        avg_price = self.average_price
        cost_removed = quantity * avg_price
        
        self.quantity -= quantity
        self.total_cost -= cost_removed
        
        return cost_removed


@dataclass
class MarketPosition:
    """Tracks positions for both YES and NO outcomes in a market."""
    market_id: str
    condition_id: str
    yes_position: Position
    no_position: Position
    
    @property
    def pair_cost(self) -> float:
        """
        Calculate pair cost (avg_YES + avg_NO).
        
        Returns:
            Sum of average prices, or 0 if no positions
        """
        return self.yes_position.average_price + self.no_position.average_price
    
    @property
    def total_shares(self) -> float:
        """Total shares across both sides."""
        return self.yes_position.quantity + self.no_position.quantity
    
    @property
    def matched_pairs(self) -> float:
        """Number of matched YES/NO pairs."""
        return min(self.yes_position.quantity, self.no_position.quantity)
    
    @property
    def unmatched_yes(self) -> float:
        """Unmatched YES shares."""
        return max(0, self.yes_position.quantity - self.no_position.quantity)
    
    @property
    def unmatched_no(self) -> float:
        """Unmatched NO shares."""
        return max(0, self.no_position.quantity - self.yes_position.quantity)
    
    @property
    def balance_ratio(self) -> float:
        """
        Ratio of smaller position to larger position.
        1.0 = perfectly balanced, 0.0 = completely imbalanced
        """
        if self.total_shares == 0:
            return 1.0
        
        smaller = min(self.yes_position.quantity, self.no_position.quantity)
        larger = max(self.yes_position.quantity, self.no_position.quantity)
        
        return smaller / larger if larger > 0 else 1.0
    
    @property
    def imbalance(self) -> float:
        """
        Position imbalance as fraction of total.
        0.0 = balanced, 1.0 = completely one-sided
        """
        if self.total_shares == 0:
            return 0.0
        
        diff = abs(self.yes_position.quantity - self.no_position.quantity)
        return diff / self.total_shares
    
    def calculate_new_pair_cost(
        self, 
        side: str, 
        quantity: float, 
        price: float
    ) -> float:
        """
        Calculate what pair cost would be after adding shares.
        
        Args:
            side: "YES" or "NO"
            quantity: Shares to add
            price: Price per share
            
        Returns:
            New pair cost after hypothetical purchase
        """
        if side.upper() == "YES":
            new_qty = self.yes_position.quantity + quantity
            new_cost = self.yes_position.total_cost + (quantity * price)
            new_avg_yes = new_cost / new_qty
            return new_avg_yes + self.no_position.average_price
        else:
            new_qty = self.no_position.quantity + quantity
            new_cost = self.no_position.total_cost + (quantity * price)
            new_avg_no = new_cost / new_qty
            return self.yes_position.average_price + new_avg_no
    
    def should_buy_yes(
        self, 
        price: float, 
        quantity: float,
        threshold: float,
        max_imbalance: float
    ) -> tuple[bool, str]:
        """
        Check if we should buy YES shares.
        
        Args:
            price: Current YES price
            quantity: Quantity to buy
            threshold: Max pair cost threshold
            max_imbalance: Max allowed imbalance
            
        Returns:
            (should_buy, reason)
        """
        new_pair_cost = self.calculate_new_pair_cost("YES", quantity, price)
        
        # Check pair cost threshold
        if new_pair_cost >= threshold:
            return False, f"Pair cost {new_pair_cost:.4f} >= {threshold}"
        
        # Check imbalance
        new_yes_qty = self.yes_position.quantity + quantity
        new_imbalance = abs(new_yes_qty - self.no_position.quantity) / (new_yes_qty + self.no_position.quantity)
        
        if new_imbalance > max_imbalance:
            return False, f"Would create imbalance {new_imbalance:.2%} > {max_imbalance:.2%}"
        
        return True, f"Pair cost {new_pair_cost:.4f} < {threshold}"
    
    def should_buy_no(
        self, 
        price: float, 
        quantity: float,
        threshold: float,
        max_imbalance: float
    ) -> tuple[bool, str]:
        """
        Check if we should buy NO shares.
        
        Args:
            price: Current NO price
            quantity: Quantity to buy
            threshold: Max pair cost threshold
            max_imbalance: Max allowed imbalance
            
        Returns:
            (should_buy, reason)
        """
        new_pair_cost = self.calculate_new_pair_cost("NO", quantity, price)
        
        # Check pair cost threshold
        if new_pair_cost >= threshold:
            return False, f"Pair cost {new_pair_cost:.4f} >= {threshold}"
        
        # Check imbalance
        new_no_qty = self.no_position.quantity + quantity
        new_imbalance = abs(self.yes_position.quantity - new_no_qty) / (self.yes_position.quantity + new_no_qty)
        
        if new_imbalance > max_imbalance:
            return False, f"Would create imbalance {new_imbalance:.2%} > {max_imbalance:.2%}"
        
        return True, f"Pair cost {new_pair_cost:.4f} < {threshold}"
    
    
    def mark_to_market_pnl(self, bid_yes: float, bid_no: float) -> float:
        """Mark-to-market P&L using best bids (liquidation value).

        This is an *unrealized* estimate that becomes important for risk controls and
        for avoiding 'paper profit' illusions from using mid prices.
        """
        value = (self.yes_position.quantity * bid_yes) + (self.no_position.quantity * bid_no)
        cost = self.yes_position.total_cost + self.no_position.total_cost
        return value - cost

    def unmatched_exposure_value(self, bid_yes: float, bid_no: float) -> float:
        """Dollar value of the unmatched side at liquidation bids."""
        if self.unmatched_yes > 0:
            return self.unmatched_yes * bid_yes
        if self.unmatched_no > 0:
            return self.unmatched_no * bid_no
        return 0.0

    def calculate_pnl(self) -> float:
        """
        Calculate realized P&L from matched pairs.
        Each matched pair costs pair_cost and pays $1 at settlement.
        
        Returns:
            Estimated P&L (matched_pairs * (1.0 - pair_cost))
        """
        if self.matched_pairs == 0:
            return 0.0
        
        return self.matched_pairs * (1.0 - self.pair_cost)
    
    def get_summary(self) -> dict:
        """Get position summary."""
        return {
            'market_id': self.market_id,
            'yes_qty': self.yes_position.quantity,
            'yes_avg': self.yes_position.average_price,
            'no_qty': self.no_position.quantity,
            'no_avg': self.no_position.average_price,
            'pair_cost': self.pair_cost,
            'matched_pairs': self.matched_pairs,
            'balance_ratio': self.balance_ratio,
            'imbalance': self.imbalance,
            'estimated_pnl': self.calculate_pnl(),
            'total_cost': self.yes_position.total_cost + self.no_position.total_cost
        }


class PositionManager:
    """Manages positions across multiple markets."""
    
    def __init__(self):
        self.positions: Dict[str, MarketPosition] = {}
        logger.info("Position manager initialized")
    
    def get_or_create_position(
        self,
        market_id: str,
        condition_id: str,
        yes_token_id: str,
        no_token_id: str
    ) -> MarketPosition:
        """
        Get existing position or create new one.
        
        Args:
            market_id: Market identifier
            condition_id: Condition ID
            yes_token_id: YES token ID
            no_token_id: NO token ID
            
        Returns:
            MarketPosition object
        """
        if market_id not in self.positions:
            self.positions[market_id] = MarketPosition(
                market_id=market_id,
                condition_id=condition_id,
                yes_position=Position(token_id=yes_token_id),
                no_position=Position(token_id=no_token_id)
            )
            logger.info(f"Created new position tracker for market {market_id}")
        
        return self.positions[market_id]
    
    def get_position(self, market_id: str) -> Optional[MarketPosition]:
        """Get position for a market."""
        return self.positions.get(market_id)
    
    def get_all_positions(self) -> Dict[str, MarketPosition]:
        """Get all tracked positions."""
        return self.positions
    
    def get_total_value(self) -> float:
        """Get total value across all positions."""
        total = 0.0
        for position in self.positions.values():
            total += position.yes_position.total_cost
            total += position.no_position.total_cost
        return total
    
    def get_total_pnl(self) -> float:
        """Get total estimated P&L across all positions."""
        total_pnl = 0.0
        for position in self.positions.values():
            total_pnl += position.calculate_pnl()
        return total_pnl
