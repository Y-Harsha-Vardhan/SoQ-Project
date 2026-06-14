"""Driver: build indicators, generate signals, and run the backtester
in both compounding and fixed-stake modes.

Strategy: volume-spike entry + ATR(14) trailing-stop reversal.
Emits the five-state signal protocol consumed by `BackTester`:
    0  HOLD
    1  open long  / close short
   -1  open short / close long
    2  reverse short -> long
   -2  reverse long  -> short
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
from backtester import BackTester


def process_data(data):
    """Append engineered indicators used by `strat`.

    Currently: ATR(14) via pandas_ta. The rolling 6-bar volume threshold
    used for entry triggers is computed inline inside `strat`.
    """
    data = data.copy()
    data['ATR'] = ta.atr(data['high'], data['low'], data['close'], length=14)
    return data


def strat(data):
    """Generate the `signals` column from volume spikes and ATR trailing
    stops.

    Entry: when current-bar volume exceeds (mean+1.5*std) of the trailing
    6-bar window AND the bar is directional (close vs open).
    Exit / reverse: trailing stop at close +/- 2*ATR, or 3 consecutive
    adverse closes, or an opposite volume-spike candle.

    All decisions for bar i use only information from bars [0..i] -- no
    forward leakage. The fill itself is delayed to bar i+1's open by the
    BackTester (see backtester.preprocess_csv).
    """
    data['trade_type'] = "HOLD"
    data['signals'] = 0
    position = 0
    num_wrong = 0
    trailing_stop = 0
    trailing_stop_multiplier = 2

    for i in range(14, len(data)):
        # Rolling 6-bar volume threshold (mean + 1.5*std).
        vol_spike = np.mean(data.loc[i-5:i, 'volume']) + 1.5 * np.std(data.loc[i-5:i, 'volume'])

        if position == 0:
            # Flat -> look for a volume-spike entry in either direction.
            if data.loc[i, 'volume'] > vol_spike:
                if data.loc[i, 'close'] > data.loc[i, 'open']:
                    data.loc[i, 'signals'] = 1
                    position = 1
                    data.loc[i, 'trade_type'] = "LONG"
                    trailing_stop = data.loc[i, 'close'] - data.loc[i, 'ATR'] * trailing_stop_multiplier

                elif data.loc[i, 'close'] < data.loc[i, 'open']:
                    data.loc[i, 'signals'] = -1
                    position = -1
                    data.loc[i, 'trade_type'] = "SHORT"
                    trailing_stop = data.loc[i, 'close'] + data.loc[i, 'ATR'] * trailing_stop_multiplier

        elif position == 1:
            # Long -> watch for reversal, stop-out, or stall.
            trend_rev = data.loc[i, 'volume'] >= vol_spike and data.loc[i, 'close'] < data.loc[i, 'open']
            if data.loc[i, 'close'] <= data.loc[i-1, 'close']:
                num_wrong += 1
            else:
                num_wrong = 0

            if trend_rev:
                data.loc[i, 'signals'] = -2
                position = -1
                trailing_stop = data.loc[i, 'close'] + data.loc[i, 'ATR'] * trailing_stop_multiplier
                num_wrong = 0
                data.loc[i, 'trade_type'] = "REVERSE_LONG_TO_SHORT"
            elif num_wrong == 3 or data.loc[i, 'close'] < trailing_stop:
                data.loc[i, 'signals'] = -1
                position = 0
                data.loc[i, 'trade_type'] = "CLOSE"
            else:
                # Ratchet the trailing stop upward.
                trailing_stop = max(trailing_stop, data.loc[i, 'close'] - data.loc[i, 'ATR'] * trailing_stop_multiplier)

        elif position == -1:
            # Short -> mirror image of the long branch.
            trend_rev = data.loc[i, 'volume'] >= vol_spike and data.loc[i, 'close'] > data.loc[i, 'open']
            if data.loc[i, 'close'] >= data.loc[i - 1, 'close']:
                num_wrong += 1
            else:
                num_wrong = 0

            if trend_rev:
                data.loc[i, 'signals'] = 2
                position = 1
                trailing_stop = data.loc[i, 'close'] - data.loc[i, 'ATR'] * trailing_stop_multiplier
                num_wrong = 0
                data.loc[i, 'trade_type'] = "REVERSE_SHORT_TO_LONG"
            elif num_wrong == 3 or data.loc[i, 'close'] > trailing_stop:
                data.loc[i, 'signals'] = 1
                position = 0
                data.loc[i, 'trade_type'] = "CLOSE"
            else:
                trailing_stop = min(trailing_stop, data.loc[i, 'close'] + data.loc[i, 'ATR'] * trailing_stop_multiplier)

    return data


def main():
    data = pd.read_csv("BTC_2019_2023_1d.csv")
    processed_data = process_data(data)
    result_data = strat(processed_data)
    result_data.to_csv("updated_final_data.csv", index=False)

    # Demonstrate BOTH position-sizing modes the engine supports.
    # compound_flag=1 -> realized PnL grows the stake (compounding).
    # compound_flag=0 -> every trade sized on the initial $1000 (fixed).
    for mode_name, flag in [("Compounding", 1), ("Fixed-Stake", 0)]:
        bt = BackTester(
            "BTC",
            signal_data_path="updated_final_data.csv",
            master_file_path="updated_final_data.csv",
            compound_flag=flag,
        )
        bt.get_trades(1000)

        print(f"\n===== {mode_name} (start = $1000) =====")
        stats = bt.get_statistics()
        for key, val in stats.items():
            print(f"  {key}: {val}")

        # Print individual trades only for the compounding run to keep
        # output compact.
        if flag == 1:
            print("\n  --- Trades ---")
            for trade in bt.trades:
                print(f"  {trade}  | PnL: {trade.pnl():.2f}")

    # ------------------------------------------------------------------
    # Signal-side lookahead-bias guard.
    # For every emitted signal we re-run process_data + strat on data
    # truncated up to and including that bar; if the same signal is
    # produced, the signal depends only on information available at the
    # decision time. (The execution-side guard lives in
    # backtester.preprocess_csv via next_open / next_open_time.)
    # ------------------------------------------------------------------
    print("\nChecking for signal-side lookahead bias...")
    lookahead_bias = False
    for i in range(len(result_data)):
        if result_data.loc[i, 'signals'] != 0:
            temp_data = data.iloc[:i+1].copy()
            temp_data = process_data(temp_data)
            temp_data = strat(temp_data)
            if temp_data.loc[i, 'signals'] != result_data.loc[i, 'signals']:
                print(f"Lookahead bias detected at index {i}")
                lookahead_bias = True

    if not lookahead_bias:
        print("No lookahead bias detected.")

    # Equity curve + trade overlay (Plotly). `bt` is the fixed-stake
    # instance from the last loop iteration; plot it for visualization.
    bt.make_trade_graph()
    bt.make_pnl_graph()


if __name__ == "__main__":
    main()
