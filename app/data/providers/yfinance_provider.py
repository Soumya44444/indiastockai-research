"""
yfinance-based data provider.
Fetches company info, financials, and price history; normalizes into
our audit-friendly format before it reaches the validation layer.
"""
from datetime import date, datetime
import yfinance as yf


def fetch_company_info(ticker: str) -> dict:
    """Basic company metadata."""
    t = yf.Ticker(ticker)
    info = t.info
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "isin": info.get("isin"),
    }


def fetch_market_data(ticker: str) -> dict:
    """
    Live market data needed for valuation (P/E, EV/EBITDA, P/B, DDM, price
    targets). Fetched fresh rather than stored historically — current
    price/shares outstanding/dividends are point-in-time snapshots, not
    audited financial statements.
    """
    t = yf.Ticker(ticker)
    info = t.info
    return {
        "ticker": ticker,
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": info.get("marketCap"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "enterprise_value": info.get("enterpriseValue"),
        "beta": info.get("beta"),
        "dividend_rate": info.get("dividendRate"),
        "payout_ratio": info.get("payoutRatio"),
    }


def fetch_business_profile(ticker: str) -> dict:
    """
    Descriptive business/industry metadata (project spec Section 7).
    Fetched live rather than stored — this is qualitative context, not
    an auditable financial figure, so it doesn't need the EAV treatment.
    """
    t = yf.Ticker(ticker)
    info = t.info
    return {
        "ticker": ticker,
        "business_summary": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "website": info.get("website"),
        "full_time_employees": info.get("fullTimeEmployees"),
        "city": info.get("city"),
    }


def fetch_price_history(ticker: str, period: str = "5y") -> list[dict]:
    """OHLCV price history, normalized to list of dicts."""
    t = yf.Ticker(ticker)
    hist = t.history(period=period)
    records = []
    for idx, row in hist.iterrows():
        records.append({
            "trade_date": idx.date(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })
    return records


def fetch_financial_metrics(ticker: str) -> list[dict]:
    """
    Pulls annual + quarterly income statement, balance sheet, and cash flow.
    Returns a flat list of metric records ready for the validation layer.
    Skips NaN/None values so nothing invalid reaches the database.
    """
    t = yf.Ticker(ticker)
    records = []

    sources = [
        ("income", "annual", t.financials),
        ("income", "quarterly", t.quarterly_financials),
        ("balance", "annual", t.balance_sheet),
        ("balance", "quarterly", t.quarterly_balance_sheet),
        ("cashflow", "annual", t.cashflow),
        ("cashflow", "quarterly", t.quarterly_cashflow),
    ]

    for statement_type, period_type, df in sources:
        if df is None or df.empty:
            continue
        for metric_name in df.index:
            for period_end, value in df.loc[metric_name].items():
                if value is None:
                    continue
                if value != value:  # NaN check (NaN != NaN is always True)
                    continue
                try:
                    period_end_date = period_end.date() if hasattr(period_end, "date") else period_end
                    records.append({
                        "metric_name": str(metric_name).strip().lower().replace(" ", "_"),
                        "statement_type": statement_type,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                        "value": float(value),
                        "unit": "INR" if ticker.endswith(".NS") or ticker.endswith(".BO") else "USD",
                        "source": "yfinance",
                    })
                except (ValueError, TypeError):
                    continue

    return records


if __name__ == "__main__":
    ticker = "RELIANCE.NS"
    info = fetch_company_info(ticker)
    print("Company info:", info)

    prices = fetch_price_history(ticker, period="5d")
    print(f"\nPrice history (last 5 days): {len(prices)} records")
    for p in prices[:3]:
        print(" ", p)

    metrics = fetch_financial_metrics(ticker)
    print(f"\nFinancial metrics: {len(metrics)} records")
    for m in metrics[:5]:
        print(" ", m)

    business = fetch_business_profile(ticker)
    print(f"\nBusiness profile: {business['country']}, {business['city']}, "
          f"{business['full_time_employees']} employees")