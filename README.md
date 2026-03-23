# Censorship Alpha

**When countries block crypto exchanges, where does the money go?**

Correlates real-time internet censorship data from [Voidly](https://voidly.ai) with on-chain blockchain fund flows from [Nansen](https://nansen.ai) to reveal how smart money adapts when authoritarian governments block crypto exchanges.

Built for the [Nansen CLI Challenge](https://nansen.ai) #NansenCLI

## What It Does

Runs a single command that:

1. Checks which crypto exchanges are blocked in 15 countries using Voidly's real-time censorship API
2. Pulls smart money flows, DEX activity, and exchange wallet data from 4 blockchains using the Nansen CLI
3. Computes a **Censorship Impact Score** per country
4. Generates an interactive HTML report with charts + PNG exports for social media

## Quick Start

```bash
# Prerequisites: Python 3.9+, Node.js 18+
pip install -r requirements.txt
npm i -g nansen-cli
nansen login --api-key YOUR_KEY

# Generate the report
python3 censorship_alpha.py --png

# Open the report
open output/report.html
```

## What Gets Checked

**Exchanges monitored (8):** Binance, Coinbase, Kraken, KuCoin, OKX, Bybit, Gate.io, Crypto.com

**Countries analyzed (15):** Iran, China, Russia, Turkey, Nigeria, Pakistan, Egypt, Vietnam, India, Saudi Arabia, UAE, Thailand, Myanmar, Belarus, Venezuela

**Chains analyzed (4):** Ethereum, BNB Chain, Solana, Base

## Data Sources

| Source | What | API Calls |
|--------|------|-----------|
| [Voidly](https://voidly.ai) | Exchange accessibility per country, risk tiers, ISP blocking, 7-day forecasts, censorship incidents | 6+ |
| [Nansen CLI](https://github.com/nansen-ai/nansen-cli) | Smart money flows, DEX trades, token screener, exchange wallet balances | 12 |

**Total: 18+ API calls per report**

## Censorship Impact Score

Each country gets a composite score (0-1) based on:

| Factor | Weight | Source |
|--------|--------|--------|
| Exchange block count (out of 8) | 35% | Voidly |
| Country risk tier (1-5) | 25% | Voidly |
| Censorship severity score | 25% | Voidly |
| 7-day forecast risk | 15% | Voidly |

## Report Sections

1. **Exchange Censorship Heat Map** — Which exchanges are blocked where
2. **Smart Money Flows** — Capital movement across ETH, BNB, SOL, Base
3. **Censorship Impact Ranking** — Countries ranked by composite score
4. **The Correlation** — Scatter plot: exchange blocks vs impact score
5. **Top Movers** — Tokens with largest smart money net flows
6. **Country Deep Dives** — ISP-level blocking, incidents, forecasts

## Output

```
output/
├── report.html          # Interactive HTML report
├── heatmap.png          # Exchange blocking heat map
├── flows.png            # Smart money flow chart
├── impact.png           # Impact score ranking
└── correlation.png      # Censorship vs impact scatter
```

## The Thesis

When authoritarian countries block crypto exchanges:

- **Exchange outflows accelerate** — users move to self-custody
- **DEX activity spikes** — blocked CEX users migrate to DEXes
- **BNB chain is a leading indicator** — Binance is the most-blocked exchange globally
- **Exchange censorship predicts broader internet censorship** — crypto blocks are early warning signals

## License

MIT — Built by [Voidly](https://voidly.ai) with [Nansen CLI](https://nansen.ai)
