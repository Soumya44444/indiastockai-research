"""
Return series and Beta calculation (project spec Section 15: Market Risk).
Computes returns from our own stored price_history rather than trusting
yfinance's single 'beta' field blindly — gives an independently
verifiable number and shows the exact calculation window used.
"""
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import PriceHistory, Company


def get_daily_returns(session: Session, company_id: int, days: int = 252) -> list[float]:
    """
    Daily simple returns from stored price history, most recent `days`
    trading days. Returns are computed as (P_t / P_t-1) - 1.
    Filters out None/NaN close prices defensively (belt-and-suspenders
    alongside the provider-level filter).
    """
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.company_id == company_id)
        .order_by(PriceHistory.trade_date.desc())
        .limit(days + 1)  # need one extra day to compute the first return
    )
    rows = session.execute(stmt).scalars().all()
    rows = list(reversed(rows))  # oldest first

    if len(rows) < 2:
        return []

    closes = [r.close for r in rows if r.close is not None and r.close == r.close]  # filters None and NaN
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] != 0]
    return returns


def calculate_beta(stock_returns: list[float], benchmark_returns: list[float]) -> dict:
    """
    Beta = Covariance(stock, benchmark) / Variance(benchmark)
    Requires equal-length, aligned return series.
    """
    n = min(len(stock_returns), len(benchmark_returns))
    if n < 20:  # need a reasonable sample size for a meaningful beta
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

    if not reliance:
        print("RELIANCE.NS not found")
    else:
        returns = get_daily_returns(session, reliance.id, days=252)
        print(f"RELIANCE.NS: {len(returns)} daily returns computed")
        if returns:
            print(f"  Sample (last 5): {returns[-5:]}")
            print(f"  Mean daily return: {np.mean(returns):.4%}")
            print(f"  Std dev (daily): {np.std(returns, ddof=1):.4%}")

    session.close()