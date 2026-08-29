"""
Metric aggregation helpers.
Pulls values out of the financial_metrics EAV table and computes
derived quantities (latest value, growth rates, CAGR) that the
screener and scoring engine build on top of.
"""
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import FinancialMetric, Company

# Canonical metric name -> list of known yfinance metric_name variants,
# tried in priority order. yfinance naming isn't perfectly consistent
# across companies/sectors, so we check alternatives.
METRIC_ALIASES = {
    "revenue": ["total_revenue", "totalrevenue", "operating_revenue"],
    "net_income": ["net_income", "net_income_common_stockholders"],
    "total_assets": ["total_assets"],
    "total_equity": ["stockholders_equity", "total_equity_gross_minority_interest"],
    "total_debt": ["total_debt"],
    "operating_cash_flow": ["operating_cash_flow", "cash_flow_from_continuing_operating_activities"],
    "free_cash_flow": ["free_cash_flow"],
    "ebitda": ["ebitda", "normalized_ebitda"],
    "ebit": ["ebit"],
    "gross_profit": ["gross_profit"],
    "interest_expense": ["interest_expense"],
    "current_assets": ["current_assets"],
    "current_liabilities": ["current_liabilities"],
    "pretax_income": ["pretax_income"],
    "tax_provision": ["tax_provision"],
}


def get_latest_metric(
    session: Session, company_id: int, canonical_name: str, period_type: str = "annual"
) -> dict | None:
    """
    Returns the most recent value for a canonical metric name, trying
    known aliases in order. Returns None if nothing found (missing data
    is surfaced, never guessed).
    """
    aliases = METRIC_ALIASES.get(canonical_name, [canonical_name])

    for alias in aliases:
        stmt = (
            select(FinancialMetric)
            .where(
                FinancialMetric.company_id == company_id,
                FinancialMetric.metric_name == alias,
                FinancialMetric.period_type == period_type,
                FinancialMetric.is_missing == False,  # noqa: E712
            )
            .order_by(FinancialMetric.period_end_date.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is not None:
            return {
                "value": row.value,
                "unit": row.unit,
                "period_end_date": row.period_end_date,
                "data_quality_status": row.data_quality_status,
                "metric_name_used": alias,
            }
    return None


def get_latest_metrics_bulk(session: Session, company_id: int, period_type: str = "annual") -> dict:
    """
    Fetches the latest value for every canonical metric in one pass —
    one DB query instead of one query per metric. Used by profile
    builders that need many metrics at once (screener, scoring), which
    otherwise triggers dozens of round trips per company.
    Returns {canonical_name: value_or_None}.
    """
    stmt = (
        select(FinancialMetric)
        .where(
            FinancialMetric.company_id == company_id,
            FinancialMetric.period_type == period_type,
            FinancialMetric.is_missing == False,  # noqa: E712
        )
    )
    rows = session.execute(stmt).scalars().all()

    # Index by metric_name -> most recent row for that name
    latest_by_name = {}
    for row in rows:
        existing = latest_by_name.get(row.metric_name)
        if existing is None or row.period_end_date > existing.period_end_date:
            latest_by_name[row.metric_name] = row

    # Resolve each canonical name via its alias list against the index
    result = {}
    for canonical, aliases in METRIC_ALIASES.items():
        value = None
        for alias in aliases:
            if alias in latest_by_name:
                value = latest_by_name[alias].value
                break
        result[canonical] = value
    return result


def get_metric_series(
    session: Session, company_id: int, canonical_name: str, period_type: str = "annual", limit: int = 5
) -> list[dict]:
    """
    Returns up to `limit` most recent periods for a metric, oldest to newest.
    Used for CAGR / growth-trend calculations.
    """
    aliases = METRIC_ALIASES.get(canonical_name, [canonical_name])

    for alias in aliases:
        stmt = (
            select(FinancialMetric)
            .where(
                FinancialMetric.company_id == company_id,
                FinancialMetric.metric_name == alias,
                FinancialMetric.period_type == period_type,
                FinancialMetric.is_missing == False,  # noqa: E712
            )
            .order_by(FinancialMetric.period_end_date.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        if rows:
            series = [
                {"period_end_date": r.period_end_date, "value": r.value, "unit": r.unit}
                for r in rows
            ]
            series.reverse()  # oldest first
            return series
    return []


def calculate_cagr(start_value: float, end_value: float, years: float) -> float | None:
    """
    Compound Annual Growth Rate. Returns None for invalid inputs
    (e.g. negative start value, zero years) rather than raising or
    silently returning a misleading number.
    """
    if start_value is None or end_value is None:
        return None
    if start_value <= 0 or years <= 0:
        return None
    return (end_value / start_value) ** (1 / years) - 1


def calculate_metric_cagr(
    session: Session, company_id: int, canonical_name: str, period_type: str = "annual", years: int = 3
) -> float | None:
    """
    Convenience wrapper: fetches the metric series and computes CAGR
    across the requested number of years using the earliest and latest
    available points within that window.
    """
    series = get_metric_series(session, company_id, canonical_name, period_type, limit=years + 1)
    if len(series) < 2:
        return None

    start = series[0]
    end = series[-1]
    span_years = (end["period_end_date"] - start["period_end_date"]).days / 365.25
    return calculate_cagr(start["value"], end["value"], span_years)


def calculate_yoy_growth(
    session: Session, company_id: int, canonical_name: str, period_type: str = "annual"
) -> float | None:
    """Latest year-over-year growth rate for a metric."""
    series = get_metric_series(session, company_id, canonical_name, period_type, limit=2)
    if len(series) < 2:
        return None
    prev, latest = series[0]["value"], series[-1]["value"]
    if prev == 0:
        return None
    return (latest - prev) / abs(prev)


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found — run scripts/load_company.py first")
    else:
        print(f"Company: {company.name} (id={company.id})\n")

        for metric in ["revenue", "net_income", "total_assets", "total_equity", "operating_cash_flow"]:
            latest = get_latest_metric(session, company.id, metric)
            print(f"{metric}: {latest}")

        print()
        revenue_cagr = calculate_metric_cagr(session, company.id, "revenue", years=3)
        print(f"3-year revenue CAGR: {revenue_cagr}")

        revenue_yoy = calculate_yoy_growth(session, company.id, "revenue")
        print(f"Latest revenue YoY growth: {revenue_yoy}")

        print("\nBulk metrics fetch:")
        bulk = get_latest_metrics_bulk(session, company.id)
        for k, v in bulk.items():
            print(f"  {k}: {v}")

    session.close()