"""
Volatility, Sharpe Ratio, and Sortino Ratio (project spec Section 15:
Market Risk). All computed from our own return series (via app/risk/returns.py),
annualized using the standard 252-trading-day convention, with the
risk-free rate disclosed (matches the rate used in Phase 5's DCF WACC
for consistency across the platform).
"""
import numpy as np

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.068  # matches DCF_engine.RISK_FREE_RATE for consistency


def annualized_volatility(daily_returns: list[float]) -> dict:
    """
    Annualized volatility = daily std dev * sqrt(252).
    Standard convention, disclosed explicitly rather than left implicit.
    """
    if len(daily_returns) < 20:
        return {"available": False, "reason": f"Insufficient data (only {len(daily_returns)} days, need >= 20)."}

    daily_std = np.std(daily_returns, ddof=1)
    annual_vol = daily_std * np.sqrt(TRADING_DAYS_PER_YEAR)

    return {
        "available": True,
        "daily_volatility": float(daily_std),
        "annualized_volatility": float(annual_vol),
        "sample_size_days": len(daily_returns),
    }


def sharpe_ratio(daily_returns: list[float], risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL) -> dict:
    """
    Sharpe Ratio = (Annualized Return - Risk-Free Rate) / Annualized Volatility.
    Uses annualized MEAN daily return (compounded), not just mean*252,
    for a more accurate annualization of returns.
    """
    if len(daily_returns) < 20:
        return {"available": False, "reason": f"Insufficient data (only {len(daily_returns)} days, need >= 20)."}

    returns = np.array(daily_returns)
    mean_daily = np.mean(returns)
    annualized_return = (1 + mean_daily) ** TRADING_DAYS_PER_YEAR - 1

    vol_result = annualized_volatility(daily_returns)
    if not vol_result["available"]:
        return vol_result

    annual_vol = vol_result["annualized_volatility"]
    if annual_vol == 0:
        return {"available": False, "reason": "Zero volatility — Sharpe ratio undefined."}

    sharpe = (annualized_return - risk_free_rate_annual) / annual_vol

    return {
        "available": True,
        "sharpe_ratio": float(sharpe),
        "annualized_return": float(annualized_return),
        "annualized_volatility": annual_vol,
        "risk_free_rate_used": risk_free_rate_annual,
    }


def sortino_ratio(daily_returns: list[float], risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL) -> dict:
    """
    Sortino Ratio = (Annualized Return - Risk-Free Rate) / Downside Deviation.
    Unlike Sharpe, only penalizes downside volatility (returns below 0),
    not upside swings — a common critique-response to Sharpe.
    """
    if len(daily_returns) < 20:
        return {"available": False, "reason": f"Insufficient data (only {len(daily_returns)} days, need >= 20)."}

    returns = np.array(daily_returns)
    mean_daily = np.mean(returns)
    annualized_return = (1 + mean_daily) ** TRADING_DAYS_PER_YEAR - 1

    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        return {"available": False, "reason": "No downside returns in sample — Sortino ratio undefined."}

    downside_deviation_daily = np.sqrt(np.mean(downside_returns ** 2))
    downside_deviation_annual = downside_deviation_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

    if downside_deviation_annual == 0:
        return {"available": False, "reason": "Zero downside deviation — Sortino ratio undefined."}

    sortino = (annualized_return - risk_free_rate_annual) / downside_deviation_annual

    return {
        "available": True,
        "sortino_ratio": float(sortino),
        "annualized_return": float(annualized_return),
        "downside_deviation_annual": float(downside_deviation_annual),
        "risk_free_rate_used": risk_free_rate_annual,
        "downside_days_count": int(len(downside_returns)),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company
    from app.risk.returns import get_daily_returns

    session = SessionLocal()
    reliance = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not reliance:
        print("RELIANCE.NS not found")
    else:
        returns = get_daily_returns(session, reliance.id, days=252)
        print(f"RELIANCE.NS: {len(returns)} daily returns\n")

        vol = annualized_volatility(returns)
        print(f"Annualized Volatility: {vol['annualized_volatility']:.2%}" if vol["available"] else vol["reason"])

        sharpe = sharpe_ratio(returns)
        if sharpe["available"]:
            print(f"\nSharpe Ratio: {sharpe['sharpe_ratio']:.3f}")
            print(f"  Annualized Return: {sharpe['annualized_return']:.2%}")
            print(f"  Risk-Free Rate: {sharpe['risk_free_rate_used']:.2%}")
        else:
            print(sharpe["reason"])

        sortino = sortino_ratio(returns)
        if sortino["available"]:
            print(f"\nSortino Ratio: {sortino['sortino_ratio']:.3f}")
            print(f"  Downside Deviation (annualized): {sortino['downside_deviation_annual']:.2%}")
            print(f"  Downside days in sample: {sortino['downside_days_count']}/{len(returns)}")
        else:
            print(sortino["reason"])

    session.close()