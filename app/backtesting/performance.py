"""
Backtest performance metrics (project spec Section 17): CAGR, Alpha vs
NIFTY 50, Volatility, Sharpe, Sortino, Max Drawdown, Win rate, Turnover,
equity & drawdown curves, yearly returns.

Built specifically for PERIOD returns (e.g. quarterly, from the backtest
engine) rather than reusing Phase 6's daily-return risk functions directly —
mixing return frequencies without correct annualization scaling would
silently produce wrong numbers.
"""
import numpy as np
from app.risk.risk_metrics import RISK_FREE_RATE_ANNUAL


def build_equity_curve(periods: list[dict], return_field: str = "portfolio_return_pct",
                        starting_value: float = 100.0) -> list[dict]:
    """
    Compounds period returns into a cumulative equity curve starting at
    starting_value (e.g. 100 = "value of ₹100 invested at the start").
    """
    curve = [{"date": periods[0]["period_start"], "value": starting_value}] if periods else []
    value = starting_value

    for p in periods:
        if not p.get("available"):
            continue
        ret = p.get(return_field)
        if ret is None:
            continue
        value = value * (1 + ret)
        curve.append({"date": p["period_end"], "value": value})

    return curve


def calculate_max_drawdown_from_curve(curve: list[dict]) -> dict:
    """Max Drawdown computed directly from an equity curve (peak/trough/recovery)."""
    if len(curve) < 2:
        return {"available": False, "reason": "Insufficient data points."}

    running_peak = curve[0]["value"]
    running_peak_date = curve[0]["date"]
    max_dd = 0.0
    max_dd_peak_date = running_peak_date
    max_dd_trough_date = running_peak_date

    for point in curve:
        if point["value"] > running_peak:
            running_peak = point["value"]
            running_peak_date = point["date"]
        dd = (point["value"] - running_peak) / running_peak
        if dd < max_dd:
            max_dd = dd
            max_dd_peak_date = running_peak_date
            max_dd_trough_date = point["date"]

    return {
        "available": True,
        "max_drawdown_pct": max_dd,
        "peak_date": max_dd_peak_date,
        "trough_date": max_dd_trough_date,
    }


def calculate_cagr_from_periods(period_returns: list[float], periods_per_year: int) -> float | None:
    """CAGR from a series of period (e.g. quarterly) returns, compounded and annualized."""
    if not period_returns:
        return None
    cumulative = 1.0
    for r in period_returns:
        cumulative *= (1 + r)
    years = len(period_returns) / periods_per_year
    if years <= 0 or cumulative <= 0:
        return None
    return cumulative ** (1 / years) - 1


def calculate_period_volatility(period_returns: list[float], periods_per_year: int) -> float | None:
    """Annualized volatility from period returns (std dev * sqrt(periods_per_year))."""
    if len(period_returns) < 2:
        return None
    return float(np.std(period_returns, ddof=1) * np.sqrt(periods_per_year))


def calculate_period_sharpe(period_returns: list[float], periods_per_year: int,
                             risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL) -> float | None:
    cagr = calculate_cagr_from_periods(period_returns, periods_per_year)
    vol = calculate_period_volatility(period_returns, periods_per_year)
    if cagr is None or vol is None or vol == 0:
        return None
    return (cagr - risk_free_rate_annual) / vol


def calculate_period_sortino(period_returns: list[float], periods_per_year: int,
                              risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL) -> float | None:
    cagr = calculate_cagr_from_periods(period_returns, periods_per_year)
    if cagr is None:
        return None
    returns = np.array(period_returns)
    downside = returns[returns < 0]
    if len(downside) == 0:
        return None
    downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(periods_per_year))
    if downside_dev == 0:
        return None
    return (cagr - risk_free_rate_annual) / downside_dev


def calculate_win_rate(period_returns: list[float]) -> float | None:
    """Fraction of periods with a positive return."""
    if not period_returns:
        return None
    wins = sum(1 for r in period_returns if r > 0)
    return wins / len(period_returns)


def calculate_backtest_performance(backtest_result: dict) -> dict:
    """
    Full performance summary from a run_backtest() result. Periods with
    available=False are excluded from all calculations, and the count of
    excluded periods is disclosed rather than silently ignored.
    """
    if not backtest_result.get("available"):
        return {"available": False, "reason": backtest_result.get("reason", "Backtest not available.")}

    periods = backtest_result["periods"]
    usable_periods = [p for p in periods if p.get("available")]
    excluded_count = len(periods) - len(usable_periods)

    if not usable_periods:
        return {"available": False, "reason": "No usable periods in this backtest."}

    rebalance_months = backtest_result["rebalance_frequency_months"]
    periods_per_year = 12 / rebalance_months

    portfolio_returns = [p["portfolio_return_pct"] for p in usable_periods]
    benchmark_returns = [p["benchmark_return_pct"] for p in usable_periods if p["benchmark_return_pct"] is not None]
    turnovers = [p["turnover"] for p in usable_periods]

    portfolio_cagr = calculate_cagr_from_periods(portfolio_returns, periods_per_year)
    benchmark_cagr = calculate_cagr_from_periods(benchmark_returns, periods_per_year) if benchmark_returns else None
    alpha = (portfolio_cagr - benchmark_cagr) if (portfolio_cagr is not None and benchmark_cagr is not None) else None

    equity_curve = build_equity_curve(usable_periods, "portfolio_return_pct")
    benchmark_curve = build_equity_curve(usable_periods, "benchmark_return_pct")
    dd_result = calculate_max_drawdown_from_curve(equity_curve)

    yearly_returns = {}
    for p in usable_periods:
        year = p["period_end"].year
        yearly_returns.setdefault(year, 1.0)
        yearly_returns[year] *= (1 + p["portfolio_return_pct"])
    yearly_returns = {y: v - 1 for y, v in yearly_returns.items()}

    return {
        "available": True,
        "period_count": len(usable_periods),
        "excluded_period_count": excluded_count,
        "periods_per_year_basis": periods_per_year,
        "cagr": portfolio_cagr,
        "benchmark_cagr": benchmark_cagr,
        "alpha_vs_benchmark": alpha,
        "volatility_annualized": calculate_period_volatility(portfolio_returns, periods_per_year),
        "sharpe_ratio": calculate_period_sharpe(portfolio_returns, periods_per_year),
        "sortino_ratio": calculate_period_sortino(portfolio_returns, periods_per_year),
        "max_drawdown": dd_result,
        "win_rate": calculate_win_rate(portfolio_returns),
        "avg_turnover": sum(turnovers) / len(turnovers) if turnovers else None,
        "yearly_returns": yearly_returns,
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
    }


if __name__ == "__main__":
    from datetime import date
    from app.data.db import SessionLocal
    from app.backtesting.backtest_engine import run_backtest

    session = SessionLocal()

    backtest = run_backtest(
        session,
        start_date=date(2025, 7, 1),
        end_date=date(2026, 7, 1),
        rebalance_frequency_months=3,
        top_n=10,
    )

    perf = calculate_backtest_performance(backtest)

    if not perf["available"]:
        print(f"NOT AVAILABLE: {perf['reason']}")
    else:
        print(f"Backtest Performance Summary ({perf['period_count']} usable periods, "
              f"{perf['excluded_period_count']} excluded)\n")
        print(f"CAGR: {perf['cagr']:.2%}" if perf["cagr"] is not None else "CAGR: N/A")
        print(f"Benchmark CAGR: {perf['benchmark_cagr']:.2%}" if perf["benchmark_cagr"] is not None else "Benchmark CAGR: N/A")
        print(f"Alpha vs Benchmark: {perf['alpha_vs_benchmark']:.2%}" if perf["alpha_vs_benchmark"] is not None else "Alpha: N/A")
        print(f"Annualized Volatility: {perf['volatility_annualized']:.2%}" if perf["volatility_annualized"] is not None else "Volatility: N/A")
        print(f"Sharpe Ratio: {perf['sharpe_ratio']:.3f}" if perf["sharpe_ratio"] is not None else "Sharpe: N/A")
        print(f"Sortino Ratio: {perf['sortino_ratio']:.3f}" if perf["sortino_ratio"] is not None else "Sortino: N/A")
        if perf["max_drawdown"]["available"]:
            print(f"Max Drawdown: {perf['max_drawdown']['max_drawdown_pct']:.2%} "
                  f"(Peak: {perf['max_drawdown']['peak_date']}, Trough: {perf['max_drawdown']['trough_date']})")
        print(f"Win Rate: {perf['win_rate']:.0%}" if perf["win_rate"] is not None else "Win Rate: N/A")
        print(f"Avg Turnover: {perf['avg_turnover']:.0%}" if perf["avg_turnover"] is not None else "Avg Turnover: N/A")
        print(f"\nYearly Returns: {perf['yearly_returns']}")
        print(f"\nEquity Curve (final value from ₹100 start): {perf['equity_curve'][-1]['value']:.2f}")

    session.close()