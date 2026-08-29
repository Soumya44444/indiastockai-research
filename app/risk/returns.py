"""
Return series and Beta calculation (project spec Section 15: Market Risk).
Computes returns from our own stored price_history rather than trusting
yfinance's single 'beta' field blindly — gives an independently
verifiable number and shows the exact calculation window used.

IMPORTANT: returns are computed and aligned by TRADE DATE, not by list
position. Two return series can have different sets of trading days
(data gaps, holiday handling differences), so aligning by raw list index
would silently corrupt beta/correlation — this was caught as a real bug
during development (self-computed Beta for RELIANCE.NS came back with an
implausibly low correlation to NIFTY 50 until date-based alignment fixed it).
"""
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import PriceHistory, Company


def get_daily_returns_by_date(session: Session, company_id: int, days: int = 252) -> dict:
    """
    Daily simple returns from stored price history, most recent `days`
    trading days, keyed by trade_date so series can be safely aligned
    across different companies/benchmarks.
    """
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.company_id == company_id)
        .order_by(PriceHistory.trade_date.desc())
        .limit(days + 1)
    )
    rows = session.execute(stmt).scalars().all()
    rows = list(reversed(rows))  # oldest first

    valid_rows = [r for r in rows if r.close is not None and r.close == r.close]  # filters None and NaN

    returns_by_date = {}
    for i in range(1, len(valid_rows)):
        prev, curr = valid_rows[i - 1], valid_rows[i]
        if prev.close != 0:
            returns_by_date[curr.trade_date] = (curr.close / prev.close) - 1

    return returns_by_date


def get_daily_returns(session: Session, company_id: int, days: int = 252) -> list[float]:
    """
    Backward-compatible plain-list version (date order preserved, but
    dates themselves discarded). Kept for callers that don't need
    cross-series alignment (e.g. computing a single company's own
    volatility, where alignment against another series isn't needed).
    """
    by_date = get_daily_returns_by_date(session, company_id, days)
    return [by_date[d] for d in sorted(by_date.keys())]


def align_return_series(returns_a: dict, returns_b: dict) -> tuple[list[float], list[float]]:
    """
    Aligns two date-keyed return series on their common trading dates
    only, in matching date order. This is the correct way to compare
    two return series — never by raw list position.
    """
    common_dates = sorted(set(returns_a.keys()) & set(returns_b.keys()))
    aligned_a = [returns_a[d] for d in common_dates]
    aligned_b = [returns_b[d] for d in common_dates]
    return aligned_a, aligned_b


def calculate_beta(stock_returns: list[float], benchmark_returns: list[float]) -> dict:
    """
    Beta = Covariance(stock, benchmark) / Variance(benchmark)
    Callers must pass already-aligned series (see align_return_series) —
    this function does not itself verify alignment, since it only
    receives plain lists by the time it's called.
    """
    n = min(len(stock_returns), len(benchmark_returns))
    if n < 20:
        return {"available": False, "reason": f"Insufficient overlapping data (only {n} days, need >= 20)."}

    stock = np.array(stock_returns[-n:])
    bench = np.array(benchmark_returns[-n:])

    covariance = np.cov(stock, bench)[0][1]
    benchmark_variance = np.var(bench, ddof=1)

    if benchmark_variance == 0:
        return {"available": False, "reason": "Benchmark variance is zero — cannot compute beta."}

    beta = covariance / benchmark_variance
    correlation = np.corrcoef(stock, bench)[0][1]

    return {
        "available": True,
        "beta": float(beta),
        "correlation_to_benchmark": float(correlation),
        "sample_size_days": n,
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()

    reliance = session.query(Company).filter_by(ticker="RELIANCE.NS").first()
    nifty = session.query(Company).filter_by(ticker="^NSEI").first()

    if not reliance or not nifty:
        print("RELIANCE.NS or ^NSEI not found — load both first")
    else:
        stock_by_date = get_daily_returns_by_date(session, reliance.id, days=252)
        bench_by_date = get_daily_returns_by_date(session, nifty.id, days=252)

        print(f"RELIANCE.NS: {len(stock_by_date)} dated returns | "
              f"NIFTY 50: {len(bench_by_date)} dated returns")

        aligned_stock, aligned_bench = align_return_series(stock_by_date, bench_by_date)
        print(f"Common trading dates after alignment: {len(aligned_stock)}\n")

        beta_result = calculate_beta(aligned_stock, aligned_bench)
        if beta_result["available"]:
            print(f"Self-computed Beta (date-aligned): {beta_result['beta']:.3f}")
            print(f"Correlation to NIFTY 50: {beta_result['correlation_to_benchmark']:.3f}")
            print(f"Sample size: {beta_result['sample_size_days']} trading days")
        else:
            print(f"Beta NOT AVAILABLE: {beta_result['reason']}")

    session.close()