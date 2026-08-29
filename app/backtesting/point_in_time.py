"""
Point-in-time fundamental snapshot builder (project spec Section 17:
backtesting must guard against look-ahead bias and ignoring publication
dates of financials).

KNOWN LIMITATION (disclosed): our data source (yfinance) does not provide
real disclosure/publication dates — only period_end_date (the fiscal
period covered). We approximate publication timing with a conservative
ASSUMED_REPORTING_LAG_DAYS, standing in for the real-world gap between
a fiscal period ending and results actually being disclosed to the
market. This is a genuine methodological compromise, not a true
point-in-time database — flagged explicitly in every backtest output.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import FinancialMetric, Company

# Conservative assumed lag between fiscal period-end and public
# disclosure, by period type. Real Indian-market disclosure norms are
# roughly 45 days (quarterly) / 60 days (annual, per SEBI LODR outer
# limits) — we use the same or slightly wider margins to stay conservative
# (better to assume data arrives LATE than to leak future information).
ASSUMED_REPORTING_LAG_DAYS = {
    "quarterly": 45,
    "annual": 60,
}


def get_metrics_as_of(session: Session, company_id: int, as_of_date: date,
                       period_type: str = "quarterly") -> dict:
    """
    Returns the latest metrics that would have been PUBLICLY KNOWN as of
    as_of_date — i.e. only metrics whose (period_end_date + assumed lag)
    is on or before as_of_date. This is the core look-ahead-bias guard:
    a backtest rebalancing on date X must never see data that wasn't
    actually available to a real investor on date X.
    """
    lag_days = ASSUMED_REPORTING_LAG_DAYS.get(period_type, 60)
    cutoff_period_end = as_of_date - timedelta(days=lag_days)

    stmt = (
        select(FinancialMetric)
        .where(
            FinancialMetric.company_id == company_id,
            FinancialMetric.period_type == period_type,
            FinancialMetric.period_end_date <= cutoff_period_end,
            FinancialMetric.is_missing == False,  # noqa: E712
        )
    )
    rows = session.execute(stmt).scalars().all()

    latest_by_name = {}
    for row in rows:
        existing = latest_by_name.get(row.metric_name)
        if existing is None or row.period_end_date > existing.period_end_date:
            latest_by_name[row.metric_name] = row

    return {name: row.value for name, row in latest_by_name.items()}


def get_metrics_as_of_canonical(session: Session, company_id: int, as_of_date: date,
                                 period_type: str = "quarterly") -> dict:
    """
    Same as get_metrics_as_of, but resolved through the canonical metric
    name mapping (from metric_aggregator.METRIC_ALIASES) so callers get
    the same clean field names used everywhere else (revenue, net_income,
    etc.) instead of raw yfinance metric names.
    """
    from app.screener.metric_aggregator import METRIC_ALIASES

    raw_metrics = get_metrics_as_of(session, company_id, as_of_date, period_type)

    result = {}
    for canonical, aliases in METRIC_ALIASES.items():
        value = None
        for alias in aliases:
            if alias in raw_metrics:
                value = raw_metrics[alias]
                break
        result[canonical] = value
    return result


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    reliance = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not reliance:
        print("RELIANCE.NS not found")
    else:
        test_date = date(2026, 1, 1)
        metrics = get_metrics_as_of_canonical(session, reliance.id, test_date, period_type="quarterly")
        print(f"Metrics 'known' as of {test_date} (with {ASSUMED_REPORTING_LAG_DAYS['quarterly']}-day assumed lag):\n")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

        # Sanity check: compare against a much earlier date, should show
        # fewer/older metrics (or None) — proving the cutoff actually filters.
        earlier_date = date(2024, 1, 1)
        earlier_metrics = get_metrics_as_of_canonical(session, reliance.id, earlier_date, period_type="quarterly")
        print(f"\nFor comparison, as of {earlier_date}:")
        print(f"  revenue: {earlier_metrics.get('revenue')}")

    session.close()