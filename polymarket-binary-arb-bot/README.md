```markdown
# Polymarket Binary Arbitrage Bot

A professional-grade trading bot for Polymarket that implements the **Binary Parity Arbitrage** (Gabagool) strategy. This strategy accumulates YES and NO shares when temporarily mispriced, keeping the average pair cost below $1.00 to guarantee profit at settlement.

## 🎯 Strategy Overview

The bot monitors 15-minute crypto prediction markets (BTC, ETH, SOL, XRP) and:

1. **Monitors prices**: Tracks YES and NO prices in real-time via WebSocket
2. **Calculates pair cost**: Computes (avg_YES_price + avg_NO_price)
3. **Identifies opportunities**: Buys when pair cost would stay < $0.99
4. **Manages risk**: Enforces position limits, daily loss limits, and circuit breakers
5. **Guarantees profit**: Each matched YES/NO pair costs < $1.00 but pays $1.00 at settlement

## ✨ Features

- ✅ **Safe by default**: Paper trading mode, multiple safety checks
- ✅ **Real-time data**: WebSocket connections for live orderbook updates
- ✅ **Risk management**: Circuit breakers, position limits, daily loss caps
- ✅ **Position tracking**: Automatic YES/NO inventory management
- ✅ **Kill switch**: Manual emergency stop
- ✅ **Structured logging**: Detailed logs for monitoring and debugging
- ✅ **Configurable**: YAML configuration with sensible defaults

## 🚀 Quick Start (5 Minutes)

### 1. Install

```bash
git clone <repository-url>
cd polymarket-binary-arb-bot
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy example files
cp config.example.yaml config.yaml
cp .env.example .env

# Edit .env with your credentials
nano .env
```

Set your Polymarket credentials:
```bash
POLY_PRIVATE_KEY=0x... # Your wallet private key
POLY_SAFE_ADDRESS=0x... # Your Polymarket Safe address
LIVE_TRADING=false      # Keep as false for paper mode
```

### 3. Run

```bash
# Run in paper mode (safe, no real trades)
python examples/quickstart.py
```

That's it! The bot will start monitoring BTC 15-minute markets and log simulated trades.

## 📁 Project Structure

```
polymarket-binary-arb-bot/
├── src/                          # Core library
│   ├── bot.py                   # Main orchestrator
│   ├── gamma_client.py          # Market discovery
│   ├── websocket_client.py      # Real-time data
│   ├── config/                  # Configuration management
│   ├── risk/                    # Risk management
│   │   ├── risk_manager.py     # Circuit breakers, limits
│   │   └── position_manager.py # Position tracking
│   └── strategies/              # Trading strategies
│       ├── base_strategy.py    # Strategy interface
│       └── binary_parity_arb.py # Main strategy
├── examples/
│   └── quickstart.py           # Getting started example
├── tests/                       # Unit and integration tests
├── config.yaml                  # Your configuration
├── .env                         # Your credentials
└── requirements.txt             # Dependencies
```

## ⚙️ Configuration

Edit `config.yaml` to customize:

```yaml
mode: paper  # paper | live

strategy:
  params:
    pair_cost_threshold: 0.99  # Buy if avg_YES + avg_NO < this
    order_size: 5.0           # Size per order in USDC
    min_liquidity: 10.0       # Min liquidity required
    max_imbalance: 0.3        # Max position imbalance

risk:
  max_daily_loss: 50.0        # Maximum loss per day
  max_position_per_market: 100.0
  max_position_total: 500.0
  kill_switch_enabled: true

markets:
  focus: ["BTC"]              # Coins to trade
```

## 🛡️ Safety Features

### Multiple Layers of Protection:

1. **Paper Mode Default**: Always defaults to simulation mode
2. **Circuit Breakers**: Auto-halt on daily loss limit, stale data, errors
3. **Position Limits**: Per-market and total position caps
4. **Rate Limiting**: Respects API limits (50 orders/minute)
5. **Kill Switch**: Manual emergency stop (Ctrl+C)
6. **Stale Data Detection**: Halts if no updates for 60 seconds
7. **Balance Checks**: Prevents excessive YES or NO imbalance

### How to Enable Live Trading:

Live trading requires EXPLICIT opt-in:

```bash
# 1. Set in .env file
LIVE_TRADING=true

# 2. Set in config.yaml
mode: live

# 3. Start with small amounts
risk:
  max_daily_loss: 10.0  # Start conservatively
```

⚠️ **Warning**: Live trading uses real money. Test thoroughly in paper mode first!

## 📊 Understanding the Strategy

### Example Trade Sequence:

```
Initial state: No position

Market dips:
- YES price drops to $0.45
- Bot buys 10 YES shares
- Position: 10 YES @ $0.45 avg

Market recovers then NO drops:
- NO price drops to $0.52
- Bot buys 10 NO shares
- Position: 10 YES @ $0.45, 10 NO @ $0.52

Pair cost: $0.45 + $0.52 = $0.97 < $0.99 ✅

At settlement:
- 10 matched pairs pay $1.00 each = $10.00
- Cost was $9.70
- Profit: $0.30 (3.1% return)
```

### Key Metrics:

- **Pair Cost**: Sum of average YES and NO prices (must be < $0.99)
- **Matched Pairs**: min(YES_qty, NO_qty) - each guaranteed $1.00
- **Balance Ratio**: Smaller position / Larger position (ideally close to 1.0)
- **Imbalance**: Absolute difference as fraction of total (keep < 30%)

## 📈 Monitoring

The bot logs status every minute:

```
📊 Status: P&L=$-2.50, Pos=$95.00, Orders=12/min, Circuit=closed
  BTC-15m: YES=10.0@$0.4500, NO=8.0@$0.5200, pair=$0.9700, P&L=$2.40
```

Key indicators:
- **P&L**: Estimated profit/loss
- **Pos**: Total position value
- **Circuit**: Circuit breaker state (closed = normal)
- **pair**: Current pair cost (lower is better)

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test
pytest tests/unit/test_position_manager.py -v
```

## 🔧 Advanced Usage

### Custom Strategy Parameters:

```python
# In config.yaml, adjust:
strategy:
  params:
    pair_cost_threshold: 0.98  # More aggressive (higher profit, rarer opportunities)
    order_size: 10.0          # Larger positions
    max_imbalance: 0.2        # Stricter balance requirement
```

### Multiple Markets:

```yaml
markets:
  focus: ["BTC", "ETH", "SOL"]  # Monitor multiple coins
```

### Stricter Risk Controls:

```yaml
risk:
  max_daily_loss: 20.0        # Tighter limit
  max_position_per_market: 50.0
  stale_data_timeout: 30      # More sensitive
```

## 🐛 Troubleshooting

### Bot won't start:

```bash
# Check config file exists
ls config.yaml

# Check .env file exists and has credentials
cat .env

# Check logs
tail -f logs/bot.log
```

### No trading signals:

- Markets may not be volatile enough
- Pair cost threshold too strict (try 0.985 or 0.99)
- Insufficient liquidity
- Check logs for "Skipping" messages

### Circuit breaker triggered:

- Daily loss limit reached → Wait for next trading day
- Stale data → Check network connection
- Manual kill switch → Restart bot

## 📝 Development Status

### ✅ Implemented:
- Binary parity arbitrage strategy
- Real-time WebSocket data
- Risk management & circuit breakers
- Position tracking
- Paper trading
- Configuration system
- Logging

### 🚧 TODO:
- [ ] Live order execution via py-clob-client
- [ ] SQLite position persistence
- [ ] Backtesting engine
- [ ] Performance analytics
- [ ] Alert notifications (Telegram, email)
- [ ] Web dashboard

## ⚠️ Important Disclaimers

1. **No guarantees**: This bot is provided as-is with no warranties
2. **Use at your own risk**: You can lose money
3. **Test thoroughly**: Always paper trade first
4. **Compliance**: Ensure you comply with local regulations
5. **US restrictions**: US residents may be prohibited from Polymarket
6. **Not financial advice**: This is educational software

## 📄 License

MIT License - see LICENSE file

## 🙏 Acknowledgments

- Built on research from the Polymarket community
- Inspired by the "Gabagool" strategy analysis
- Uses official Polymarket APIs

## 📞 Support

For issues or questions:
1. Check the logs: `tail -f logs/bot.log`
2. Review configuration: `cat config.yaml`
3. Test in paper mode first
4. Open an issue on GitHub

---

**Remember**: Start small, test thoroughly, and never risk more than you can afford to lose.
```


## Auto-discover one target market (recommended)

You can have the bot auto-select a **single** target market (e.g., the current ETH 15-minute "Up or Down" market)
by configuring `markets.target` in `config.yaml`.

Example:

```yaml
markets:
  auto_discover: true
  target:
    asset: "ETH"
    keyword: "Up or Down"
    window_minutes: 15
    search_limit: 120
```

When `markets.target` is set, the bot will ignore `markets.focus` and will select the best matching active market.
