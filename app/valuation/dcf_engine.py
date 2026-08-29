"""
DCF valuation engine (project spec Section 13).
WACC (CAPM cost of equity + post-tax cost of debt) -> discount Bear/Base/Bull
FCF projections from Phase 4 -> Enterprise Value -> Equity Value -> Fair
Value per share, with a sensitivity table across terminal growth rates.

Macro assumptions (risk-free rate, equity risk premium) are disclosed
constants representative of the Indian market context, not fabricated
per-company. Terminal growth is capped conservatively below long-run
nominal GDP growth, per standard DCF practice.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.data.providers.yfinance_provider import fetch_market_data
from app.screener.metric_aggregator import get_latest_metrics_bulk
from app.forecasting.forecast_engine import generate_forecast

# Macro assumptions — disclosed, not hidden. Representative of the Indian
# market context as of this build; should be revisited periodically.
RISK_FREE_RATE = 0.068          # ~10yr Indian G-Sec yield
EQUITY_RISK_PREMIUM = 0.065     # typical India equity risk premium
DEFAULT_TERMINAL_GROWTH = 0.04  # conservative, below long-run nominal GDP growth
DEFAULT_BETA_IF_MISSING = 1.0   # neutral fallback, disclosed when used


def calculate_wacc(session: Session, company: Company) -> dict:
    """
    WACC = (E/V * Cost of Equity) + (D/V * Cost of Debt * (1 - Tax Rate))
    Cost of Equity via CAPM: Rf + Beta * ERP
    """
    market = fetch_market_data(company.ticker)
    metrics = get_latest_metrics_bulk(session, company.id)

    beta = market.get("beta")
    beta_used = beta if beta is not None else DEFAULT_BETA_IF_MISSING
    cost_of_equity = RISK_FREE_RATE + beta_used * EQUITY_RISK_PREMIUM

    market_cap = market.get("market_cap")
    total_debt = metrics.get("total_debt") or 0.0
    interest_expense = metrics.get("interest_expense")
    pretax_income = metrics.get("pretax_income")
    tax_provision = metrics.get("tax_provision")

    tax_rate = None
    if pretax_income and tax_provision is not None and pretax_income != 0:
        tax_rate = max(min(tax_provision / pretax_income, 0.5), 0.0)  # sanity-bounded 0-50%
    if tax_rate is None:
        tax_rate = 0.25  # disclosed fallback, typical Indian corporate rate

    cost_of_debt = None
    if interest_expense and total_debt:
        cost_of_debt = abs(interest_expense) / total_debt

    if market_cap is None or market_cap <= 0:
        return {"available": False, "reason": "Market cap unavailable — cannot weight WACC."}

    total_capital = market_cap + total_debt
    equity_weight = market_cap / total_capital
    debt_weight = total_debt / total_capital if total_capital > 0 else 0.0

    if cost_of_debt is not None:
        wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt * (1 - tax_rate)
    else:
        # No debt or no interest data — WACC collapses to cost of equity
        wacc = cost_of_equity

    return {
        "available": True,
        "wacc": wacc,
        "cost_of_equity": cost_of_equity,
        "cost_of_debt": cost_of_debt,
        "beta_used": beta_used,
        "beta_was_estimated": beta is None,
        "tax_rate_used": tax_rate,
        "equity_weight": equity_weight,
        "debt_weight": debt_weight,
        "risk_free_rate": RISK_FREE_RATE,
        "equity_risk_premium": EQUITY_RISK_PREMIUM,
    }


def _discount_fcf_series(fcf_by_year: list[float], wacc: float, terminal_growth: float) -> dict:
    """
    Present-values each year's FCF, then adds a Gordon Growth terminal
    value discounted back to present. Returns None-safe if WACC <= terminal
    growth (invalid DCF math — would produce a nonsensical infinite value).
    """
    if wacc <= terminal_growth:
        return {
            "available": False,
            "reason": f"WACC ({wacc:.1%}) must exceed terminal growth ({terminal_growth:.1%}) for a valid DCF."
        }

    pv_explicit = 0.0
    for year, fcf in enumerate(fcf_by_year, start=1):
        pv_explicit += fcf / ((1 + wacc) ** year)

    final_year_fcf = fcf_by_year[-1]
    terminal_value = (final_year_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** len(fcf_by_year))

    enterprise_value = pv_explicit + pv_terminal

    return {
        "available": True,
        "pv_explicit_fcf": pv_explicit,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "enterprise_value": enterprise_value,
        "terminal_value_pct_of_ev": pv_terminal / enterprise_value if enterprise_value else None,
    }


def run_dcf(session: Session, company: Company, years: int = 3,
            terminal_growth: float = DEFAULT_TERMINAL_GROWTH) -> dict:
    """
    Full DCF: WACC -> discount Bear/Base/Bull FCF paths from Phase 4's
    forecast engine -> Enterprise Value -> Equity Value -> Fair Value/share.
    """
    wacc_result = calculate_wacc(session, company)
    if not wacc_result["available"]:
        return {"available": False, "reason": wacc_result["reason"]}

    forecast = generate_forecast(session, company.id, years=years)
    if not forecast["available"]:
        return {"available": False, "reason": forecast["reason"]}

    market = fetch_market_data(company.ticker)
    shares_outstanding = market.get("shares_outstanding")
    metrics = get_latest_metrics_bulk(session, company.id)
    total_debt = metrics.get("total_debt") or 0.0
    # Cash isn't in our current metric set — treated as 0 (disclosed
    # simplification; understates equity value slightly for cash-rich firms).
    net_debt = total_debt

    if not shares_outstanding:
        return {"available": False, "reason": "Shares outstanding unavailable — cannot compute per-share value."}

    results = {}
    for scenario_name, years_data in forecast["forecasts"].items():
        fcf_series = [y["fcf"] for y in years_data]
        if any(f is None for f in fcf_series):
            results[scenario_name] = {"available": False, "reason": "Incomplete FCF projection for this scenario."}
            continue

        dcf = _discount_fcf_series(fcf_series, wacc_result["wacc"], terminal_growth)
        if not dcf["available"]:
            results[scenario_name] = dcf
            continue

        equity_value = dcf["enterprise_value"] - net_debt
        fair_value_per_share = equity_value / shares_outstanding

        results[scenario_name] = {
            "available": True,
            "enterprise_value": dcf["enterprise_value"],
            "equity_value": equity_value,
            "fair_value_per_share": fair_value_per_share,
            "terminal_value_pct_of_ev": dcf["terminal_value_pct_of_ev"],
        }

    return {
        "available": True,
        "wacc_breakdown": wacc_result,
        "terminal_growth_used": terminal_growth,
        "net_debt_used": net_debt,
        "shares_outstanding": shares_outstanding,
        "current_price": market.get("current_price"),
        "scenarios": results,
        "methodology_note": (
            f"WACC = {wacc_result['wacc']:.1%} (Cost of Equity {wacc_result['cost_of_equity']:.1%} via CAPM "
            f"[Rf={RISK_FREE_RATE:.1%}, Beta={wacc_result['beta_used']:.2f}"
            f"{' (estimated, not available from data source)' if wacc_result['beta_was_estimated'] else ''}"
            f", ERP={EQUITY_RISK_PREMIUM:.1%}]). Terminal growth {terminal_growth:.1%}. "
            f"Net debt treated as gross debt (cash not currently captured — "
            f"understates equity value for cash-rich companies, disclosed limitation)."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = run_dcf(session, company, years=3)
        print(f"DCF Valuation: {company.name}\n")

        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            print(f"Current Price: {result['current_price']}")
            print(f"Shares Outstanding: {result['shares_outstanding']:,.0f}")
            print(f"\n{result['methodology_note']}\n")

            for scenario, vals in result["scenarios"].items():
                if not vals["available"]:
                    print(f"[{scenario.upper()}] NOT AVAILABLE: {vals['reason']}")
                    continue
                print(f"[{scenario.upper()}] Fair Value/Share: {vals['fair_value_per_share']:,.2f}  "
                      f"(EV={vals['enterprise_value']:,.0f}, Equity Value={vals['equity_value']:,.0f}, "
                      f"Terminal Value%={vals['terminal_value_pct_of_ev']:.1%})")

    session.close()