import pandas as pd
import numpy as np
# import talib as tb
import pandas_ta as ta
from backtester import BackTester

# Data Preprocessing Function
def process_data(data):
    """
    Process the input data and return a dataframe with all the necessary indicators and data for making signalss.

    Parameters:
    data (pandas.DataFrame): The input data to be processed.

    Returns:
    pandas.DataFrame: The processed dataframe with all the necessary indicators and data.
    """
    # Genereate the necessary indicators here
    data = data.copy()
    data['ATR'] = ta.atr(data['high'], data['low'], data['close'], length = 14)
    return data

# Strategy Logic Function
def strat(data):
    """
    Create a strategy based on indicators or other factors.

    Parameters:
    - data: DataFrame
        The input data containing the necessary columns for strategy creation.

    Returns:
    - DataFrame
        The modified input data with an additional 'signals' column representing the strategy signals.
    """
    data['trade_type'] = "HOLD" 
    data['signals'] = 0
    position = 0 
    num_wrong = 0
    trailing_stop = 0
    trailing_stop_multiplier = 2

    for i in range(14, len(data)):
        vol_spike = np.mean(data.loc[i-5:i, 'volume']) + 1.5 * np.std(data.loc[i-5:i, 'volume'])

        if position == 0:
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
                trailing_stop = max(trailing_stop, data.loc[i, 'close'] - data.loc[i, 'ATR'] * trailing_stop_multiplier)

        elif position == -1:
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


# Main Function
def main():
    data = pd.read_csv("BTC_2019_2023_1d.csv")
    processed_data = process_data(data) # process the data
    result_data = strat(processed_data) # Apply the strategy
    csv_file_path = "updated_final_data.csv" 
    result_data.to_csv(csv_file_path, index=False)

    bt = BackTester("BTC", signal_data_path="updated_final_data.csv", master_file_path="updated_final_data.csv", compound_flag=1)
    bt.get_trades(1000)

    # print trades and their PnL
    print("\n ***=== Trades & PnL ===***")
    for trade in bt.trades: 
        print(trade)
        print("PnL:", trade.pnl())

    # Print results
    print("\n ***=== Statistics ===***")
    stats = bt.get_statistics()
    for key, val in stats.items():
        print(key, ":", val)


    #Check for lookahead bias
    print("Checking for lookahead bias...")
    lookahead_bias = False
    for i in range(len(result_data)):
        if result_data.loc[i, 'signals'] != 0:  # If there's a signal
            temp_data = data.iloc[:i+1].copy()  # Take data only up to that point
            temp_data = process_data(temp_data) # process the data
            temp_data = strat(temp_data) # Re-run strategy
            if temp_data.loc[i, 'signals'] != result_data.loc[i, 'signals']:
                print(f"Lookahead bias detected at index {i}")
                lookahead_bias = True

    if not lookahead_bias:
        print("No lookahead bias detected.")

    # Generate the PnL graph
    bt.make_trade_graph()
    bt.make_pnl_graph()
    
if __name__ == "__main__":
    main()