"""
Weighted fundamental score engine (project spec Section 10).
Weights: Growth 20% | Profitability 20% | Balance Sheet 15% | Cash Flow 15%
         | Valuation 20% | Quality 10%

Every component score comes with a plain-language rationale — no black-box.
Quality still requires additional earnings-quality-flag-to-score mapping
(deferred); Valuation is now wired in via Phase 5's price target engine.

Accepts a pre-fetched metrics dict + growth figures, computed once per
company by the caller — avoids redundant DB queries during screening.
"""
from app.screener.ratio_calculator import (
    net_margin, roe, roce, debt_to_equity, interest_coverage,
    current_ratio, cfo_to_pat
)

COMPONENT_WEIGHTS = {
    "growth": 20,
    "profitability": 20,
    "balance_sheet": 15,
    "cash_flow": 15,
    "valuation": 20,
    "quality": 10,      # still pending — needs earnings-quality-flag-to-score mapping
}


def _bucket_score(value: float | None, thresholds: list[tuple[float, int]], default: int = 50) -> int:
    if value is None:
        return default
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return thresholds[-1][1] if thresholds else default


def score_growth(revenue_cagr: float | None, revenue_yoy: float | None) -> dict:
    cagr_score = _bucket_score(revenue_cagr, [
        (0.20, 100), (0.15, 85), (0.10, 70), (0.05, 55), (0.0, 40), (-1.0, 20)
    ])
    yoy_score = _bucket_score(revenue_yoy, [
        (0.20, 100), (0.15, 85), (0.10, 70), (0.05, 55), (0.0, 40), (-1.0, 20)
    ])

    available = [s for s, v in [(cagr_score, revenue_cagr), (yoy_score, revenue_yoy)] if v is not None]
    score = round(sum(available) / len(available)) if available else None

    rationale = [
        f"3yr revenue CAGR: {revenue_cagr:.1%}" if revenue_cagr is not None else "3yr revenue CAGR: N/A",
        f"Latest YoY revenue growth: {revenue_yoy:.1%}" if revenue_yoy is not None else "Latest YoY revenue growth: N/A",
    ]
    return {"score": score, "rationale": rationale}


def score_profitability(metrics: dict) -> dict:
    nm, r_oe, r_oce = net_margin(metrics), roe(metrics), roce(metrics)

    nm_score = _bucket_score(nm, [(0.20, 100), (0.15, 85), (0.10, 70), (0.05, 55), (0.0, 40), (-1.0, 20)])
    roe_score = _bucket_score(r_oe, [(0.20, 100), (0.15, 85), (0.10, 70), (0.05, 55), (0.0, 40), (-1.0, 20)])
    roce_score = _bucket_score(r_oce, [(0.20, 100), (0.15, 85), (0.10, 70), (0.05, 55), (0.0, 40), (-1.0, 20)])

    parts = [(nm_score, nm), (roe_score, r_oe), (roce_score, r_oce)]
    available = [s for s, v in parts if v is not None]
    score = round(sum(available) / len(available)) if available else None

    rationale = [
        f"Net margin: {nm:.1%}" if nm is not None else "Net margin: N/A",
        f"ROE: {r_oe:.1%}" if r_oe is not None else "ROE: N/A",
        f"ROCE: {r_oce:.1%}" if r_oce is not None else "ROCE: N/A",
    ]
    return {"score": score, "rationale": rationale}


def score_balance_sheet(metrics: dict) -> dict:
    de, ic, cr = debt_to_equity(metrics), interest_coverage(metrics), current_ratio(metrics)

    de_score = _bucket_score(-de if de is not None else None, [
        (-0.0, 100), (-0.5, 80), (-1.0, 60), (-2.0, 40), (-1e9, 20)
    ]) if de is not None else None
    ic_score = _bucket_score(ic, [(10, 100), (5, 80), (3, 60), (1.5, 40), (0, 20)])
    cr_score = _bucket_score(cr, [(2.0, 100), (1.5, 85), (1.0, 65), (0.5, 40), (0, 20)])

    parts = [(de_score, de), (ic_score, ic), (cr_score, cr)]
    available = [s for s, v in parts if v is not None and s is not None]
    score = round(sum(available) / len(available)) if available else None

    rationale = [
        f"Debt-to-Equity: {de:.2f}" if de is not None else "Debt-to-Equity: N/A",
        f"Interest Coverage: {ic:.1f}x" if ic is not None else "Interest Coverage: N/A",
        f"Current Ratio: {cr:.2f}" if cr is not None else "Current Ratio: N/A",
    ]
    return {"score": score, "rationale": rationale}


def score_cash_flow(metrics: dict) -> dict:
    ratio = cfo_to_pat(metrics)

    if ratio is None:
        score = None
    elif 0.8 <= ratio <= 1.5:
        score = 100
    elif 0.5 <= ratio < 0.8 or 1.5 < ratio <= 2.5:
        score = 70
    elif ratio < 0.5:
        score = 30
    else:
        score = 55

    rationale = [f"CFO/PAT: {ratio:.2f}" if ratio is not None else "CFO/PAT: N/A"]
    return {"score": score, "rationale": rationale}


def score_valuation(base_case_upside_pct: float | None) -> dict:
    """
    Scores based on the DCF Base-case upside/downside (Phase 5).
    Higher upside (undervalued relative to DCF fair value) scores higher.
    Not a recommendation — a transparent input to the composite score.
    """
    score = _bucket_score(base_case_upside_pct, [
        (0.30, 100), (0.15, 85), (0.0, 70), (-0.15, 50), (-0.30, 30), (-1.0, 15)
    ])
    rationale = [
        f"DCF Base-case upside/downside: {base_case_upside_pct:.1%}"
        if base_case_upside_pct is not None else "DCF Base-case upside/downside: N/A"
    ]
    return {"score": score, "rationale": rationale}


def calculate_fundamental_score(
    metrics: dict, revenue_cagr: float | None, revenue_yoy: float | None,
    valuation_upside_pct: float | None = None
) -> dict:
    """
    Returns full auditable breakdown: each component's score, weight,
    weighted contribution, and rationale. Quality remains 'pending' with
    weight excluded from the current total — never guessed. Valuation is
    scored when valuation_upside_pct is supplied (Phase 5 price targets);
    otherwise remains pending too, so older callers keep working unchanged.
    """
    valuation_component = (
        score_valuation(valuation_upside_pct) if valuation_upside_pct is not None
        else {"score": None, "rationale": ["Pending — no DCF valuation data supplied"]}
    )

    components = {
        "growth": score_growth(revenue_cagr, revenue_yoy),
        "profitability": score_profitability(metrics),
        "balance_sheet": score_balance_sheet(metrics),
        "cash_flow": score_cash_flow(metrics),
        "valuation": valuation_component,
        "quality": {"score": None, "rationale": ["Pending — requires earnings-quality-flag-to-score mapping"]},
    }

    weighted_sum = 0.0
    weight_used = 0.0
    breakdown = {}

    for name, weight in COMPONENT_WEIGHTS.items():
        comp = components[name]
        score = comp["score"]
        contribution = (score * weight / 100) if score is not None else None
        breakdown[name] = {
            "score": score,
            "weight_pct": weight,
            "weighted_contribution": round(contribution, 2) if contribution is not None else None,
            "rationale": comp["rationale"],
        }
        if score is not None:
            weighted_sum += contribution
            weight_used += weight

    total_score = round(weighted_sum / weight_used * 100, 1) if weight_used > 0 else None

    return {
        "components": breakdown,
        "total_score_available_weight_only": total_score,
        "weight_used_pct": weight_used,
        "weight_pending_pct": 100 - weight_used,
        "note": (
            f"Total score is based on {weight_used}% of full weighting "
            f"(remaining components pending)."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company
    from app.screener.metric_aggregator import (
        get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
    )
    from app.valuation.price_targets import generate_price_targets

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found — run scripts/load_company.py first")
    else:
        metrics = get_latest_metrics_bulk(session, company.id)
        revenue_cagr = calculate_metric_cagr(session, company.id, "revenue", years=3)
        revenue_yoy = calculate_yoy_growth(session, company.id, "revenue")

        price_targets = generate_price_targets(session, company)
        valuation_upside = None
        if price_targets["available"] and price_targets["targets"]["base"]["available"]:
            valuation_upside = price_targets["targets"]["base"]["upside_pct"]

        result = calculate_fundamental_score(metrics, revenue_cagr, revenue_yoy, valuation_upside)
        print(f"Fundamental Score for {company.name} (now including Valuation)\n")
        for name, comp in result["components"].items():
            print(f"[{name.upper()}] weight={comp['weight_pct']}% score={comp['score']} "
                  f"contribution={comp['weighted_contribution']}")
            for r in comp["rationale"]:
                print(f"    - {r}")
        print(f"\nTotal (available weight only): {result['total_score_available_weight_only']}")
        print(result["note"])

    session.close()