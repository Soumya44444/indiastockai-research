"""
Forecast engine (project spec Section 12): projects Revenue -> EBITDA ->
EBIT -> PAT -> Free Cash Flow for Bear/Base/Bull scenarios over a chosen
horizon. Every derived ratio (D&A%, tax rate, capex%) is computed from
historical actuals and shown alongside the output — never a hidden
hard-coded assumption.
"""
from sqlalchemy.orm import Session
from app.forecasting.assumptions import build_forecast_assumptions
from app.screener.metric_aggregator import get_latest_metrics_bulk, get_metric_series


def _derive_supporting_ratios(session: Session, company_id: int) -> dict:
    """
    Derives D&A-as-%-of-revenue, effective tax rate, and capex-as-%-of-revenue
    from the latest available historicals, held constant across the forecast
    horizon (a simplifying assumption, disclosed explicitly).
    """
    metrics = get_latest_metrics_bulk(session, company_id)

    revenue = metrics.get("revenue")
    ebitda = metrics.get("ebitda")
    ebit = metrics.get("ebit")
    pretax_income = metrics.get("pretax_income")
    tax_provision = metrics.get("tax_provision")
    operating_cash_flow = metrics.get("operating_cash_flow")
    free_cash_flow = metrics.get("free_cash_flow")

    da_pct_revenue = None
    if revenue and ebitda is not None and ebit is not None:
        da_pct_revenue = (ebitda - ebit) / revenue

    effective_tax_rate = None
    if pretax_income and tax_provision is not None and pretax_income != 0:
        effective_tax_rate = tax_provision / pretax_income

    capex_pct_revenue = None
    if revenue and operating_cash_flow is not None and free_cash_flow is not None:
        capex = operating_cash_flow - free_cash_flow
        capex_pct_revenue = capex / revenue

    return {
        "da_pct_revenue": da_pct_revenue,
        "effective_tax_rate": effective_tax_rate,
        "capex_pct_revenue": capex_pct_revenue,
        "base_revenue": revenue,
    }


def _project_scenario(base_revenue: float, revenue_growth: float, ebitda_margin: float,
                       da_pct_revenue: float, tax_rate: float, capex_pct_revenue: float,
                       years: int) -> list[dict]:
    """Projects one scenario forward year-by-year."""
    projection = []
    revenue = base_revenue

    for year in range(1, years + 1):
        revenue = revenue * (1 + revenue_growth)
        ebitda = revenue * ebitda_margin
        da = revenue * da_pct_revenue if da_pct_revenue is not None else None
        ebit = (ebitda - da) if da is not None else None
        pat = (ebit * (1 - tax_rate)) if (ebit is not None and tax_rate is not None) else None
        capex = revenue * capex_pct_revenue if capex_pct_revenue is not None else None
        # Simplified FCF: EBITDA - Tax (approx via PAT-based tax) - Capex.
        # Working-capital changes are handled separately in Step 3.
        fcf = None
        if ebitda is not None and capex is not None and tax_rate is not None and ebit is not None:
            tax_amount = ebit * tax_rate
            fcf = ebitda - max(tax_amount, 0) - capex

        projection.append({
            "year": year,
            "revenue": round(revenue, 0),
            "ebitda": round(ebitda, 0) if ebitda is not None else None,
            "ebit": round(ebit, 0) if ebit is not None else None,
            "pat": round(pat, 0) if pat is not None else None,
            "fcf": round(fcf, 0) if fcf is not None else None,
        })

    return projection


def generate_forecast(session: Session, company_id: int, years: int = 3) -> dict:
    """
    Full Bear/Base/Bull forecast for a company. Returns None-safe results
    when historical data is insufficient — never fabricates a forecast
    from nothing.
    """
    assumptions = build_forecast_assumptions(session, company_id)
    if not assumptions["available"]:
        return {"available": False, "reason": assumptions["reason"]}

    supporting = _derive_supporting_ratios(session, company_id)
    if supporting["base_revenue"] is None:
        return {"available": False, "reason": "No base revenue figure available to forecast from."}

    forecasts = {}
    for scenario_name, scenario_assumptions in assumptions["scenarios"].items():
        forecasts[scenario_name] = _project_scenario(
            base_revenue=supporting["base_revenue"],
            revenue_growth=scenario_assumptions["revenue_growth"],
            ebitda_margin=scenario_assumptions["ebitda_margin"],
            da_pct_revenue=supporting["da_pct_revenue"],
            tax_rate=supporting["effective_tax_rate"],
            capex_pct_revenue=supporting["capex_pct_revenue"],
            years=years,
        )

    return {
        "available": True,
        "years": years,
        "forecasts": forecasts,
        "supporting_ratios": supporting,
        "scenario_assumptions": assumptions["scenarios"],
        "methodology_note": (
            assumptions["methodology_note"] + " D&A%, effective tax rate, and "
            "capex% are held constant at the latest historical level across "
            "the forecast horizon (simplifying assumption). Working-capital "
            "changes are not yet included in this FCF figure — see Phase 4 "
            "Step 3."
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
        result = generate_forecast(session, company.id, years=3)
        print(f"3-Year Forecast for {company.name}\n")

        if not result["available"]:
            print(f"NOT AVAILABLE: {result['reason']}")
        else:
            print("Supporting ratios (held constant):")
            for k, v in result["supporting_ratios"].items():
                print(f"  {k}: {v}")

            for scenario, years_data in result["forecasts"].items():
                print(f"\n[{scenario.upper()}]")
                for y in years_data:
                    print(f"  Year {y['year']}: Revenue={y['revenue']:,.0f}  EBITDA={y['ebitda']}  "
                          f"EBIT={y['ebit']}  PAT={y['pat']}  FCF={y['fcf']}")

            print(f"\n{result['methodology_note']}")

    session.close()