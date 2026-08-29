"""
Max Drawdown, VaR, and CVaR (project spec Section 15: Market Risk).
Max Drawdown includes peak/trough/recovery dates. VaR/CVaR use historical
simulation (not a parametric/normal-distribution assumption) — the
methodology, confidence level, and time horizon are always disclosed
alongside the number, per spec requirement.
"""
import numpy as np
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.data.models import PriceHistory


def calculate_max_drawdown(session: Session, company_id: int, days: int = 252) -> dict:
    """
    Max Drawdown = largest peak-to-trough decline in the price series.
    Returns the peak date/price, trough date/price, drawdown %, and a
    recovery date if the price has since recovered to a new high above
    the pre-drawdown peak (None if not yet recovered).
    """
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.company_id == company_id)
        .order_by(PriceHistory.trade_date.asc())
    )
    all_rows = session.execute(stmt).scalars().all()
    rows = [r for r in all_rows if r.close is not None and r.close == r.close][-days:]

    if len(rows) < 20:
        return {"available": False, "reason": f"Insufficient price history ({len(rows)} days, need >= 20)."}

    running_peak_price = rows[0].close
    running_peak_date = rows[0].trade_date

    max_dd = 0.0
    max_dd_peak_date = running_peak_date
    max_dd_peak_price = running_peak_price
    max_dd_trough_date = running_peak_date
    max_dd_trough_price = running_peak_price

    for row in rows:
        if row.close > running_peak_price:
            running_peak_price = row.close
            running_peak_date = row.trade_date

        drawdown = (row.close - running_peak_price) / running_peak_price
        if drawdown < max_dd:
            max_dd = drawdown
            max_dd_peak_date = running_peak_date
            max_dd_peak_price = running_peak_price
            max_dd_trough_date = row.trade_date
            max_dd_trough_price = row.close

    # Check for recovery: first date after the trough where price closes
    # back above the pre-drawdown peak price.
    recovery_date = None
    for row in rows:
        if row.trade_date > max_dd_trough_date and row.close >= max_dd_peak_price:
            recovery_date = row.trade_date
            break

    return {
        "available": True,
        "max_drawdown_pct": max_dd,
        "peak_date": max_dd_peak_date,
        "peak_price": max_dd_peak_price,
        "trough_date": max_dd_trough_date,
        "trough_price": max_dd_trough_price,
        "recovery_date": recovery_date,
        "recovered": recovery_date is not None,
        "sample_size_days": len(rows),
    }


def calculate_historical_var_cvar(daily_returns: list[float], confidence_level: float = 0.95,
                                   time_horizon_days: int = 1) -> dict:
    """
    Historical simulation VaR/CVaR — uses the actual empirical distribution
    of past returns rather than assuming normality. Scaled to the requested
    time horizon via the square-root-of-time rule (standard approximation).

    VaR = the loss threshold not expected to be exceeded with the given
    confidence level. CVaR (Expected Shortfall) = the average loss GIVEN
    that the VaR threshold was breached — a more informative tail-risk
    measure than VaR alone.
    """
    if len(daily_returns) < 30:
        return {"available": False, "reason": f"Insufficient data ({len(daily_returns)} days, need >= 30 for meaningful percentile estimation)."}

    returns = np.array(daily_returns)
    percentile = (1 - confidence_level) * 100
    var_daily = np.percentile(returns, percentile)

    tail_losses = returns[returns <= var_daily]
    cvar_daily = tail_losses.mean() if len(tail_losses) > 0 else var_daily

    scale_factor = np.sqrt(time_horizon_days)
    var_scaled = var_daily * scale_factor
    cvar_scaled = cvar_daily * scale_factor

    return {
        "available": True,
        "methodology": "Historical simulation (empirical percentile, not normal-distribution assumption)",
        "confidence_level": confidence_level,
        "time_horizon_days": time_horizon_days,
        "var_pct": float(var_scaled),
        "cvar_pct": float(cvar_scaled),
        "sample_size_days": len(daily_returns),
        "interpretation": (
            f"With {confidence_level:.0%} confidence, losses over {time_horizon_days} day(s) are not "
            f"expected to exceed {abs(var_scaled):.2%}. In the worst {100 - confidence_level*100:.0f}% "
            f"of cases, the average loss is {abs(cvar_scaled):.2%} (CVaR/Expected Shortfall)."
        ),
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
        dd = calculate_max_drawdown(session, reliance.id, days=252)
        print("Max Drawdown:")
        if dd["available"]:
            print(f"  {dd['max_drawdown_pct']:.2%} (Peak: {dd['peak_date']} @ {dd['peak_price']:.2f}, "
                  f"Trough: {dd['trough_date']} @ {dd['trough_price']:.2f})")
            print(f"  Recovered: {dd['recovered']}" + (f" on {dd['recovery_date']}" if dd["recovered"] else ""))
        else:
            print(f"  NOT AVAILABLE: {dd['reason']}")

        returns = get_daily_returns(session, reliance.id, days=252)
        var_result = calculate_historical_var_cvar(returns, confidence_level=0.95, time_horizon_days=1)
        print("\n1-Day VaR/CVaR (95% confidence):")
        if var_result["available"]:
            print(f"  Methodology: {var_result['methodology']}")
            print(f"  VaR: {var_result['var_pct']:.2%}")
            print(f"  CVaR: {var_result['cvar_pct']:.2%}")
            print(f"  {var_result['interpretation']}")
        else:
            print(f"  NOT AVAILABLE: {var_result['reason']}")

    session.close()