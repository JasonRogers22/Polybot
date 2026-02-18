"""
Quickstart Example - Run binary parity arbitrage bot in paper mode.

This example:
1. Loads configuration from config.yaml
2. Initializes the bot in PAPER mode
3. Discovers active 15-minute markets
4. Monitors for arbitrage opportunities
5. Simulates trades (no real execution)

To run:
    python examples/quickstart.py
"""
import asyncio
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import TradingBot, load_config


async def main():
    """Run the quickstart example."""
    # Setup nice logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/quickstart.log')
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = load_config("config.yaml")
        
        # Ensure we're in paper mode for quickstart
        if config.mode.value != 'paper':
            logger.warning("Forcing PAPER mode for quickstart example")
            config.mode = 'paper'
        
        # Create bot
        logger.info("Creating trading bot...")
        bot = TradingBot(config)
        
        # Run bot
        logger.info("Starting bot...")
        await bot.run()
        
    except FileNotFoundError:
        logger.error(
            "Config file not found. Please copy config.example.yaml to config.yaml "
            "and set your credentials in .env file"
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
