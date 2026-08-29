"""
Batch-loads all Nifty 50 companies into the database.
Continues past individual failures and reports a summary at the end.
Usage: python -m scripts.load_nifty50
"""
import time
from app.data.nifty50_tickers import NIFTY_50_TICKERS
from scripts.load_company import load_company


def main():
    succeeded = []
    failed = []

    for i, ticker in enumerate(NIFTY_50_TICKERS, start=1):
        print(f"\n[{i}/{len(NIFTY_50_TICKERS)}] {ticker}")
        try:
            load_company(ticker)
            succeeded.append(ticker)
        except Exception as e:
            print(f"  ERROR loading {ticker}: {e}")
            failed.append(ticker)
        time.sleep(1)  # be polite to yfinance, avoid rate limiting

    print("\n" + "=" * 50)
    print(f"Batch complete: {len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print("Failed tickers:", failed)


if __name__ == "__main__":
    main()