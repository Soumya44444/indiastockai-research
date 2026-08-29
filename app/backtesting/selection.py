"""
Rebalance schedule and point-in-time portfolio selection (project spec
Section 17). Selection uses ONLY point-in-time data (via
app/backtesting/point_in_time.py) — never live/current data, since a
real historical investor could never have seen today's numbers.

Selection criteria are deliberately simpler than the full DCF-based
screener: DCF needs live market price/shares-outstanding data we cannot
retroactively obtain for arbitrary past dates, so backtested selection
uses fundamentals-only criteria (ROE, growth, leverage) computed
point-in-time. This is a disclosed scope limitation, not an oversight.
"""
from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from app.data.models import Company
from app.backtesting.point_in_time import get_metrics_as_of_canonical


def generate_rebalance_dates(start_date: date, end_date: date, frequency_months: int = 3) -> list[date]:
    """Generates rebalance dates at a fixed interval (default quarterly)."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current = current + relativedelta(months=frequency_months)
    return dates

def _compute_point_in_time_score(metrics: dict) -> float | None:
    """
    Simple, transparent fundamentals-only score for backtest selection:
    equal-weighted average of Net Margin and ANNUALIZED ROE (both
    point-in-time). Net income and equity come from quarterly financial
    statements, so net income is annualized (x4) before computing ROE —
    otherwise ROE would be understated ~4x vs the familiar annual figure
    (a real issue caught during development: ICICI Bank showed "3.6% ROE"
    from raw quarterly division, vs its real ~15-18% annual ROE).
    Net margin needs no such adjustment (it's already a ratio of same-period
    quantities).
    """
    revenue = metrics.get("revenue")
    net_income = metrics.get("net_income")
    total_equity = metrics.get("total_equity")

    if not revenue or net_income is None or not total_equity:
        return None

    net_margin = net_income / revenue
    annualized_net_income = net_income * 4  # quarterly -> annualized approximation
    roe_annualized = annualized_net_income / total_equity

    return (net_margin + roe_annualized) / 2


def select_portfolio_as_of(session: Session, as_of_date: date, top_n: int = 10,
                            min_roe: float = 0.0) -> dict:
    """
    Selects the top-N companies by point-in-time fundamentals score,
    among those with positive point-in-time ROE (excludes loss-making
    companies as a basic quality filter). Uses only data that would have
    been known as of as_of_date.
    """
    companies = session.query(Company).all()
    scored = []

    for company in companies:
        if company.ticker == "^NSEI":  # exclude the benchmark index itself
            continue

        metrics = get_metrics_as_of_canonical(session, company.id, as_of_date, period_type="quarterly")
        score = _compute_point_in_time_score(metrics)

        if score is None:
            continue

        roe = None
        if metrics.get("net_income") is not None and metrics.get("total_equity"):
            roe = (metrics["net_income"] * 4) / metrics["total_equity"]  # annualized

        if roe is None or roe < min_roe:
            continue

        scored.append({"ticker": company.ticker, "company_id": company.id, "score": score, "roe": roe})

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = scored[:top_n]

    return {
        "as_of_date": as_of_date,
        "eligible_count": len(scored),
        "selected_count": len(selected),
        "selected": selected,
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()

    dates = generate_rebalance_dates(date(2025, 1, 1), date(2026, 6, 1), frequency_months=3)
    print(f"Rebalance dates generated: {dates}\n")

    test_date = dates[-1]
    result = select_portfolio_as_of(session, test_date, top_n=10)
    print(f"Portfolio selection as of {test_date}:")
    print(f"  Eligible companies (positive ROE, complete data): {result['eligible_count']}")
    print(f"  Selected (top {len(result['selected'])}):")
    for s in result["selected"]:
        print(f"    {s['ticker']}: score={s['score']:.4f}, roe={s['roe']:.2%}")

    session.close()