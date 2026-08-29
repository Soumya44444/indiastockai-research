"""
Beginner screener presets (project spec Section 5).
All 9 presets now implemented:
  Strong Fundamentals, High Growth, Low Debt, High ROCE,
  Strong Cash Flow, Quality Companies, Conservative Companies,
  Undervalued, Growth + Reasonable Valuation

Each preset returns which specific criteria passed/failed per company —
never a black-box pass/fail.

Performance: fetches all metrics for a company in ONE bulk query
(get_latest_metrics_bulk), then computes all ratios/scores from that
in-memory dict. Valuation (DCF) is the slowest part of a profile since
it needs live market data + a full discounted cash flow — failures
there degrade gracefully to None rather than breaking the whole profile.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.screener.metric_aggregator import (
    get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
)
from app.screener.ratio_calculator import calculate_all_ratios
from app.screener.fundamental_score import calculate_fundamental_score
from app.valuation.price_targets import generate_price_targets


def build_company_profile(session: Session, company: Company) -> dict:
    """Computes everything a preset filter might need, once per company."""
    metrics = get_latest_metrics_bulk(session, company.id)
    ratios = calculate_all_ratios(metrics)

    revenue_cagr = calculate_metric_cagr(session, company.id, "revenue", years=3)
    revenue_yoy = calculate_yoy_growth(session, company.id, "revenue")

    # Valuation is slower (live market data + DCF), so failures here
    # degrade gracefully to None rather than breaking the whole profile.
    valuation_upside = None
    try:
        price_targets = generate_price_targets(session, company)
        if price_targets["available"] and price_targets["targets"]["base"]["available"]:
            valuation_upside = price_targets["targets"]["base"]["upside_pct"]
    except Exception:
        pass

    fundamental_score = calculate_fundamental_score(metrics, revenue_cagr, revenue_yoy, valuation_upside)

    return {
        "company_id": company.id,
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "revenue_cagr_3y": revenue_cagr,
        "revenue_yoy": revenue_yoy,
        "valuation_upside_pct": valuation_upside,
        "fundamental_score": fundamental_score["total_score_available_weight_only"],
        **ratios,
    }


def _check(label: str, condition: bool | None, detail: str) -> dict:
    if condition is None:
        status = "unknown"
    elif condition:
        status = "passed"
    else:
        status = "failed"
    return {"criterion": label, "status": status, "detail": detail}


def preset_strong_fundamentals(profile: dict) -> list[dict]:
    score = profile["fundamental_score"]
    return [
        _check("Fundamental score >= 60", score >= 60 if score is not None else None, f"score={score}"),
        _check("ROE >= 12%", profile["roe"] >= 0.12 if profile["roe"] is not None else None, f"roe={profile['roe']}"),
        _check("Debt-to-Equity <= 1.0", profile["debt_to_equity"] <= 1.0 if profile["debt_to_equity"] is not None else None, f"debt_to_equity={profile['debt_to_equity']}"),
    ]


def preset_high_growth(profile: dict) -> list[dict]:
    return [
        _check("3yr Revenue CAGR >= 15%", profile["revenue_cagr_3y"] >= 0.15 if profile["revenue_cagr_3y"] is not None else None, f"revenue_cagr_3y={profile['revenue_cagr_3y']}"),
        _check("Latest YoY Revenue Growth >= 15%", profile["revenue_yoy"] >= 0.15 if profile["revenue_yoy"] is not None else None, f"revenue_yoy={profile['revenue_yoy']}"),
    ]


def preset_low_debt(profile: dict) -> list[dict]:
    return [
        _check("Debt-to-Equity <= 0.5", profile["debt_to_equity"] <= 0.5 if profile["debt_to_equity"] is not None else None, f"debt_to_equity={profile['debt_to_equity']}"),
        _check("Interest Coverage >= 5x", profile["interest_coverage"] >= 5 if profile["interest_coverage"] is not None else None, f"interest_coverage={profile['interest_coverage']}"),
    ]


def preset_high_roce(profile: dict) -> list[dict]:
    return [
        _check("ROCE >= 15%", profile["roce"] >= 0.15 if profile["roce"] is not None else None, f"roce={profile['roce']}"),
    ]


def preset_strong_cash_flow(profile: dict) -> list[dict]:
    return [
        _check("CFO/PAT between 0.8 and 2.0", 0.8 <= profile["cfo_to_pat"] <= 2.0 if profile["cfo_to_pat"] is not None else None, f"cfo_to_pat={profile['cfo_to_pat']}"),
    ]


def preset_quality_companies(profile: dict) -> list[dict]:
    return [
        _check("Net Margin >= 10%", profile["net_margin"] >= 0.10 if profile["net_margin"] is not None else None, f"net_margin={profile['net_margin']}"),
        _check("Debt-to-Equity <= 0.75", profile["debt_to_equity"] <= 0.75 if profile["debt_to_equity"] is not None else None, f"debt_to_equity={profile['debt_to_equity']}"),
        _check("Interest Coverage >= 5x", profile["interest_coverage"] >= 5 if profile["interest_coverage"] is not None else None, f"interest_coverage={profile['interest_coverage']}"),
    ]


def preset_conservative_companies(profile: dict) -> list[dict]:
    return [
        _check("Debt-to-Equity <= 0.4", profile["debt_to_equity"] <= 0.4 if profile["debt_to_equity"] is not None else None, f"debt_to_equity={profile['debt_to_equity']}"),
        _check("Current Ratio >= 1.5", profile["current_ratio"] >= 1.5 if profile["current_ratio"] is not None else None, f"current_ratio={profile['current_ratio']}"),
        _check("Positive Revenue Growth", profile["revenue_yoy"] >= 0 if profile["revenue_yoy"] is not None else None, f"revenue_yoy={profile['revenue_yoy']}"),
    ]


def preset_undervalued(profile: dict) -> list[dict]:
    return [
        _check("DCF upside >= 20%",
               profile["valuation_upside_pct"] >= 0.20 if profile["valuation_upside_pct"] is not None else None,
               f"valuation_upside_pct={profile['valuation_upside_pct']}"),
    ]


def preset_growth_reasonable_valuation(profile: dict) -> list[dict]:
    return [
        _check("3yr Revenue CAGR >= 12%",
               profile["revenue_cagr_3y"] >= 0.12 if profile["revenue_cagr_3y"] is not None else None,
               f"revenue_cagr_3y={profile['revenue_cagr_3y']}"),
        _check("DCF upside >= -10% (not significantly overvalued)",
               profile["valuation_upside_pct"] >= -0.10 if profile["valuation_upside_pct"] is not None else None,
               f"valuation_upside_pct={profile['valuation_upside_pct']}"),
    ]


PRESETS = {
    "strong_fundamentals": preset_strong_fundamentals,
    "high_growth": preset_high_growth,
    "low_debt": preset_low_debt,
    "high_roce": preset_high_roce,
    "strong_cash_flow": preset_strong_cash_flow,
    "quality_companies": preset_quality_companies,
    "conservative_companies": preset_conservative_companies,
    "undervalued": preset_undervalued,
    "growth_reasonable_valuation": preset_growth_reasonable_valuation,
}


def run_preset(session: Session, preset_name: str) -> list[dict]:
    """
    Runs a named preset across all companies in the database.
    A company "matches" only if ALL criteria passed (unknown/missing
    data does not count as a pass, but is shown transparently).
    Results sorted by fundamental_score descending.
    """
    if preset_name not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_name}. Available: {list(PRESETS.keys())}")

    filter_fn = PRESETS[preset_name]
    companies = session.query(Company).all()
    results = []

    for company in companies:
        profile = build_company_profile(session, company)
        criteria_results = filter_fn(profile)
        matched = all(c["status"] == "passed" for c in criteria_results)

        results.append({
            "ticker": profile["ticker"],
            "name": profile["name"],
            "matched": matched,
            "fundamental_score": profile["fundamental_score"],
            "criteria": criteria_results,
        })

    results.sort(key=lambda r: (not r["matched"], -(r["fundamental_score"] or 0)))
    return results


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company as CompanyModel

    session = SessionLocal()
    company = session.query(CompanyModel).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        profile = build_company_profile(session, company)
        print(f"Profile for {profile['name']}:")
        print(f"  valuation_upside_pct: {profile['valuation_upside_pct']}")
        print(f"  fundamental_score: {profile['fundamental_score']}")

        print("\nTesting 'undervalued' preset criteria:")
        for c in preset_undervalued(profile):
            print(f"  {c['status']:8s} {c['criterion']} ({c['detail']})")

        print("\nTesting 'growth_reasonable_valuation' preset criteria:")
        for c in preset_growth_reasonable_valuation(profile):
            print(f"  {c['status']:8s} {c['criterion']} ({c['detail']})")

    session.close()