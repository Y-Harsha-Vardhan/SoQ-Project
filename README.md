# SoQ Trading Signal Backtester

A Python event-driven backtesting engine for single-asset signal strategies,
demonstrated on ~1,600 daily BTC candles (2019-2023). The engine supports
both compounding and fixed-stake position sizing, reports Sharpe ratio,
win rate, and maximum drawdown, and renders an interactive equity curve
via Plotly. A five-state signal protocol over engineered indicators
(ATR, rolling volume spike) is consumed with next-bar-open execution to
eliminate lookahead bias on the fill side.

## Dependencies

| Package | Version |
|---|---|
| `numpy` | 1.24.4 (pinned) |
| `pandas` | latest |
| `pandas_ta` | latest |
| `plotly` | latest |
| `matplotlib` | latest |
| `scipy` | latest (used by the analysis notebooks only) |

Install with:

```bash
pip install -r requirements.txt
```

## Architecture

| Component | File | Responsibility |
|---|---|---|
| `TradeType` (enum) | `backtester.py` | LONG / SHORT direction tag. |
| `TradePair` | `backtester.py` | Immutable record of a closed round-trip trade. Computes PnL net of per-leg fees, win/loss flag, and holding time. |
| `Position` | `backtester.py` | Mutable container for the current open position (at most one). Enforces signal-vs-direction consistency via `is_valid`. |
| `BackTester` | `backtester.py` | Engine. Loads OHLCV, derives next-bar fill columns, iterates the signal stream, executes trades, scans intrabar TP/SL, computes summary statistics, and renders Plotly visualizations. |
| `process_data` | `main.py` | Appends engineered indicators (ATR(14)). |
| `strat` | `main.py` | Generates signals from a rolling volume-spike threshold plus an ATR(14) trailing stop with 2x multiplier. |
| `analysis/markov_regimes.ipynb` | notebook | First-order 3-state Markov chain on BTC log-returns; transition matrix and stationary distribution. |
| `analysis/poisson_trade_arrivals.ipynb` | notebook | Poisson-process model of trade-arrival times; MLE rate and KS test against exponential gaps. |

## Signal Protocol

The engine consumes a single `signals` column with five integer states:

| Value | Meaning |
|---|---|
| `0` | **HOLD** -- do nothing. |
| `1` | If flat: **open LONG**. If a SHORT is open: **close** it. |
| `-1` | If flat: **open SHORT**. If a LONG is open: **close** it. |
| `2` | **REVERSE SHORT -> LONG** (close short, open long in one step). |
| `-2` | **REVERSE LONG -> SHORT** (close long, open short in one step). |

`Position.is_valid` rejects any signal inconsistent with the current
direction (e.g. cannot open a second long).

## Results

Run on `BTC_2019_2023_1d.csv` (1,577 daily candles, 2019-09-08 to
2024-01-01) with starting capital **$1,000** and per-leg fee
**0.15%**. Both position-sizing modes are reported.

| Metric | Compounding | Fixed-Stake |
|---|---:|---:|
| Total Trades | 104 | 104 |
| Win Rate | **42.31%** | **42.31%** |
| Winning / Losing Streak | 8 / 9 | 8 / 9 |
| Net Profit ($) | **+4,872.60** | **+2,570.14** |
| Return % | **+487.26%** | **+257.01%** |
| Sharpe Ratio | **2.2611** | **3.5986** |
| Maximum Drawdown | **45.51%** | **25.18%** |
| Average Drawdown | 16.55% | 5.64% |
| Largest Win / Loss | +1,925.49 / -930.17 | +454.57 / -257.78 |
| Avg Holding Time | ~11.5 days | ~11.5 days |
| Buy-and-Hold Benchmark | +325.63% | +325.63% |

Sharpe is annualized with sqrt(365) and risk-free rate 0. The
fixed-stake run posts a higher Sharpe (lower stake-induced variance)
but a lower absolute return, exactly as expected.

## Design Decisions

### Next-bar-open execution (lookahead-bias guard)

Signals computed on bar `t` are filled at the **open of bar `t+1`**, not
at bar `t`'s close. The fill price and timestamp are pre-computed in
`BackTester.preprocess_csv` as `next_open` and `next_open_time`. The
final bar has NaN next_open and is skipped. This guarantees that no
trade ever uses information that would not have been available at the
moment of the decision.

A complementary **signal-side** guard lives in `main.py`: for every
emitted signal, the strategy is re-run on a window truncated up to that
bar; if the same signal is produced, the signal depends only on past +
current data. Together these cover both sources of lookahead leakage
(signal generation and order execution).

### Compounding vs fixed-stake

Both modes are supported via `compound_flag`:

- **Compounding (`compound_flag=1`)**: realized PnL is added back into
  the stake after each trade, so subsequent positions are sized on
  grown equity. Matches a real account that reinvests profits.
- **Fixed-stake (`compound_flag=0`)**: every trade is sized on the
  original starting capital regardless of prior PnL. Useful for
  strategy evaluation in isolation -- removes the path-dependent
  variance compounding introduces and produces a cleaner Sharpe
  estimate.

The driver in `main.py` runs both modes back-to-back so they can be
compared directly.

## How to Run

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Run the full strategy + backtests (both modes) + Plotly graphs
python main.py
```

`main.py` will:
1. Build indicators (`process_data`).
2. Generate the five-state signals (`strat`).
3. Run the BackTester in **compounding** mode and print full stats + trade list.
4. Run the BackTester in **fixed-stake** mode and print full stats.
5. Verify signal-side absence of lookahead bias by causal re-simulation.
6. Open interactive Plotly charts: trade overlay on candles, and the
   capital + close-price equity curve.

### Analysis notebooks

```bash
jupyter notebook analysis/
```

- `markov_regimes.ipynb` -- 3-state Markov chain on BTC log-returns.
- `poisson_trade_arrivals.ipynb` -- Poisson model of trade arrival times.

## Project Files

| File | Description |
|---|---|
| `backtester.py` | Event-driven engine, statistics, Plotly visualizations. |
| `main.py` | Indicator pipeline, strategy, driver for both sizing modes. |
| `BTC_2019_2023_1d.csv` | OHLCV input (1,577 daily candles). |
| `updated_final_data.csv` | Signal CSV written by `main.py`. |
| `final_data.csv` | Earlier signal export (kept for reference). |
| `requirements.txt` | Python dependencies. |
| `analysis/` | Standalone Markov / Poisson notebooks. |
| `Problem Statement.pdf` | Original assignment brief. |
| `SoQ_Project_Documentation.pdf` | Submission documentation. |
