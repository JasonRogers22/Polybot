"""
Binary Parity Arbitrage Strategy (Gabagool Strategy).

Accumulates YES and NO shares at different times when either side is temporarily
mispriced, keeping the average pair cost (avg_YES + avg_NO) below $1.00 to
guarantee profit at settlement.
"""
from typing import Optional, Dict
import logging
from .base_strategy import BaseStrategy, MarketState, StrategySignal

logger = logging.getLogger(__name__)


class BinaryParityArbStrategy(BaseStrategy):
    """
    Binary parity arbitrage strategy implementation.
    
    Strategy logic:
    1. Monitor YES and NO prices continuously
    2. Calculate what new pair cost would be if we buy either side
    3. Buy YES if new_pair_cost < threshold AND sufficient liquidity AND acceptable imbalance
    4. Buy NO if new_pair_cost < threshold AND sufficient liquidity AND acceptable imbalance
    5. Hold matched pairs until settlement (guaranteed $1.00 payout)
    """
    
    def __init__(self, config: Dict, position_manager, risk_manager):
        """
        Initialize binary parity arbitrage strategy.
        
        Args:
            config: Strategy configuration with params:
                - pair_cost_threshold: Max pair cost (default 0.99)
                - min_liquidity: Min liquidity required (default 10.0)
                - order_size: Size per order (default 5.0)
                - max_imbalance: Max position imbalance (default 0.3)
        """
        super().__init__(config, position_manager, risk_manager)
        
        # Extract parameters
        params = config.get('params', {})
        self.pair_cost_threshold = params.get('pair_cost_threshold', 0.99)
        self.min_liquidity = params.get('min_liquidity', 10.0)
        self.order_size = params.get('order_size', 5.0)
        self.max_imbalance = params.get('max_imbalance', 0.3)
        
        logger.info(
            f"Binary Parity Arb Strategy initialized: "
            f"threshold={self.pair_cost_threshold}, "
            f"min_liq={self.min_liquidity}, "
            f"size={self.order_size}"
        )
    
    
    def _effective_threshold(self, state: MarketState) -> float:
        """Fee/slippage-aware pair cost threshold.

        If market fees are enabled, require additional edge to avoid false arbitrage.
        """
        base = float(self.pair_cost_threshold)
        params = self.config.get('params', {})
        fee_extra = float(params.get('fee_enabled_extra_margin', 0.01))
        slip = float(params.get('slippage_buffer', 0.002))
        safety = float(params.get('safety_margin', 0.001))
        dynamic = 1.0 - slip - safety - (fee_extra if getattr(state, 'fees_enabled', False) else 0.0)
        return min(base, dynamic)

    async def on_market_update(self, state: MarketState) -> Optional[StrategySignal]:
        """
        Process market update and generate trading signal.
        
        Args:
            state: Current market state
            
        Returns:
            StrategySignal if trade opportunity found, None otherwise
        """
        if not self.is_initialized:
            return None
        
        # Get or create position for this market
        position = self.position_manager.get_or_create_position(
            market_id=state.market_id,
            condition_id=state.condition_id,
            yes_token_id=state.token_id_yes,
            no_token_id=state.token_id_no
        )
        
        # Log current position state
        logger.debug(
            f"Market {state.market_id}: "
            f"YES={state.price_yes:.4f} (liq={state.liquidity_yes:.1f}), "
            f"NO={state.price_no:.4f} (liq={state.liquidity_no:.1f}), "
            f"pair_cost={position.pair_cost:.4f}"
        )
        
        # Check YES opportunity
        signal_yes = await self._check_yes_opportunity(state, position)
        if signal_yes:
            return signal_yes
        
        # Check NO opportunity
        signal_no = await self._check_no_opportunity(state, position)
        if signal_no:
            return signal_no
        
        # No opportunity
        return None
    
    async def _check_yes_opportunity(
        self, 
        state: MarketState, 
        position
    ) -> Optional[StrategySignal]:
        """
        Check if we should buy YES shares.
        
        Args:
            state: Market state
            position: Current position
            
        Returns:
            StrategySignal or None
        """
        eff_threshold = self._effective_threshold(state)
        # Check liquidity
        if state.liquidity_yes < self.min_liquidity:
            return None
        
        # Calculate what pair cost would be after buying YES
        new_pair_cost = position.calculate_new_pair_cost(
            side="YES",
            quantity=self.order_size,
            price=state.price_yes
        )
        
        # Check if pair cost is acceptable
        if new_pair_cost >= eff_threshold:
            return None
        
        # Check imbalance
        should_buy, reason = position.should_buy_yes(
            price=state.price_yes,
            quantity=self.order_size,
            threshold=eff_threshold,
            max_imbalance=self.max_imbalance
        )
        
        if not should_buy:
            logger.debug(f"Skipping YES: {reason}")
            return None
        
        # Generate signal
        signal = StrategySignal(
            action="BUY_YES",
            market_id=state.market_id,
            token_id=state.token_id_yes,
            size=self.order_size,
            price=state.price_yes,
            reason=f"Pair cost {new_pair_cost:.4f} < {eff_threshold:.4f} ({reason})"
        )
        
        if self._validate_signal(signal):
            logger.info(f"[SIGNAL] BUY YES signal: {signal.reason}")
            return signal
        
        return None
    
    async def _check_no_opportunity(
        self, 
        state: MarketState, 
        position
    ) -> Optional[StrategySignal]:
        """
        Check if we should buy NO shares.
        
        Args:
            state: Market state
            position: Current position
            
        Returns:
            StrategySignal or None
        """
        eff_threshold = self._effective_threshold(state)
        
        # Check liquidity
        if state.liquidity_no < self.min_liquidity:
            return None
        
        # Calculate what pair cost would be after buying NO
        new_pair_cost = position.calculate_new_pair_cost(
            side="NO",
            quantity=self.order_size,
            price=state.price_no
        )
        
        # Check if pair cost is acceptable
        if new_pair_cost >= eff_threshold:
            return None
        
        # Check imbalance
        should_buy, reason = position.should_buy_no(
            price=state.price_no,
            quantity=self.order_size,
            threshold=eff_threshold,
            max_imbalance=self.max_imbalance
        )
        
        if not should_buy:
            logger.debug(f"Skipping NO: {reason}")
            return None
        
        # Generate signal
        signal = StrategySignal(
            action="BUY_NO",
            market_id=state.market_id,
            token_id=state.token_id_no,
            size=self.order_size,
            price=state.price_no,
            reason=f"Pair cost {new_pair_cost:.4f} < {eff_threshold:.4f} ({reason})"
        )
        
        if self._validate_signal(signal):
            logger.info(f"[SIGNAL] BUY NO signal: {signal.reason}")
            return signal
        
        return None
    
    async def on_fill(
        self, 
        market_id: str, 
        token_id: str, 
        filled_size: float, 
        price: float
    ):
        """
        Update position after order fill.
        
        Args:
            market_id: Market ID
            token_id: Token ID that was filled
            filled_size: Shares filled
            price: Fill price
        """
        position = self.position_manager.get_position(market_id)
        if not position:
            logger.error(f"No position found for market {market_id}")
            return
        
        # Determine if this was YES or NO
        if token_id == position.yes_position.token_id:
            position.yes_position.add_shares(filled_size, price)
            side = "YES"
        elif token_id == position.no_position.token_id:
            position.no_position.add_shares(filled_size, price)
            side = "NO"
        else:
            logger.error(f"Unknown token_id {token_id} for market {market_id}")
            return
        
        # Log updated position
        summary = position.get_summary()
        logger.info(
            f"[OK] Fill: {filled_size:.2f} {side} @ ${price:.4f} | "
            f"Pair cost: ${summary['pair_cost']:.4f} | "
            f"Matched: {summary['matched_pairs']:.1f} | "
            f"Balance: {summary['balance_ratio']:.2%} | "
            f"Est P&L: ${summary['estimated_pnl']:.2f}"
        )
        
        # Update risk manager
        pnl_change = 0.0  # No realized P&L until settlement
        position_change = filled_size * price
        
        await self.risk_manager.post_trade_update(
            market_id=market_id,
            pnl_change=pnl_change,
            position_change=position_change
        )
    
    def get_state(self) -> Dict:
        """
        Get current strategy state.
        
        Returns:
            State dict with all positions
        """
        positions = {}
        for market_id, position in self.position_manager.get_all_positions().items():
            positions[market_id] = position.get_summary()
        
        return {
            'strategy_name': 'binary_parity_arb',
            'parameters': {
                'pair_cost_threshold': self.pair_cost_threshold,
                'min_liquidity': self.min_liquidity,
                'order_size': self.order_size,
                'max_imbalance': self.max_imbalance
            },
            'positions': positions,
            'total_value': self.position_manager.get_total_value(),
            'total_pnl': self.position_manager.get_total_pnl()
        }
