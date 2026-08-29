"""
Backtest engine (project spec Section 17). Runs the full loop: for each
rebalance date, select a portfolio using ONLY point-in-time data, hold
equal-weighted until the next rebalance, and compute the period's actual
price-based return from our stored price_history. Also tracks the NIFTY 50
benchmark over the same periods for later comparison (Step 4).
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import PriceHistory, Company
from app.backtesting.selection import generate_rebalance_dates, select_portfolio_as_of


def get_price_near_date(session: Session, company_id: int, target_date: date,
                         max_lookahead_days: int = 7) -> tuple[date, float] | None:
    """
    Finds the closing price on target_date, or the nearest trading day
    AFTER it within max_lookahead_days (handles weekends/holidays where
    target_date itself has no trade). Never looks backward — using a
    price from before the rebalance date would misrepresent execution
    timing.
    """
    stmt = (
        select(PriceHistory)
        .where(
            PriceHistory.company_id == company_id,
            PriceHistory.trade_date >= target_date,
            PriceHistory.trade_date <= target_date + timedelta(days=max_lookahead_days),
            PriceHistory.close.isnot(None),
        )
        .order_by(PriceHistory.trade_date.asc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return row.trade_date, row.close


def compute_period_return(session: Session, company_id: int, start_date: date, end_date: date) -> dict:
    """Simple price return for one company over one holding period."""
    start = get_price_near_date(session, company_id, start_date)
    end = get_price_near_date(session, company_id, end_date)

    if start is None or end is None:
        return {"available": False, "reason": "Missing price data for start or end of period."}

    start_actual_date, start_price = start
    end_actual_date, end_price = end

    if start_price == 0:
        return {"available": False, "reason": "Zero start price — cannot compute return."}

    return_pct = (end_price / start_price) - 1
    return {
        "available": True,
        "return_pct": return_pct,
        "start_date_actual": start_actual_date,
        "end_date_actual": end_actual_date,
        "start_price": start_price,
        "end_price": end_price,
    }


def run_backtest(session: Session, start_date: date, end_date: date,
                  rebalance_frequency_months: int = 3, top_n: int = 10,
                  benchmark_ticker: str = "^NSEI") -> dict:
    """
    Full backtest loop. For each rebalance period:
      1. Select portfolio using ONLY point-in-time data as of the period start
      2. Hold equal-weighted until the next rebalance date
      3. Compute the period's actual portfolio return (average of holdings' returns)
      4. Compute the benchmark's return over the same exact period for comparison

    Companies with missing price data for a period are excluded from that
    period's return calculation (disclosed, not silently zero-filled).
    """
    rebalance_dates = generate_rebalance_dates(start_date, end_date, rebalance_frequency_months)
    if len(rebalance_dates) < 2:
        return {"available": False, "reason": "Need at least 2 rebalance dates to compute a return period."}

    benchmark = session.query(Company).filter_by(ticker=benchmark_ticker).first()
    if not benchmark:
        return {"available": False, "reason": f"Benchmark {benchmark_ticker} not found — load it first."}

    periods = []
    previous_holdings = set()

    for i in range(len(rebalance_dates) - 1):
        period_start = rebalance_dates[i]
        period_end = rebalance_dates[i + 1]

        selection = select_portfolio_as_of(session, period_start, top_n=top_n)
        holdings = selection["selected"]

        if not holdings:
            periods.append({
                "period_start": period_start, "period_end": period_end,
                "available": False, "reason": "No eligible companies selected for this period.",
            })
            continue

        holding_returns = []
        excluded_tickers = []
        for h in holdings:
            result = compute_period_return(session, h["company_id"], period_start, period_end)
            if result["available"]:
                holding_returns.append(result["return_pct"])
            else:
                excluded_tickers.append(h["ticker"])

        if not holding_returns:
            periods.append({
                "period_start": period_start, "period_end": period_end,
                "available": False, "reason": "No holdings had usable price data for this period.",
            })
            continue

        portfolio_return = sum(holding_returns) / len(holding_returns)  # equal-weighted

        benchmark_result = compute_period_return(session, benchmark.id, period_start, period_end)
        benchmark_return = benchmark_result["return_pct"] if benchmark_result["available"] else None

        current_holdings = {h["ticker"] for h in holdings}
        # Turnover: fraction of the portfolio that changed since last period
        if previous_holdings:
            unchanged = len(current_holdings & previous_holdings)
            turnover = 1 - (unchanged / len(current_holdings))
        else:
            turnover = 1.0  # first period — entire portfolio is "new"
        previous_holdings = current_holdings

        periods.append({
            "period_start": period_start,
            "period_end": period_end,
            "available": True,
            "holdings": [h["ticker"] for h in holdings],
            "holdings_used_in_return": len(holding_returns),
            "holdings_excluded": excluded_tickers,
            "portfolio_return_pct": portfolio_return,
            "benchmark_return_pct": benchmark_return,
            "turnover": turnover,
        })

    return {
        "available": True,
        "start_date": start_date,
        "end_date": end_date,
        "rebalance_frequency_months": rebalance_frequency_months,
        "top_n": top_n,
        "periods": periods,
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()

        # Pushed one quarter later than the theoretical minimum — the first
    # quarter of our data coverage (Dec 2024) has very few companies with
    # complete data, since most only accumulate from later quarters.
    # Starting from Jul 2025 gives more companies a full quarter of
    # point-in-time history at the first rebalance.
    result = run_backtest(
        session,
        start_date=date(2025, 7, 1),
        end_date=date(2026, 7, 1),
        rebalance_frequency_months=3,
        top_n=10,
    )

    if not result["available"]:
        print(f"NOT AVAILABLE: {result['reason']}")
    else:
        print(f"Backtest: {result['start_date']} to {result['end_date']}, "
              f"rebalanced every {result['rebalance_frequency_months']} months, top {result['top_n']}\n")

        for p in result["periods"]:
            if not p["available"]:
                print(f"[{p['period_start']} -> {p['period_end']}] NOT AVAILABLE: {p['reason']}")
                continue
            benchmark_str = f"{p['benchmark_return_pct']:.2%}" if p["benchmark_return_pct"] is not None else "N/A"
            print(f"[{p['period_start']} -> {p['period_end']}] "
                  f"Portfolio: {p['portfolio_return_pct']:.2%}  "
                  f"Benchmark: {benchmark_str}  "
                  f"Turnover: {p['turnover']:.0%}  "
                  f"Holdings used: {p['holdings_used_in_return']}/{len(p['holdings'])}")
            if p["holdings_excluded"]:
                print(f"    Excluded (missing price data): {p['holdings_excluded']}")

    session.close()