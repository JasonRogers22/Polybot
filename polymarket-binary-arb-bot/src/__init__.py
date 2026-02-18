"""Polymarket Binary Arbitrage Bot package."""

__version__ = "1.0.0"

# Keep package imports side-effect free so submodules can be tested without
# requiring optional runtime dependencies at import time.
__all__ = [
    'bot',
    'config',
    'gamma_client',
    'websocket_client',
    'risk',
    'strategies',
]
