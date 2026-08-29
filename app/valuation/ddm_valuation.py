"""
Dividend Discount Model — Gordon Growth variant (project spec Section 13:
"FCFE/DDM/RIM using cost of equity" per the equity-research-platform
project's prior approach, adapted here).

Value/share = Next Year's Dividend / (Cost of Equity - Growth Rate)

Growth rate is estimated via the sustainable growth rate formula
(Retention Ratio x ROE) rather than guessed — an explicit, auditable
derivation. DDM is only meaningful for dividend-paying companies;
non-payers return "not applicable" rather than a fabricated zero.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.data.providers.yfinance_provider import fetch_market_data
from app.screener.ratio_calculator import roe as calc_roe
from app.screener.metric_aggregator import get_latest_metrics_bulk
from app.valuation.dcf_engine import calculate_wacc


def estimate_sustainable_growth(metrics: dict, market: dict) -> dict:
    """
    Sustainable Growth Rate = Retention Ratio x ROE
    Retention Ratio = 1 - Payout Ratio
    """
    payout_ratio = market.get("payout_ratio")
    r_oe = calc_roe(metrics)

    if payout_ratio is None or r_oe is None:
        return {"available": False, "reason": "Missing payout ratio or ROE."}

    payout_ratio = max(min(payout_ratio, 1.0), 0.0)  # sanity bound
    retention_ratio = 1 - payout_ratio
    growth_rate = retention_ratio * r_oe

    return {
        "available": True,
        "growth_rate": growth_rate,
        "retention_ratio": retention_ratio,
        "payout_ratio": payout_ratio,
        "roe_used": r_oe,
    }


def run_ddm(session: Session, company: Company) -> dict:
    """
    Full DDM valuation. Requires: company pays dividends, cost of equity
    is computable, and the resulting growth rate is sane relative to
    cost of equity (growth must be below cost of equity for valid math).
    """
    market = fetch_market_data(company.ticker)
    metrics = get_latest_metrics_bulk(session, company.id)

    dividend_rate = market.get("dividend_rate")
    if not dividend_rate or dividend_rate <= 0:
        return {"available": False, "reason": "Company does not pay a dividend — DDM not applicable."}

    wacc_result = calculate_wacc(session, company)
    if not wacc_result["available"]:
        return {"available": False, "reason": wacc_result["reason"]}
    cost_of_equity = wacc_result["cost_of_equity"]

    growth = estimate_sustainable_growth(metrics, market)
    if not growth["available"]:
        return {"available": False, "reason": growth["reason"]}

    growth_rate = growth["growth_rate"]
    if growth_rate >= cost_of_equity:
        return {
            "available": False,
            "reason": (
                f"Estimated growth rate ({growth_rate:.1%}) exceeds cost of equity "
                f"({cost_of_equity:.1%}) — Gordon Growth DDM math is invalid here. "
                f"Rely on DCF/relative valuation instead for this company."
            ),
        }

    next_year_dividend = dividend_rate * (1 + growth_rate)
    fair_value_per_share = next_year_dividend / (cost_of_equity - growth_rate)

    return {
        "available": True,
        "current_dividend_rate": dividend_rate,
        "next_year_dividend_estimate": next_year_dividend,
        "cost_of_equity": cost_of_equity,
        "growth_rate": growth_rate,
        "growth_basis": growth,
        "fair_value_per_share": fair_value_per_share,
        "current_price": market.get("current_price"),
        "methodology_note": (
            f"DDM (Gordon Growth): Value = Next Dividend / (Cost of Equity - Growth). "
            f"Growth estimated as Retention Ratio ({growth['retention_ratio']:.1%}) x "
            f"ROE ({growth['roe_used']:.1%}) = {growth_rate:.1%} (sustainable growth rate "
            f"method, not a guess). Cost of Equity {cost_of_equity:.1%} via CAPM."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = run_ddm(session, company)
        print(f"DDM Valuation: {company.name}\n")

        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            print(f"Current Dividend Rate: {result['current_dividend_rate']}")
            print(f"Current Price: {result['current_price']}")
            print(f"\n{result['methodology_note']}\n")
            print(f"Fair Value/Share: {result['fair_value_per_share']:,.2f}")

    session.close()