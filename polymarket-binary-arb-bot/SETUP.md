# Setup Guide

Complete setup instructions for the Polymarket Binary Arbitrage Bot.

## Prerequisites

- Python 3.9 or higher
- Polymarket account with a Safe wallet
- Basic understanding of cryptocurrency trading
- Command line familiarity

## Step-by-Step Setup

### 1. Install Python Dependencies

```bash
cd polymarket-binary-arb-bot
pip install -r requirements.txt
```

**Troubleshooting**:
- If `pip install` fails, try: `python3 -m pip install -r requirements.txt`
- For permission errors, use: `pip install --user -r requirements.txt`
- Consider using a virtual environment:
  ```bash
  python3 -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  pip install -r requirements.txt
  ```

### 2. Get Your Polymarket Credentials

#### A. Private Key

**Option 1: MetaMask (Recommended for testing)**
1. Open MetaMask
2. Click the three dots → Account details
3. Click "Show private key"
4. Enter your password
5. Copy the private key (starts with `0x`)

**Option 2: Hardware Wallet**
- Use your hardware wallet's export feature
- NEVER share your hardware wallet seed phrase

#### B. Safe Address

1. Go to [polymarket.com](https://polymarket.com)
2. Connect your wallet
3. Click your profile → Settings
4. Copy your "Wallet Address" (this is your Safe address)

### 3. Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit with your credentials
nano .env  # or use any text editor
```

Add your credentials:
```bash
POLY_PRIVATE_KEY=0x1234...abcd  # Your private key (66 characters)
POLY_SAFE_ADDRESS=0x5678...efgh  # Your Safe address (42 characters)
LIVE_TRADING=false                # Keep false for paper mode
```

**Security Notes**:
- ✅ `.env` is in `.gitignore` (won't be committed)
- ✅ Never share your private key
- ✅ Use a separate wallet for bot testing
- ✅ Start with minimal funds ($10-20)

### 4. Configure Trading Parameters

```bash
# config.yaml is already created with safe defaults
nano config.yaml  # Review and adjust if needed
```

**Recommended for First Run** (already set):
```yaml
mode: paper  # KEEP THIS FOR TESTING

strategy:
  params:
    pair_cost_threshold: 0.99
    order_size: 5.0  # $5 per trade

risk:
  max_daily_loss: 50.0
  max_position_per_market: 100.0
  
markets:
  focus: ["BTC"]  # Start with one market
```

### 5. Test Your Setup

```bash
# Create logs directory
mkdir -p logs

# Run a quick test
python -c "from src import load_config; config = load_config(); print('✅ Config loaded successfully')"
```

If you see `✅ Config loaded successfully`, you're ready to go!

### 6. Run in Paper Mode

```bash
python examples/quickstart.py
```

**What to expect**:
```
2026-02-14 10:30:00 - INFO - Loading configuration...
2026-02-14 10:30:00 - INFO - 📝 Running in PAPER mode (no real trades)
2026-02-14 10:30:01 - INFO - Discovering markets...
2026-02-14 10:30:02 - INFO - Found market: Will BTC be up or down in 15 minutes?
2026-02-14 10:30:03 - INFO - 🚀 Bot started, monitoring 1 markets
```

The bot will:
- Monitor the BTC 15-minute market
- Log when it would execute trades
- Update status every minute
- NOT execute any real trades

### 7. Monitor the Bot

**In another terminal**, watch the logs:
```bash
tail -f logs/quickstart.log
```

Look for:
- `📊 Status` - Regular updates
- `🎯 BUY YES/NO signal` - Opportunities found
- `📝 PAPER ORDER` - Simulated trades
- `✅ Fill` - Position updates

### 8. Stop the Bot

Press `Ctrl+C` to stop gracefully. The bot will:
1. Disconnect from WebSocket
2. Save state
3. Log final positions

## Verification Checklist

Before going live, verify:

- [ ] Bot runs in paper mode without errors
- [ ] You see market data updates in logs
- [ ] Paper trades are being logged
- [ ] Circuit breakers work (test by setting very low daily loss limit)
- [ ] Kill switch works (Ctrl+C stops cleanly)
- [ ] You understand the strategy (read README.md)
- [ ] You've tested for at least 24 hours in paper mode

## Going Live (Advanced)

⚠️ **ONLY after thorough paper trading testing**

### 1. Start Small

Edit `config.yaml`:
```yaml
mode: live  # Enable live mode

risk:
  max_daily_loss: 10.0  # Very conservative
  max_position_per_market: 25.0
  max_position_total: 50.0

strategy:
  params:
    order_size: 2.0  # Small size
```

Edit `.env`:
```bash
LIVE_TRADING=true  # REQUIRED for live mode
```

### 2. Fund Your Wallet

- Transfer small amount to your Safe wallet ($20-50)
- Ensure you have USDC on Polygon

### 3. Run with Monitoring

```bash
# Run in one terminal
python examples/quickstart.py

# Monitor in another
tail -f logs/quickstart.log
```

### 4. Watch Closely

For the first hour:
- Monitor every trade
- Verify positions on polymarket.com
- Check P&L calculations
- Be ready to hit Ctrl+C (kill switch)

### 5. Gradual Scale-Up

After 24 hours of successful operation:
- Increase position sizes gradually
- Add more markets (ETH, SOL)
- Increase loss limits carefully
- Keep monitoring daily

## Common Issues

### "Config file not found"
```bash
# Make sure you're in the right directory
pwd  # Should show: .../polymarket-binary-arb-bot

# Check if config.yaml exists
ls config.yaml

# If missing, copy from example
cp config.example.yaml config.yaml
```

### "Private key must be 66 characters"
- Private key must start with `0x`
- Must be exactly 66 characters total
- Check for spaces or newlines in .env

### "No active 15-minute market found"
- Markets are only active at specific times
- Wait 5-10 minutes and try again
- Try different coins: change `focus: ["ETH"]`

### "WebSocket connection failed"
- Check internet connection
- Try again (may be temporary)
- Check Polymarket status page

### "Circuit breaker triggered"
- This is NORMAL - it's protecting you
- Check the reason in logs
- Common: daily loss limit, stale data
- Reset by restarting bot next day

## Getting Help

1. **Check logs**: `tail -f logs/quickstart.log`
2. **Review config**: `cat config.yaml`
3. **Test imports**: `python -c "import src; print('OK')"`
4. **Verify credentials**: Check .env file (without sharing it!)

## Security Best Practices

✅ **DO**:
- Use a dedicated wallet for bot
- Start in paper mode
- Start with minimal funds
- Monitor actively
- Use version control for config (without secrets)

❌ **DON'T**:
- Share your private key
- Commit .env to git
- Skip paper trading
- Use your main wallet
- Trade more than you can lose

## Next Steps

Once comfortable:
1. Read the full README.md
2. Review the strategy code: `src/strategies/binary_parity_arb.py`
3. Understand risk management: `src/risk/risk_manager.py`
4. Run tests: `pytest tests/ -v`
5. Customize parameters for your risk tolerance

---

**Remember**: Start small, test thoroughly, and never risk more than you can afford to lose.
