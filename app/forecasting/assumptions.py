"""
Forecast assumption builder (project spec Section 12).
Derives explicit, visible Bear/Base/Bull assumptions from historical
data rather than hard-coding guesses. Every assumption is traceable
back to the historical figure it was derived from.
"""
from sqlalchemy.orm import Session
from app.screener.metric_aggregator import get_metric_series, calculate_cagr
from app.screener.ratio_calculator import ebitda_margin, net_margin


def _historical_growth_stats(session: Session, company_id: int, canonical_name: str, years: int = 5) -> dict:
    """
    Computes historical CAGR and year-over-year growth rates for a metric,
    used as the basis for forward assumptions.
    """
    series = get_metric_series(session, company_id, canonical_name, limit=years)
    if len(series) < 2:
        return {"cagr": None, "yoy_rates": [], "avg_yoy": None, "data_points": len(series)}

    yoy_rates = []
    for i in range(1, len(series)):
        prev, curr = series[i - 1]["value"], series[i]["value"]
        if prev and prev != 0:
            yoy_rates.append((curr - prev) / abs(prev))

    span_years = (series[-1]["period_end_date"] - series[0]["period_end_date"]).days / 365.25
    cagr = calculate_cagr(series[0]["value"], series[-1]["value"], span_years)
    avg_yoy = sum(yoy_rates) / len(yoy_rates) if yoy_rates else None

    return {"cagr": cagr, "yoy_rates": yoy_rates, "avg_yoy": avg_yoy, "data_points": len(series)}


def _historical_margin_stats(session: Session, company_id: int) -> dict:
    """Average and most-recent EBITDA/net margin, used to project forward margins."""
    revenue_series = get_metric_series(session, company_id, "revenue", limit=5)
    ebitda_series = get_metric_series(session, company_id, "ebitda", limit=5)

    margins = []
    for rev, ebitda in zip(revenue_series, ebitda_series):
        if rev["value"] and rev["value"] != 0:
            margins.append(ebitda["value"] / rev["value"])

    if not margins:
        return {"avg_ebitda_margin": None, "latest_ebitda_margin": None}

    return {
        "avg_ebitda_margin": sum(margins) / len(margins),
        "latest_ebitda_margin": margins[-1],
    }


def build_forecast_assumptions(session: Session, company_id: int) -> dict:
    """
    Builds Bear/Base/Bull assumptions for revenue growth and EBITDA margin,
    explicitly derived from historical data — with the historical basis
    shown alongside each assumption (never a bare number with no justification).
    """
    revenue_stats = _historical_growth_stats(session, company_id, "revenue", years=5)
    margin_stats = _historical_margin_stats(session, company_id)

    base_growth = revenue_stats["avg_yoy"] if revenue_stats["avg_yoy"] is not None else revenue_stats["cagr"]
    base_margin = margin_stats["avg_ebitda_margin"]

    if base_growth is None or base_margin is None:
        return {
            "available": False,
            "reason": "Insufficient historical data (need at least 2 years of revenue and EBITDA history)",
            "historical_basis": {"revenue_growth": revenue_stats, "margin": margin_stats},
        }

    # Scenario construction: Bear/Bull are offsets from the historically-derived
    # Base case, not arbitrary guesses. Offsets are conservative and disclosed.
    scenarios = {
        "bear": {
            "revenue_growth": round(base_growth - 0.05, 4),
            "ebitda_margin": round(max(base_margin - 0.02, 0.0), 4),
        },
        "base": {
            "revenue_growth": round(base_growth, 4),
            "ebitda_margin": round(base_margin, 4),
        },
        "bull": {
            "revenue_growth": round(base_growth + 0.05, 4),
            "ebitda_margin": round(base_margin + 0.02, 4),
        },
    }

    return {
        "available": True,
        "scenarios": scenarios,
        "historical_basis": {
            "revenue_avg_yoy_growth": revenue_stats["avg_yoy"],
            "revenue_cagr": revenue_stats["cagr"],
            "revenue_data_points": revenue_stats["data_points"],
            "avg_ebitda_margin": margin_stats["avg_ebitda_margin"],
            "latest_ebitda_margin": margin_stats["latest_ebitda_margin"],
        },
        "methodology_note": (
            "Base case = historical average YoY revenue growth and average EBITDA "
            "margin over available history. Bear = Base minus 5pp growth / 2pp margin. "
            "Bull = Base plus 5pp growth / 2pp margin. These are illustrative "
            "scenario offsets, not predictions."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = build_forecast_assumptions(session, company.id)
        print(f"Forecast assumptions for {company.name}\n")
        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            for scenario, vals in result["scenarios"].items():
                print(f"[{scenario.upper()}] Revenue growth: {vals['revenue_growth']:.1%}, "
                      f"EBITDA margin: {vals['ebitda_margin']:.1%}")
            print(f"\nHistorical basis: {result['historical_basis']}")
            print(f"\n{result['methodology_note']}")

    session.close()