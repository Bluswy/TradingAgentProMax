import time
from tradingagents.dataflows.tushare_provider import get_tushare_indicator

print("Testing optimized implementation with 30-day lookback:")
start_time = time.time()
result = get_tushare_indicator("600519.SH", "macd", "2024-11-01", 30)
end_time = time.time()

print(f"Execution time: {end_time - start_time:.2f} seconds")
print(f"Result length: {len(result)} characters")
print(result)
