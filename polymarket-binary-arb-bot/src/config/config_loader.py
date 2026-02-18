"""
Configuration management for Polymarket Binary Arbitrage Bot.
Loads from YAML and environment variables with Pydantic validation.
"""
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, List
from pydantic import BaseModel, validator, Field
from enum import Enum
import re
from dotenv import load_dotenv


class Mode(str, Enum):
    """Trading mode."""
    PAPER = "paper"
    LIVE = "live"


class BuilderConfig(BaseModel):
    """Builder Program configuration for gasless trading."""
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_passphrase: Optional[str] = None


class PolymarketConfig(BaseModel):
    """Polymarket API configuration."""
    private_key: Optional[str] = None
    safe_address: Optional[str] = None
    signature_type: int = 0
    builder: Optional[BuilderConfig] = None
    
    @validator('private_key')
    def validate_private_key(cls, v):
        if v is None or v == "":
            return v
        if not v.startswith('0x') or len(v) != 66:
            raise ValueError('Private key must be 66 characters starting with 0x')
        return v
    
    @validator('safe_address')
    def validate_safe_address(cls, v):
        if v is None or v == "":
            return v
        if not v.startswith('0x') or len(v) != 42:
            raise ValueError('Safe address must be 42 characters starting with 0x')
        return v


class StrategyParams(BaseModel):
    """Strategy-specific parameters."""
    pair_cost_threshold: float = 0.99
    target_balance_ratio: float = 0.9
    min_liquidity: float = 10.0
    order_size: float = 5.0
    max_imbalance: float = 0.3
    # Buffers used to avoid false 'arb' signals once fees/slippage are considered
    fee_enabled_extra_margin: float = 0.01   # additional required edge if market feesEnabled=True
    slippage_buffer: float = 0.002           # depth/slippage allowance
    safety_margin: float = 0.001             # extra conservatism
    
    @validator('pair_cost_threshold')
    def validate_threshold(cls, v):
        if v >= 1.0 or v < 0.90:
            raise ValueError('pair_cost_threshold must be between 0.95 and 1.0')
        return v
    
    @validator('target_balance_ratio')
    def validate_balance(cls, v):
        if v < 0.5 or v > 1.0:
            raise ValueError('target_balance_ratio must be between 0.5 and 1.0')
        return v


class RiskConfig(BaseModel):
    """Risk management configuration."""
    max_daily_loss: float = 50.0
    max_position_per_market: float = 100.0
    max_position_total: float = 500.0
    stale_data_timeout: int = 60
    kill_switch_enabled: bool = True
    max_orders_per_minute: int = 50
    cooldown_after_error: int = 30


class TargetMarketConfig(BaseModel):
    """Auto-discovery target market filters."""
    asset: str = "ETH"                 # e.g., ETH
    keyword: str = "Up or Down"        # phrase in question
    window_minutes: int = 15           # expected duration if start/end present
    min_liquidity: float = 0.0
    min_volume: float = 0.0
    search_limit: int = 100            # number of events to scan

class MarketsConfig(BaseModel):
    """Markets configuration."""
    focus: List[str] = ["BTC"]         # BTC, ETH, SOL, XRP
    market_type: str = "15m"
    auto_discover: bool = True
    # Optional: if set, bot will discover ONE best matching market using these filters
    target: Optional[TargetMarketConfig] = None
class DataConfig(BaseModel):
    """Data feed configuration."""
    websocket_reconnect: bool = True
    websocket_ping_interval: int = 30
    orderbook_buffer_size: int = 100
    reconnect_max_attempts: int = 10
    reconnect_delay: int = 5


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    file: str = "logs/bot.log"
    console: bool = True
    structured: bool = True


class StorageConfig(BaseModel):
    """Storage configuration."""
    database: str = "data/positions.db"
    backup_interval: int = 3600


class StrategyConfig(BaseModel):
    """Strategy configuration."""
    name: str = "binary_parity_arb"
    params: StrategyParams = StrategyParams()


class Config(BaseModel):
    """Main configuration."""
    mode: Mode = Mode.PAPER
    polymarket: Optional[PolymarketConfig] = None
    strategy: StrategyConfig = StrategyConfig()
    risk: RiskConfig = RiskConfig()
    markets: MarketsConfig = MarketsConfig()
    data: DataConfig = DataConfig()
    logging: LoggingConfig = LoggingConfig()
    storage: StorageConfig = StorageConfig()
    
    mode_explicitly_set: bool = False


def _find_and_load_dotenv():
    """
    Load .env from the current working directory or one level up only.
    Safe - does not search system folders or home directory.
    Put your .env in C:\PolyBot\ and always run from C:\PolyBot\polymarket-binary-arb-bot\
    """
    search_paths = [
        Path.cwd() / ".env",               # C:\PolyBot\polymarket-binary-arb-bot\.env
        Path.cwd().parent / ".env",         # C:\PolyBot\.env  <-- recommended location
    ]
    for env_path in search_paths:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            print(f"[OK] Loaded .env from: {env_path}")
            return
    print("[WARN] No .env file found in current folder or parent folder.")
    print("[WARN] Put your .env file in C:\\PolyBot\\ and run from C:\\PolyBot\\polymarket-binary-arb-bot\\")


def load_config(config_path: str = "config.yaml") -> Config:
    """
    Load configuration from YAML file with environment variable substitution.
    
    Args:
        config_path: Path to YAML configuration file
        
    Returns:
        Validated Config object
    """
    # Auto-find and load .env from anywhere in the folder tree
    _find_and_load_dotenv()
    
    # Load YAML
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(path, 'r') as f:
        raw_config = yaml.safe_load(f)
    
    # Substitute environment variables
    config_dict = _substitute_env_vars(raw_config)
    
    # Check if mode was explicitly set
    mode_explicit = 'mode' in raw_config and raw_config['mode'] is not None
    
    # Force paper mode if LIVE_TRADING env var not set to true
    live_trading_env = os.getenv('LIVE_TRADING', 'false').lower()
    if live_trading_env != 'true' and config_dict.get('mode') == 'live':
        print("⚠️  WARNING: LIVE_TRADING env var not set to 'true', forcing PAPER mode")
        config_dict['mode'] = 'paper'
        mode_explicit = False
    
    
    # If running in PAPER mode, polymarket secrets are optional.
    # If env-substitution produced empty strings, drop the polymarket block so validation doesn't fail.
    if config_dict.get('mode') == 'paper':
        poly = config_dict.get('polymarket') or {}
        pk = (poly.get('private_key') or '').strip() if isinstance(poly, dict) else ''
        sa = (poly.get('safe_address') or '').strip() if isinstance(poly, dict) else ''
        if pk == '' and sa == '':
            config_dict.pop('polymarket', None)

# Parse and validate
    config = Config(**config_dict)
    config.mode_explicitly_set = mode_explicit
    
    # Additional safety check
    if config.mode == Mode.LIVE and live_trading_env != 'true':
        config.mode = Mode.PAPER
        print("🛡️  SAFETY: Defaulting to PAPER mode")
    
    return config


def _substitute_env_vars(obj):
    """Recursively substitute ${VAR} with environment variables."""
    if isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        # Match ${VAR_NAME}
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, obj)
        result = obj
        for var_name in matches:
            env_value = os.getenv(var_name, '')
            result = result.replace(f'${{{var_name}}}', env_value)
        return result
    else:
        return obj


# Absolute safety constants (cannot be overridden)
ABSOLUTE_MAX_POSITION = 1000.0  # USD
ABSOLUTE_MAX_DAILY_LOSS = 200.0  # USD
