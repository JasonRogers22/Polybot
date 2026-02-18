"""Configuration module for Polymarket Binary Arbitrage Bot."""
from .config_loader import (
    Config,
    Mode,
    PolymarketConfig,
    StrategyParams,
    RiskConfig,
    load_config,
    ABSOLUTE_MAX_POSITION,
    ABSOLUTE_MAX_DAILY_LOSS
)

__all__ = [
    'Config',
    'Mode',
    'PolymarketConfig',
    'StrategyParams',
    'RiskConfig',
    'load_config',
    'ABSOLUTE_MAX_POSITION',
    'ABSOLUTE_MAX_DAILY_LOSS'
]
