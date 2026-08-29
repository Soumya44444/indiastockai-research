"""
Price target generator (project spec Section 14).
Combines DCF Bear/Base/Bull scenarios into price targets with current
price, upside/downside %, and margin of safety. DDM (where available)
is shown as an independent cross-check, not blended in — mixing models
with different assumptions into one number would hide real uncertainty
rather than surface it.

Never presented as guaranteed — every output carries the scenario
assumptions that produced it.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.valuation.dcf_engine import run_dcf
from app.valuation.ddm_valuation import run_ddm


def _upside(current_price: float, target_price: float) -> float:
    return (target_price - current_price) / current_price


def generate_price_targets(session: Session, company: Company, years: int = 3) -> dict:
    """
    Full price target output: DCF-based Bear/Base/Bull targets with
    upside/downside and margin of safety, plus DDM as an independent
    cross-check when the company pays dividends.
    """
    dcf = run_dcf(session, company, years=years)
    if not dcf["available"]:
        return {"available": False, "reason": dcf["reason"]}

    current_price = dcf["current_price"]
    if not current_price:
        return {"available": False, "reason": "Current market price unavailable."}

    targets = {}
    for scenario_name, vals in dcf["scenarios"].items():
        if not vals["available"]:
            targets[scenario_name] = {"available": False, "reason": vals["reason"]}
            continue

        target_price = vals["fair_value_per_share"]
        upside = _upside(current_price, target_price)

        targets[scenario_name] = {
            "available": True,
            "target_price": round(target_price, 2),
            "upside_pct": round(upside, 4),
            # Margin of safety: how far below the Base-case fair value the
            # CURRENT price sits — a classic value-investing concept.
            # Meaningful primarily for the Base scenario.
            "margin_of_safety_pct": round(-upside, 4) if upside < 0 else 0.0,
        }

    ddm = run_ddm(session, company)
    ddm_summary = None
    if ddm["available"]:
        ddm_target = ddm["fair_value_per_share"]
        ddm_summary = {
            "target_price": round(ddm_target, 2),
            "upside_pct": round(_upside(current_price, ddm_target), 4),
            "note": "Independent cross-check via Dividend Discount Model — not blended into DCF targets.",
        }

    return {
        "available": True,
        "ticker": company.ticker,
        "current_price": current_price,
        "horizon_years": years,
        "targets": targets,
        "ddm_cross_check": ddm_summary,
        "note": (
            "Price targets are scenario-based illustrations derived from explicit, "
            "disclosed assumptions (see DCF methodology) — not guarantees or "
            "recommendations. Actual results depend on execution, macro conditions, "
            "and factors outside any model's scope."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = generate_price_targets(session, company, years=3)
        print(f"Price Targets: {company.name}\n")

        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            print(f"Current Price: {result['current_price']}")
            print(f"Horizon: {result['horizon_years']} years\n")

            for scenario, t in result["targets"].items():
                if not t["available"]:
                    print(f"[{scenario.upper()}] NOT AVAILABLE: {t['reason']}")
                    continue
                print(f"[{scenario.upper()}] Target: {t['target_price']}  "
                      f"Upside: {t['upside_pct']:.1%}  "
                      f"Margin of Safety: {t['margin_of_safety_pct']:.1%}")

            if result["ddm_cross_check"]:
                d = result["ddm_cross_check"]
                print(f"\n[DDM CROSS-CHECK] Target: {d['target_price']}  Upside: {d['upside_pct']:.1%}")
                print(f"  {d['note']}")

            print(f"\n{result['note']}")

    session.close()