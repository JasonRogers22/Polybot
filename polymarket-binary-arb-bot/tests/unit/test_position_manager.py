"""
Unit tests for PositionManager.
"""
import pytest
from src.risk.position_manager import Position, MarketPosition, PositionManager


class TestPosition:
    """Test Position class."""
    
    def test_initial_state(self):
        """Test position initialization."""
        pos = Position(token_id="test_token")
        assert pos.quantity == 0.0
        assert pos.total_cost == 0.0
        assert pos.average_price == 0.0
    
    def test_add_shares(self):
        """Test adding shares."""
        pos = Position(token_id="test_token")
        pos.add_shares(10.0, 0.50)
        
        assert pos.quantity == 10.0
        assert pos.total_cost == 5.0
        assert pos.average_price == 0.50
    
    def test_average_price_calculation(self):
        """Test average price calculation with multiple additions."""
        pos = Position(token_id="test_token")
        
        # Buy 10 @ $0.50
        pos.add_shares(10.0, 0.50)
        assert pos.average_price == pytest.approx(0.50)
        
        # Buy 10 @ $0.60
        pos.add_shares(10.0, 0.60)
        assert pos.quantity == 20.0
        assert pos.average_price == pytest.approx(0.55)  # (5.0 + 6.0) / 20


class TestMarketPosition:
    """Test MarketPosition class."""
    
    def test_pair_cost_calculation(self):
        """Test pair cost calculation."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        yes_pos.add_shares(10.0, 0.45)
        no_pos.add_shares(10.0, 0.52)
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        assert market_pos.pair_cost == pytest.approx(0.97)
    
    def test_matched_pairs(self):
        """Test matched pairs calculation."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        yes_pos.add_shares(10.0, 0.45)
        no_pos.add_shares(8.0, 0.52)
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        assert market_pos.matched_pairs == 8.0
        assert market_pos.unmatched_yes == 2.0
        assert market_pos.unmatched_no == 0.0
    
    def test_balance_ratio(self):
        """Test balance ratio calculation."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        # Perfectly balanced
        yes_pos.add_shares(10.0, 0.45)
        no_pos.add_shares(10.0, 0.52)
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        assert market_pos.balance_ratio == pytest.approx(1.0)
        
        # Add more YES to create imbalance
        yes_pos.add_shares(5.0, 0.45)
        assert market_pos.balance_ratio < 1.0
    
    def test_calculate_new_pair_cost(self):
        """Test calculating new pair cost before trade."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        yes_pos.add_shares(10.0, 0.50)  # Current YES avg: $0.50
        no_pos.add_shares(10.0, 0.48)  # Current NO avg: $0.48
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        # Current pair cost
        assert market_pos.pair_cost == pytest.approx(0.98)
        
        # What if we buy 5 YES @ $0.40?
        new_pair_cost = market_pos.calculate_new_pair_cost("YES", 5.0, 0.40)
        # New YES avg: (10*0.50 + 5*0.40) / 15 = 7.0/15 = 0.4667
        # New pair cost: 0.4667 + 0.48 = 0.9467
        assert new_pair_cost == pytest.approx(0.9467, rel=0.01)
    
    def test_should_buy_yes(self):
        """Test should_buy_yes logic."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        no_pos.add_shares(10.0, 0.52)  # Have some NO position
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        # Good opportunity: YES @ $0.45
        should_buy, reason = market_pos.should_buy_yes(
            price=0.45,
            quantity=10.0,
            threshold=0.99,
            max_imbalance=0.3
        )
        assert should_buy
        assert "0.97" in reason or "0.970" in reason  # 0.45 + 0.52
        
        # Bad opportunity: YES too expensive
        should_buy, reason = market_pos.should_buy_yes(
            price=0.55,
            quantity=10.0,
            threshold=0.99,
            max_imbalance=0.3
        )
        assert not should_buy
    
    def test_calculate_pnl(self):
        """Test P&L calculation."""
        yes_pos = Position(token_id="yes_token")
        no_pos = Position(token_id="no_token")
        
        yes_pos.add_shares(10.0, 0.45)
        no_pos.add_shares(10.0, 0.52)
        
        market_pos = MarketPosition(
            market_id="test_market",
            condition_id="test_condition",
            yes_position=yes_pos,
            no_position=no_pos
        )
        
        # 10 matched pairs at pair cost $0.97
        # Each pays $1.00 at settlement
        # P&L = 10 * (1.00 - 0.97) = $0.30
        pnl = market_pos.calculate_pnl()
        assert pnl == pytest.approx(0.30, rel=0.01)


class TestPositionManager:
    """Test PositionManager class."""
    
    def test_create_position(self):
        """Test creating a new position."""
        manager = PositionManager()
        
        position = manager.get_or_create_position(
            market_id="BTC-15m",
            condition_id="condition_123",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        assert position.market_id == "BTC-15m"
        assert position.condition_id == "condition_123"
        assert position.yes_position.token_id == "yes_token"
        assert position.no_position.token_id == "no_token"
    
    def test_get_existing_position(self):
        """Test retrieving existing position."""
        manager = PositionManager()
        
        # Create position
        pos1 = manager.get_or_create_position(
            market_id="BTC-15m",
            condition_id="condition_123",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        # Get same position
        pos2 = manager.get_or_create_position(
            market_id="BTC-15m",
            condition_id="condition_123",
            yes_token_id="yes_token",
            no_token_id="no_token"
        )
        
        assert pos1 is pos2  # Same object
    
    def test_total_value(self):
        """Test total value calculation across positions."""
        manager = PositionManager()
        
        # Create two positions
        pos1 = manager.get_or_create_position(
            market_id="BTC-15m",
            condition_id="btc_cond",
            yes_token_id="btc_yes",
            no_token_id="btc_no"
        )
        
        pos2 = manager.get_or_create_position(
            market_id="ETH-15m",
            condition_id="eth_cond",
            yes_token_id="eth_yes",
            no_token_id="eth_no"
        )
        
        # Add positions
        pos1.yes_position.add_shares(10.0, 0.50)  # $5
        pos1.no_position.add_shares(10.0, 0.50)   # $5
        pos2.yes_position.add_shares(5.0, 0.60)   # $3
        
        total_value = manager.get_total_value()
        assert total_value == pytest.approx(13.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
