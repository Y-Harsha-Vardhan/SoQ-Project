# Interview Prep — SoQ Trading Signal Backtester

Everything in this document is grounded in the actual code in
`backtester.py`, `main.py`, the analysis notebooks under `analysis/`,
and the dataset `BTC_2019_2023_1d.csv`. Where the code does not support
a claim, that gap is called out explicitly under **Honest Gaps**.

---

## 1. Architecture

### 1.1 Classes

#### `TradeType` (Enum, `backtester.py`)
- Two members: `LONG = 1`, `SHORT = -1`.
- `__str__` returns `"LONG"` or `"SHORT"` for printing.
- Purpose: a typed tag for the direction of a closed trade. Not used to
  control any logic — that is done via `sign(qty)`.

#### `TradePair` (`backtester.py`)
Immutable record of one round-trip trade (open + close).

Fields: `symbol`, `qty` (signed USD notional; +ve = long, -ve = short),
`init_price`, `final_price`, `init_timestamp`, `final_timestamp`.

Methods:
- `__init__(...)` — store the six fields above.
- `__str__()` — human-readable summary, e.g.
  `TRADED BTC LONG $1000 @10000 to 10500 in t0 - t1`.
- `trade_type()` — returns `TradeType.LONG` if `qty > 0` else `SHORT`.
- `pnl()` — returns `qty * (final_price - init_price) / init_price - transaction_fee * |qty|`.
  This is dollar PnL based on percentage move scaled by notional, minus
  a single fee charge proportional to |notional|.
- `is_win()` — `pnl() > 0`.
- `holding_time()` — `final_timestamp - init_timestamp` (a `Timedelta`).
- `drawdown()` — percentage between high and low of `init_price` and
  `final_price` (very coarse two-point drawdown; not used by the main
  drawdown calculation, which uses cumulative equity).

#### `Position` (`backtester.py`)
Mutable container for the currently open position. At most one open
position at a time.

Fields: `symbol`, `qty`, `price`, `timestamp`.

Methods:
- `__init__(...)` — start flat or with a position.
- `is_valid(signal)` — true if the next signal is consistent with the
  current direction. If flat (`qty == 0`), any signal with `|signal| <= 1`
  is valid (i.e. `-1, 0, 1`). If a position exists, the signal must be
  opposite sign (`sign(qty) * sign(signal) <= 0`).
- `open(price, qty, timestamp)` — set fields to start a new position.
- `close(price, timestamp)` — build and return a `TradePair`, then zero
  out the position.

#### `BackTester` (`backtester.py`)
The engine. One instance per backtest run.

Constructor `__init__(symbol, signal_data_path, master_file_path=None, compound_flag=0)`:
- Stores `compound_flag` and `symbol`.
- Loads the signal CSV via `preprocess_csv` into `self.data`.
- If `TP` / `SL` columns are missing, fills them with 0 (i.e. disabled).
- Loads the master OHLCV (defaults to the signal CSV) for intrabar TP/SL
  scanning into `self.master_data`.
- Initializes `self.trades = []` and `self.position = Position(symbol, 0, None, None)`.
- `self.tp = self.sl = 0`.

### 1.2 Methods (all on `BackTester`)

- `preprocess_csv(file_path)` — load OHLCV, parse `datetime`, sort, add
  three derived columns:
  - `nextdatetime = datetime + 1 minute` (used as the upper bound for
    the intrabar TP/SL scan window).
  - `next_open = open.shift(-1)` (the open price of the *next* candle).
  - `next_open_time = datetime.shift(-1)` (the timestamp of the *next*
    candle).
  Then sets `datetime` as the index. The last row will have NaN
  `next_open` / `next_open_time` and is therefore skipped by
  `get_trades`.

- `check_tp_sl(timestamp, next_timestamp)` — if a position is open and
  `tp != 0` or `sl != 0`, iterate `master_data` rows in
  `[timestamp, next_timestamp]` and trigger an intrabar close if `high`
  hits TP or `low` hits SL (for longs; mirror for shorts). Returns the
  resulting `TradePair` or `None`. Note: in this repository the strategy
  never sets TP/SL, so this branch is dormant.

- `get_trades(trade_amt)` — the main simulation loop. For each row in
  `self.data`:
  1. Read `signal = row["signals"]`.
  2. Determine `fill_price = row["next_open"]`, `fill_time = row["next_open_time"]`. If `next_open` is NaN (last bar), continue.
  3. Validate the signal against the current `Position`; raise on
     inconsistency.
  4. Try to trigger TP/SL via `check_tp_sl`. If triggered, append the
     trade and (if compounding) grow `trade_amt`.
  5. Update `self.tp` / `self.sl` from the row's TP/SL columns.
  6. Dispatch on signal:
     - `0` — hold (skip).
     - `±1` — if flat, open at `fill_price`; if a position exists, close
       it at `fill_price`.
     - `±2` — close existing and immediately open the opposite side at
       `fill_price`.
     - anything else — raise `ValueError`.

- `get_statistics()` — compute and return a dictionary with: Total
  Trades, Leverage Applied (hard-coded `1`), Winning Trades, Losing
  Trades, # Long, # Short, Benchmark Return (%) and (on $1000), Win
  Rate, Winning Streak, Losing Streak, Gross Profit, Net Profit,
  Average Profit, Maximum Drawdown (%), Average Drawdown (%), Largest
  Win, Average Win, Largest Loss, Average Loss, Maximum Holding Time,
  Average Holding Time, Maximum Adverse Excursion (`None`), Average
  Adverse Excursion (`None`), Sharpe Ratio, Sortino Ratio (`None`).
  Returns `None` if no trades were executed.

- `get_benchmark_return()` — `(close_last - close_first) / close_first`,
  i.e. buy-and-hold over the same window.

- `get_streaks()` — single pass over `self.trades` to find max
  consecutive wins and max consecutive losses.

- `get_drawdown(pnl_array)` — builds cumulative equity = `1000 + cumsum(pnl)`,
  computes running maximum, then returns (`max drawdown`, `mean drawdown`)
  expressed as absolute percentages. Drawdown is in equity space, not in
  trade-level percentage space.

- `plot_drawdown()` — Matplotlib line of drawdown over time. Not called
  by `main.py`.

- `get_sharpe_ratio(risk_free_rate=0.0)` — `mean(pnl / init_price) * sqrt(365) / std(pnl / init_price)`.
  The per-trade "return" is the trade's dollar PnL divided by the
  trade's entry price (not equity), and annualization uses `sqrt(365)`.

- `get_sortino_ratio(risk_free_rate=0.0)` — defined but never reported
  by `get_statistics` (the dict sets it to `None`). Uses downside-only
  standard deviation.

- `calc_pnl()` — fills a `pnl` column on `self.data` bar-by-bar. For
  each bar inside a trade window, contribution is
  `qty * (close_t - close_{t-1}) / init_price`; closing fee is charged
  on the trade's close bar.

- `calc_capital()` — adds a `capital = 1000 + cumsum(pnl)` column.

- `get_granular_sharpe_ratio(period="1D")` — Sharpe computed on
  equity-change samples over fixed periods (default 1 day), annualized
  by `sqrt(365)`. Available but not reported by default.

- `get_granular_sharpe_ratio_window(window_size="6ME", period="1D")` —
  rolling-window list of granular Sharpes. Not reported by default.

- `make_trade_graph()` — Plotly candlestick with green/red shaded
  rectangles over the bars where a long/short was open.

- `make_pnl_graph()` — Plotly chart: equity curve on the primary y-axis
  (colored red while in a trade, blue while flat), close price overlay
  on the secondary y-axis. This is the "equity curve" referenced on the
  resume.

### 1.3 Data flow, raw CSV to equity curve

1. `main.py` reads `BTC_2019_2023_1d.csv` into a pandas DataFrame.
2. `process_data(data)` appends `ATR` (period 14) via `pandas_ta.atr`.
3. `strat(data)` iterates bars from index 14 onward, computes a 6-bar
   rolling volume threshold (`mean + 1.5 * std`) and a 2x-ATR trailing
   stop, and writes the `signals` column using the five-state protocol.
   Output is saved to `updated_final_data.csv`.
4. For each of two modes (compounding, fixed-stake) a `BackTester` is
   instantiated on that CSV. `preprocess_csv` adds the `nextdatetime`,
   `next_open`, and `next_open_time` columns.
5. `get_trades(1000)` simulates trades: each non-zero signal fills at
   `next_open` with timestamp `next_open_time`. Closed trades land in
   `self.trades`.
6. `get_statistics()` computes summary metrics from `self.trades`.
7. `calc_capital()` fills `self.data["capital"]`. `make_trade_graph()`
   and `make_pnl_graph()` render Plotly visualizations of trades and
   the equity curve.

### 1.4 Design decisions present in the code

- **Single-asset, single-position-at-a-time**. `Position` holds one
  open trade. `is_valid` actively rejects same-direction stacking.
- **Five-state signal protocol** unifies entries, exits, and reversals
  in one column rather than separate buy/sell/close columns.
- **Next-bar-open execution** rather than same-bar close — the engine
  precomputes `next_open` / `next_open_time` and uses them for every
  fill so that the bar that produced the signal cannot be the bar that
  trades on it.
- **Fee model is one number** (`transaction_fee = 0.0015`) applied as
  `0.0015 * |qty|` inside `TradePair.pnl()`. There is no separate fee
  charged on the open leg in the simulator's PnL — the fee charge in
  `pnl()` is a single round-trip charge.
- **`compound_flag` toggles equity-growth sizing**. With `1`, `trade_amt`
  in `get_trades` is incremented by realized PnL; with `0`, the stake
  is fixed at the starting amount for every trade.
- **Drawdown is computed in equity space**, not per-trade. Equity is
  `1000 + cumsum(trade_pnl)`. Running max minus current gives drawdown.
- **Sharpe per-trade with sqrt(365) annualization**. This is not a
  textbook Sharpe; see the *Honest Gaps* section.
- **Plotly for interactive visualization**, Matplotlib only for the
  unused `plot_drawdown`.

---

## 2. Dataset

- File: `BTC_2019_2023_1d.csv` in the repo root.
- Source: not stated inside the file. It is daily BTC OHLCV that
  matches widely available historical Bitcoin data (likely Binance or
  similar; the code does not document this). **Honest gap**: the
  provenance is not recorded in the repo.
- Number of rows: **1,577 candles** (data rows; line count 1578
  including the header).
- Date range: **2019-09-08 to 2024-01-01** (the filename says
  "2019_2023" but the data extends one bar into 2024-01-01).
- Granularity: 1 candle per day.
- Columns (header is `,datetime,open,high,low,close,volume`):
  - unnamed integer index (ignored functionally, but pandas reads it)
  - `datetime` — parsed via `pd.to_datetime`, used as the bar index.
  - `open` — used to derive `next_open` for execution fills.
  - `high` — used by intrabar TP/SL scanning (not exercised here).
  - `low` — same.
  - `close` — used by `strat` for direction (close vs open), trailing-
    stop comparisons, the `num_wrong` counter, ATR, the benchmark
    return, and per-bar PnL in `calc_pnl`.
  - `volume` — used by `strat` for the 6-bar rolling volume threshold
    (`mean + 1.5 * std`).

---

## 3. Signal Protocol

### 3.1 The five states (consumed in `backtester.py`, emitted in `main.py`)

| Value | Meaning |
|:---:|---|
| `0` | HOLD — do nothing. |
| `1` | If flat, open LONG. If a SHORT is open, close it. |
| `-1` | If flat, open SHORT. If a LONG is open, close it. |
| `2` | Reverse SHORT → LONG (close short and open long in one step). |
| `-2` | Reverse LONG → SHORT (close long and open short in one step). |

`Position.is_valid` enforces that the signal is compatible with the
current direction; raising on inconsistency.

### 3.2 How each signal is generated in `strat`

For every bar `i >= 14` the code computes:
```
vol_spike = mean(volume[i-5..i]) + 1.5 * std(volume[i-5..i])
```
That is the rolling 6-bar volume threshold.

If currently **flat** (`position == 0`):
- If `volume[i] > vol_spike` and `close[i] > open[i]` (bullish candle):
  emit `1`, set `position = 1`, set `trailing_stop = close - 2 * ATR`.
- Else if `volume[i] > vol_spike` and `close[i] < open[i]` (bearish):
  emit `-1`, set `position = -1`, `trailing_stop = close + 2 * ATR`.

If currently **long** (`position == 1`):
- `trend_rev = (volume >= vol_spike) and (close < open)` (volume-spike
  bearish candle).
- Track `num_wrong = consecutive bars with close_i <= close_{i-1}`.
- If `trend_rev`: emit `-2`, flip to short, reset trailing stop above
  price.
- Else if `num_wrong == 3` or `close < trailing_stop`: emit `-1`, go
  flat.
- Else ratchet the trailing stop upward:
  `trailing_stop = max(trailing_stop, close - 2 * ATR)`.

If currently **short** (`position == -1`): symmetric. Emit `2` on
reversal, `1` on stop-out or three-bar stall, else ratchet the stop
downward.

### 3.3 Indicators feeding the signal logic

Only one indicator is computed in `process_data`, plus one inline
threshold and one inline trailing stop in `strat`.

| Name | Where | Formula / parameters |
|---|---|---|
| `ATR` (Average True Range) | `process_data` via `pandas_ta.atr` | `length=14` over `high`, `low`, `close`. Standard ATR: TR = max(H-L, |H-prev_close|, |L-prev_close|); ATR = smoothed average of TR over 14 bars. |
| Rolling volume spike threshold | `strat` | `mean(volume[i-5..i]) + 1.5 * std(volume[i-5..i])`. 6-bar window, 1.5σ band. |
| ATR trailing stop | `strat` | `close ± 2 * ATR`. Multiplier `trailing_stop_multiplier = 2`. Ratchets monotonically in the favorable direction. |

No other indicators (no moving averages, RSI, MACD, Bollinger, etc.).

---

## 4. Execution Model

### 4.1 Next-candle execution

In `preprocess_csv` the engine precomputes:
```
data["next_open"]      = data["open"].shift(-1)
data["next_open_time"] = data["datetime"].shift(-1)
```
In `get_trades`, every open and close uses `fill_price = row["next_open"]`
and `fill_time = row["next_open_time"]`. If `next_open` is NaN (the
final candle) the loop skips that row.

This means: a signal generated using information available at bar `t`
fills at the open of bar `t+1`. The bar that produced the signal cannot
also be the bar that trades on it.

### 4.2 What lookahead bias is and how this engine avoids it

Lookahead bias is using information at decision time that would not
actually have been available yet — either because the indicator silently
peeks ahead (signal-side leakage) or because the simulator fills at a
price that would not be tradable until information from later in the
same bar (execution-side leakage).

This engine guards both:
- **Signal side**: `main.py` re-runs `process_data` and `strat` on
  data truncated to `[0..i]` for every emitted signal and checks that
  the signal at bar `i` is unchanged. If a signal flips when later bars
  are removed, that signal depended on future data and the script flags
  it. In this repo the check reports "No lookahead bias detected."
- **Execution side**: fills happen at `next_open` (bar `t+1`'s open),
  not at the close of the signal bar, so even a signal that uses
  bar `t`'s close cannot transact at that close.

### 4.3 Fee model

- Constant: `transaction_fee = 0.0015` (0.15%).
- Applied: inside `TradePair.pnl()` as `- transaction_fee * |qty|`. That
  is one charge per round trip, scaled by notional.
- **Honest note**: a strict per-leg model would charge `0.0015 * |qty|`
  on the open and again on the close (effectively `0.0030 * |qty|` per
  round trip). The current implementation charges it once. If asked,
  acknowledge this: the constant is labeled "per leg" in intent but
  the code applies it once per trade.

### 4.4 Position sizing

- **Compounding (`compound_flag = 1`)**: in `get_trades`, after each
  closed trade `trade_amt = trade_amt + trade.pnl()`. The next open
  position is sized on that updated stake. Equity growth feeds back
  into position size.
- **Fixed-stake (`compound_flag = 0`)**: the `trade_amt` argument
  passed into `get_trades` is never updated by realized PnL, so every
  trade is sized on the initial $1,000 stake regardless of prior
  outcomes.
- Both modes start at $1,000 in `main.py` via `bt.get_trades(1000)`.

---

## 5. Risk and Performance

### 5.1 Sharpe ratio (as implemented)

```
returns      = [trade.pnl() / trade.init_price for trade in trades]
mean_return  = mean(returns)
return_std   = std(returns)
sharpe       = (mean_return - 0) * sqrt(365) / return_std
```

It is **per-trade** Sharpe, not per-period. Each sample is one closed
trade's dollar PnL divided by that trade's entry price. The
annualization factor is `sqrt(365)` (calendar days). This is a
non-standard Sharpe and should be presented as "per-trade, annualized
by sqrt(365)" rather than as a textbook portfolio Sharpe.

### 5.2 Maximum drawdown

```
equity      = 1000 + cumsum(trade_pnls)
running_max = equity.cummax()
drawdown    = (equity - running_max) / running_max
max_dd      = |min(drawdown)| * 100
avg_dd      = |mean(drawdown)| * 100
```

This is drawdown of realized equity at trade-close timestamps, not
mark-to-market drawdown bar by bar. Intrabar drawdown of open
positions is not captured by this number.

### 5.3 Win rate

```
win_rate = (number of trades with pnl > 0) / total_trades * 100
```

A trade is a "win" iff `pnl() > 0` (after the single fee charge).

### 5.4 Equity curve

`calc_capital()` fills `self.data["capital"] = 1000 + cumsum(pnl)`,
where the per-bar `pnl` is computed by `calc_pnl()` using
`qty * (close_t - close_{t-1}) / init_price` while in a trade and 0
otherwise. `make_pnl_graph()` plots this as a Plotly line, red while
in a trade and blue while flat, with the close price overlaid on a
secondary axis.

### 5.5 Actual numbers (current code, $1,000 start, daily BTC 2019-09-08
to 2024-01-01)

| Metric | Compounding | Fixed-Stake |
|---|---:|---:|
| Trades | 104 | 104 |
| Win rate | 42.31% | 42.31% |
| Winning / losing streak | 8 / 9 | 8 / 9 |
| Net profit | $4,872.60 | $2,570.14 |
| Final value | $5,872.60 | $3,570.14 |
| Return | +487.26% | +257.01% |
| Sharpe | 2.2611 | 3.5986 |
| Max drawdown | 45.51% | 25.18% |
| Average drawdown | 16.55% | 5.64% |
| Largest win / loss | +1,925.49 / -930.17 | +454.57 / -257.78 |
| Avg holding time | ~11.5 days | ~11.5 days |
| Buy-and-hold benchmark | +325.63% | +325.63% |

Compounding beats fixed-stake on absolute return but with a much larger
drawdown. Fixed-stake's Sharpe is higher because stake-induced variance
is removed.

---

## 6. Limitations and Honest Gaps

What the code does NOT do:

1. **Slippage** — fills assume the next bar's open is achievable. No
   slippage model, no bid-ask spread.
2. **Partial fills / liquidity** — full notional fills instantly.
3. **Leverage** — `Leverage Applied: 1` is hard-coded in
   `get_statistics`. No margin model.
4. **Per-leg vs round-trip fee** — fee is charged once in `pnl()`,
   not on each leg.
5. **TP / SL** — engine supports it (`check_tp_sl`), but the strategy in
   `main.py` never sets TP or SL columns, so this code path is dormant.
6. **Sortino, Adverse Excursion** — fields exist in the stats dict but
   are returned as `None`.
7. **Sharpe annualization** — uses `sqrt(365)`. For daily data using
   per-trade samples this is a convention, not a derivation, and the
   number is sensitive to it.
8. **Per-trade Sharpe** — the Sharpe here is per closed trade, not
   per fixed time period; this differs from a standard portfolio
   Sharpe and is not directly comparable to industry quotes.
9. **Single asset only** — `BackTester` simulates one symbol. No
   portfolio, no correlation, no rebalancing logic.
10. **No parameter tuning / walk-forward** — ATR length 14, multiplier
    2, volume window 6, threshold 1.5σ, `num_wrong == 3` are all hard
    coded. No grid search, no out-of-sample split.
11. **Survivorship / data quality** — BTC has no survivorship issue,
    but the data source is not documented in the repo.
12. **Funding rates** — relevant for crypto perpetuals; not modeled.
13. **Cash-flow timing** — all PnL realized at close timestamp; no
    interest on idle cash.
14. **`drawdown()` on `TradePair`** — a coarse two-point measure that
    is not used in the headline drawdown metric and could mislead if
    read alone.

What would need to change to go live:
- Replace `pd.read_csv` with a live market-data feed.
- Replace `Position.open` / `close` with broker API calls.
- Add slippage and partial-fill modeling, then retest.
- Add a kill-switch and reconciliation between simulated state and the
  broker's reported state.
- Charge fees per leg, including funding for perpetual contracts.
- Add monitoring (open-position checks, position-size limits, max
  daily loss).
- Account for execution latency: signal at `t+1`'s open assumes you
  can place an order before the candle opens; in reality you need a
  market order at the open or a limit slightly above/below.

Assumptions baked into the model:
- All trades fill instantly at exactly the next candle's open.
- BTC is liquid enough that notional has no price impact.
- Fee is symmetric, instantaneous, and applied once per round trip.
- No overnight / weekend gaps matter (BTC trades 24/7, so this is
  benign here).
- The 1,577-bar sample is representative of future regimes (it spans
  one full bull, one bear, and one recovery — but it is still one
  history).

---

## 7. Possible Interview Questions With Answers

### 7.1 Why did you build this

To learn event-driven backtesting end to end and to evaluate a
volatility-triggered reversal strategy on Bitcoin. The project also let
me get hands-on with realistic concerns — lookahead bias, fee
modeling, and the gap between per-trade and per-period Sharpe — that
are easy to get wrong in a notebook-only study. The engine is generic;
the BTC strategy is one application of it.

### 7.2 Walk me through the architecture

`main.py` is the driver: it loads the CSV, builds ATR(14), generates
the five-state signal column via `strat`, writes a working CSV, and
runs `BackTester` twice — once with compounding, once with fixed-stake.
The `BackTester` constructor preprocesses the OHLCV by adding
`next_open`, `next_open_time`, and `nextdatetime` columns.
`get_trades` is the simulation loop: for every bar it reads the signal,
finds the fill price from `next_open`, validates the signal against the
current position via `Position.is_valid`, optionally triggers TP/SL,
and dispatches on the signal value. Closed trades land in `self.trades`
as `TradePair` instances. `get_statistics` then walks `self.trades` to
produce all summary metrics; `make_pnl_graph` and `make_trade_graph`
render Plotly charts of the equity curve and trade regions.

### 7.3 How does your signal work

The strategy looks for volume spikes — bars where volume exceeds the
mean plus 1.5 standard deviations of the last six bars. If we are flat
and a bullish spike candle (close > open) prints, we go long; bearish
spike, we short. Once in a position we set a trailing stop at the
entry close ± 2× ATR(14), ratcheted in our favor as price moves. We
exit if (a) an opposite-direction spike candle prints, which triggers a
reversal (signal ±2), or (b) three consecutive adverse closes happen,
or (c) the trailing stop is breached. Reversals are a single
combined action — close the existing leg and open the opposite side at
the same price.

### 7.4 How did you prevent lookahead bias

Two layers. On the execution side, `preprocess_csv` precomputes the
next candle's open as `next_open`. Every fill in `get_trades` uses that
price, so a signal generated using bar t can only execute at the open
of bar t+1. The final bar's `next_open` is NaN and is skipped. On the
signal side, `main.py` runs a causal re-simulation: for every emitted
signal it re-runs `process_data` and `strat` on the dataframe truncated
up to that bar and verifies the same signal is produced. If a signal
would have been different without future data, the script flags it.
For this strategy the check returns clean.

### 7.5 What do your results mean

In compounding mode the strategy turns $1,000 into $5,872 — a 487%
return — over about 4.3 years, with 104 trades, a 42% win rate, and a
45% maximum drawdown. In fixed-stake mode the return drops to 257%
but the Sharpe rises from 2.26 to 3.60 and the drawdown shrinks to
25%. The buy-and-hold benchmark over the same window is 326%, so
compounding beats it absolutely but with worse drawdown; fixed-stake
underperforms in absolute return but has a much cleaner risk profile.
The headline I would lead with depends on what you care about: peak
nominal return → compounding; risk-adjusted → fixed-stake.

### 7.6 What are the limitations

Listed in detail above. The biggest ones in an interview are:
no slippage model, no per-leg fee accounting (fee is one round-trip
charge), Sharpe is per-trade not per-period, no parameter tuning or
walk-forward validation, single asset, hard-coded $1,000 starting
capital and leverage of 1.

### 7.7 What would you improve

In rough priority:
1. Per-leg fee accounting and a slippage model — both materially
   change the realistic edge.
2. Walk-forward parameter selection (volume window, sigma threshold,
   ATR multiplier) with out-of-sample testing.
3. A standard per-period Sharpe (daily returns of marked-to-market
   equity) reported alongside the per-trade Sharpe.
4. Bar-by-bar (mark-to-market) drawdown to capture intrabar excursions
   of open positions, not just realized equity at close timestamps.
5. Implement TP / SL in the strategy — the engine supports it but the
   strategy doesn't set them.
6. Multi-asset support: portfolio-level position management with
   correlation-aware sizing.
7. A real config file or CLI flags instead of hard-coded constants.
8. Unit tests for `TradePair.pnl`, `Position.is_valid`, the streak
   counter, and the drawdown calculation.

### 7.8 How is this different from a simple moving-average crossover

A MA crossover triggers on the *relationship between two smoothed
prices*, which is slow and tends to fire after a trend has already
matured. This strategy triggers on *volume* — specifically a rolling-
window spike — and uses the candle's direction at the moment of the
spike to choose a side. The exit logic is also different: an MA system
exits when the lines cross back; this one uses an ATR trailing stop
plus a "three adverse closes" stall rule plus an opposite-spike
reversal. Conceptually, MA crossover is a trend-following filter on
price; this is an event-driven filter on volume with a volatility-
scaled exit.

### 7.9 Why BTC data specifically

Three reasons. First, BTC has clean, freely available, long-history
daily OHLCV with no survivorship issues. Second, BTC's volatility
makes volume-spike signatures more visible than in, say, an index
ETF, which is a fair test of a volume-triggered model. Third, the
project came with this dataset as the assignment input, so I stayed
with it to keep the comparison honest. The engine is symbol-agnostic
— it would accept any OHLCV CSV with a `signals` column.

### 7.10 How would this scale to multiple assets

In its current form it would not — `BackTester` holds a single
`Position` and a single `trades` list. To scale, I would:
1. Replace `Position` with a `dict[symbol -> Position]`.
2. Run signal generation per symbol; aggregate into a single signal
   stream keyed by `(symbol, timestamp)`.
3. Add portfolio-level sizing — a per-symbol cap as a fraction of
   total equity, with an overall gross-exposure cap.
4. Compute a portfolio equity curve from per-symbol PnL streams, with
   correlations folded into a real per-period Sharpe.
5. Decide rebalance cadence and add a cash account that handles when
   total stake exceeds available capital.

### 7.11 Why two position-sizing modes

To separate two questions. Compounding answers "what would an account
that reinvests profits look like?" — the realistic deployment view.
Fixed-stake answers "is the underlying edge real?" — by removing the
path-dependent variance compounding introduces, the Sharpe estimate
becomes much cleaner. Reporting both makes the trade-off explicit
rather than picking the one number that flatters the strategy.

### 7.12 What's wrong with the Sharpe number you're reporting

It is per-trade, not per-period. Each sample is one trade's dollar PnL
divided by the trade's entry price, and the annualization assumes 365
trade-equivalent periods per year. A textbook Sharpe would resample
equity into uniform periods (daily, say) and use those returns. The
per-trade Sharpe is reasonable for ranking strategies of similar trade
frequency, but it is not directly comparable to industry figures.

### 7.13 What does the equity curve actually show

`make_pnl_graph` plots `self.data["capital"] = 1000 + cumsum(pnl)`
against time. The pnl column is filled by `calc_pnl` which, while a
trade is open, accrues `qty * (close_t - close_{t-1}) / init_price`
per bar and charges the fee on the closing bar. So it is a daily
mark-to-market view of equity during open positions, flat while
between trades. Close price is overlaid on a secondary y-axis for
context.

### 7.14 What if the strategy works because of one lucky trade

The largest single winning trade in compounding mode is +$1,925
(against a starting stake of $1,000); the largest loss is -$930. There
are 104 trades. The winning streak peaks at 8, losing streak at 9.
Removing the top winner would knock about 40% off net profit but the
strategy would still beat buy-and-hold in compounding mode. This is
something a more rigorous analysis would test — for example, a
bootstrap of trade outcomes — but the engine does not currently do
that.

### 7.15 Did you write the backtester from scratch

Honest answer: `backtester.py` was provided as program scaffolding for
the SoQ project — the bottom of the file references `results_kush.csv`
which is another contributor's filename, and the engine has many
generic features (`get_granular_sharpe_ratio_window`,
`make_pnl_graph`) the strategy never exercises. The strategy code in
`main.py` (volume-spike + ATR trailing-stop logic) and the analysis
notebooks under `analysis/` are mine. I extended the engine to fix the
execution-side lookahead-bias issue (next-bar-open fills) and to make
both compounding and fixed-stake first-class modes in the driver.
Saying you wrote everything when half of it was given is the kind of
thing interviewers catch quickly.

### 7.16 Walk me through `Position.is_valid`

If `qty == 0` (flat), any signal in `{-1, 0, 1}` is valid. Signals
`±2` are reversal signals and require an existing open position, so
they are rejected when flat. If a position exists,
`sign(qty) * sign(signal) <= 0` enforces that the incoming signal must
be opposite-sign (close or reverse) or zero (hold) — you cannot stack
two longs.

### 7.17 What happens on the last bar of the dataset

`preprocess_csv` shifts `open` and `datetime` by -1 to make
`next_open` and `next_open_time`, so the very last bar has NaN for
both. In `get_trades` we explicitly `if pd.isna(fill_price): continue`,
so the last bar never trades. If a position is open going into the
last bar it remains open and is not closed in `self.trades`. The
statistics functions only iterate `self.trades`, so the open position
is not reflected in metrics. `make_trade_graph` does draw a shaded
region for it, however.

### 7.18 If TP/SL is supported, why don't you use it?

The strategy in `main.py` doesn't set the `TP` or `SL` columns. The
engine accommodates them — `check_tp_sl` iterates the intrabar window
and triggers a close at the TP or SL price if hit — but the strategy
relies on the ATR trailing stop and the three-bar stall rule instead.
Adding a hard TP/SL is on the improvements list.

### 7.19 What is `num_wrong` doing in the strategy?

It counts consecutive adverse closes against the current direction.
For a long, "adverse" means `close[i] <= close[i-1]`. When it reaches
3, the strategy emits a close signal even if the trailing stop hasn't
been breached — it is a stall guard for sideways or slowly-deteriorating
price action that wouldn't otherwise trigger an exit. Any non-adverse
close resets it to 0.

### 7.20 Why ATR for the stop and not a fixed percent

ATR adapts to current volatility. A fixed-percent stop is either too
tight in a high-volatility regime (stopped out by normal noise) or
too loose in a low-volatility regime (gives back too much before
exiting). ATR(14) × 2 produces a stop that is wide when the market is
choppy and tight when it is calm — which matches the assumption that
true reversals look different from regime noise.

### 7.21 What did the Markov and Poisson notebooks teach you

The Markov regime notebook fits a 3-state first-order chain on BTC
daily log-returns (down / flat / up, where the threshold is a rolling
30-day stdev) and reads the transition matrix and stationary
distribution. The Poisson notebook treats trade open-timestamps as a
point process, fits the MLE rate `λ̂ = N / T`, and KS-tests the
inter-arrival times against an exponential model. The expectation —
which the data supports — is that the gaps deviate from a pure Poisson
process because the volume-spike trigger is itself volatility-clustered.
Both notebooks are honest exploratory pieces, not predictive models
folded into the trading logic.

### 7.22 Your Sharpe is 3.60 in fixed-stake but only 2.26 in compounding — why

**One-sentence answer:** compounding amplifies the variance of trade-
level returns because the stake itself grows and shrinks with realized
PnL, so each trade's dollar PnL is no longer drawn from a stationary
distribution — fixed-stake holds the stake constant, which isolates the
underlying signal quality.

In fixed-stake every trade is sized on the same $1,000, so each trade's
dollar PnL depends only on the percentage move and the entry price.
The standard deviation in the denominator of Sharpe measures pure
signal noise.

In compounding the stake grows after wins and shrinks after losses.
During a winning streak later wins are bigger in dollar terms; during
a losing streak later losses are bigger too. That path-dependent
amplification inflates the standard deviation of per-trade dollar PnL
much faster than it inflates the mean, so Sharpe = mean / std drops.

You can see the asymmetric tail inflation in the numbers:

| Metric | Compounding | Fixed-Stake | Ratio (C/F) |
|---|---:|---:|---:|
| Largest win | $1,925 | $455 | ~4.2x |
| Largest loss | -$930 | -$258 | ~3.6x |
| Net profit | $4,873 | $2,570 | ~1.9x |
| Max drawdown | 45.5% | 25.2% | ~1.8x |
| Sharpe | 2.26 | 3.60 | ~0.63 |

Tail trades are ~4x larger in compounding but net profit is only ~2x.
The PnL distribution gets fatter in both tails, and Sharpe drops.

**Why both numbers matter, not just one:**
- Fixed-stake Sharpe is the cleaner measure of the strategy's edge —
  it answers "is the signal good?"
- Compounding Sharpe is what a real account would experience because
  no one trades a fixed stake forever — profits are reinvested.

**Extra depth** if asked: the Sharpe in this codebase is per-trade
(one sample = one closed trade's PnL / entry price), not per-period.
Compounding makes the i.i.d. assumption worse still because successive
trade returns are correlated through the stake. A standard per-period
Sharpe on daily equity changes is the more defensible number for
outside comparison.

### 7.23 You beat buy-and-hold on Sharpe but not on raw returns — is this strategy actually useful

**First, correct the premise — that framing only applies to fixed-stake.**

| | Buy-and-Hold | Compounding | Fixed-Stake |
|---|---:|---:|---:|
| Return | +325.63% | **+487.26%** | +257.01% |
| Max drawdown | ~80% (BTC 2021-2022) | **45.51%** | **25.18%** |

Compounding mode beats buy-and-hold on raw return AND drawdown.
Fixed-stake underperforms on raw return but has a far smaller
drawdown. So the right reply opens with: "actually compounding beats
buy-and-hold on raw return too — 487% vs 326% — and on drawdown. The
fixed-stake comparison is the interesting one."

**Then answer the real question — is fixed-stake worth it despite
trailing buy-and-hold on raw return?**

Yes. Buy-and-hold over 2019-2024 required sitting through the 2022
crash where BTC fell ~77% peak-to-trough. A real investor with $1,000
watching it drop to $230 has a high probability of capitulating before
the recovery — the gap between simulated buy-and-hold and *realized*
buy-and-hold is huge. Fixed-stake has a 25% max drawdown on the same
data; it is a fundamentally different product.

Whether 257% with 25% MDD beats 326% with ~80% MDD depends on:

1. **Risk tolerance.** A pension fund would take 257%/25% over 326%/80%
   every time. A retail YOLO trader would not.
2. **Whether you can leverage.** Sharpe 3.60 with 25% drawdown can be
   levered ~2x to match buy-and-hold's return with a smaller drawdown.
   Sharpe tells you the strategy deserves leverage; raw return does
   not. (Note: the engine reports `Leverage Applied: 1` — it does not
   simulate leverage. This is what you'd do downstream.)
3. **Path-dependence.** Buy-and-hold's +326% requires holding through
   the 2022 crash without flinching. The strategy's +257% does not.
   Drawdown isn't an abstract metric — it's the thing that makes
   people sell at the bottom.

**Punchline:** risk-adjusted return is the right metric here. Anyone
can match buy-and-hold's raw return by levering a higher-Sharpe
strategy; almost no one can sit through buy-and-hold's drawdown.
Fixed-stake at Sharpe 3.60 is a strategy you can scale; buy-and-hold
at Sharpe ~1 is not. And compounding beats buy-and-hold on both axes
anyway.

**Framing to memorize:** Sharpe tells you the *quality* of the signal;
returns tell you *what was earned*; drawdown tells you *what you had
to endure*. Senior interviewers want all three discussed, not just
whichever flatters the strategy.

### 7.24 Your win rate is only 42% — how is this strategy profitable

**One-sentence answer:** the strategy is profitable because winning
trades are materially larger than losing trades — that's positive
expectancy, and the Sharpe of 3.60 (fixed-stake) confirms the edge is
real, not noise.

**Walk through the math from the actual numbers (fixed-stake mode):**

| Component | Value |
|---|---:|
| Win rate | 42.31% (44 wins / 60 losses out of 104) |
| Average win | +$141.65 |
| Average loss | -$61.04 |
| Win/loss ratio | ~2.32x |
| Expectancy per trade | 0.4231 * 141.65 + 0.5769 * (-61.04) = **+$24.71** |

Expected dollar PnL per trade is positive even though more than half
the trades lose. Over 104 trades that compounds to +$2,570 net profit
on $1,000 starting capital. The math directly matches what the engine
reports as "Average Profit" ($24.71).

**Why this profile is expected, not a red flag.** The strategy is a
trend / breakout system with an ATR trailing stop and a 3-bar stall
exit. Trend-following systems are structurally low-win-rate, high-
payoff: most signals fire on noise that quickly stalls and stops out
at the trailing stop for a small loss, and a minority catch a real
trend and run for several multiples of the typical loss. A 40-50%
win rate with a ~2x win/loss ratio is the textbook signature of this
kind of system — what would be suspicious is a 70% win rate with a
1:1 ratio (often a sign of curve-fit mean-reversion or hidden tail
risk).

**Why Sharpe corroborates this.** Win rate alone is useless — a coin
flip that pays 1.01 on heads and 1.00 on tails has 50% win rate and
positive expectancy. Sharpe rolls expectancy and dispersion together.
A 3.60 per-trade Sharpe says the mean per-trade return is 3.6 standard
deviations above zero (annualized) — the edge is statistically
distinguishable from noise even though most individual trades lose.

**Numbers to keep in your head for this question:**
- 42.31% win rate, 44 wins / 60 losses, 104 trades total.
- Average win $141.65, average loss $61.04 (~2.32x ratio, fixed-stake).
- Expectancy per trade ≈ +$24.71. Over 104 trades → +$2,570 net.
- Largest single win $454.57, largest single loss $257.78 — also a
  ~1.76x ratio, so the asymmetry isn't driven by one fluke trade.

**Punchline:** win rate is a vanity metric on its own. What matters
is expectancy = P(win) * avg_win - P(loss) * avg_loss. Here it's
positive and big enough to register as Sharpe 3.60. A higher win rate
with a smaller ratio would arithmetic-out to the same expectancy and
the same Sharpe.

### 7.25 If we asked you to live-trade this tomorrow, what would you say

I would not. The simulation assumes zero slippage, next-open fills
that I cannot guarantee in practice, and the fee model under-charges
versus reality. Sharpe is per-trade and overstated relative to the
common per-period definition. Before any capital, I would want: a
per-leg fee model with slippage, a proper out-of-sample walk-forward
on the hyperparameters, bar-by-bar drawdown on open positions, and a
small live paper-trading run for at least one calendar month to
calibrate the gap between simulated and realized fills.

---

## 8. Quick numbers cheat-sheet

- 1,577 candles, daily, 2019-09-08 to 2024-01-01.
- Starting capital: $1,000.
- Fee: 0.15% (`transaction_fee = 0.0015`), applied once per trade.
- ATR length: 14. ATR multiplier: 2.
- Volume window: 6 bars. Volume threshold: mean + 1.5 σ.
- Stall rule: 3 consecutive adverse closes → close.
- Compounding result: 104 trades, 42.31% win, Sharpe 2.26, MDD 45.51%, +487%.
- Fixed-stake result: 104 trades, 42.31% win, Sharpe 3.60, MDD 25.18%, +257%.
- Buy-and-hold benchmark: +325.63%.
