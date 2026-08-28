"""
Loads a single company's data (info, financials, prices) from yfinance
into the Supabase database. Usage: python -m scripts.load_company RELIANCE.NS

Uses bulk delete-then-insert per company for speed (fine for a research
tool refreshing one company at a time; not meant for massive concurrent loads).
"""
import sys
from app.data.db import SessionLocal
from app.data.models import Company, FinancialMetric, PriceHistory
from app.data.providers.yfinance_provider import (
    fetch_company_info, fetch_price_history, fetch_financial_metrics
)


def get_or_create_company(session, info: dict) -> Company:
    company = session.query(Company).filter_by(ticker=info["ticker"]).first()
    if company:
        company.name = info["name"]
        company.sector = info["sector"]
        company.industry = info["industry"]
        company.isin = info["isin"]
    else:
        company = Company(
            ticker=info["ticker"],
            name=info["name"],
            sector=info["sector"],
            industry=info["industry"],
            isin=info["isin"],
        )
        session.add(company)
    session.flush()  # get company.id without full commit
    return company


def load_company(ticker: str):
    session = SessionLocal()
    try:
        print(f"Fetching {ticker} from yfinance...")
        info = fetch_company_info(ticker)
        prices = fetch_price_history(ticker, period="5y")
        metrics = fetch_financial_metrics(ticker)
        print(f"Fetched: {len(metrics)} metrics, {len(prices)} price records. Loading into DB...")

        company = get_or_create_company(session, info)

        # Clear existing rows for this company, then bulk-insert fresh —
        # far faster than checking each row individually for a full refresh.
        session.query(FinancialMetric).filter_by(company_id=company.id).delete()
        session.query(PriceHistory).filter_by(company_id=company.id).delete()

        session.bulk_insert_mappings(FinancialMetric, [
            {
                "company_id": company.id,
                "metric_name": m["metric_name"],
                "statement_type": m["statement_type"],
                "period_type": m["period_type"],
                "period_end_date": m["period_end_date"],
                "value": m["value"],
                "unit": m["unit"],
                "source": m["source"],
            }
            for m in metrics
        ])

        session.bulk_insert_mappings(PriceHistory, [
            {
                "company_id": company.id,
                "trade_date": p["trade_date"],
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "volume": p["volume"],
            }
            for p in prices
        ])

        session.commit()
        print(f"Loaded {ticker}: {len(metrics)} metrics, {len(prices)} price records "
              f"(company id={company.id})")
    except Exception as e:
        session.rollback()
        print(f"Failed to load {ticker}: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    load_company(ticker)