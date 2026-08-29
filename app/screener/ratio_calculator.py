"""
Ratio calculators covering Growth | Profitability | Balance Sheet | Cash Flow
(project spec Section 6). Each function returns None (not 0 or a guess) when
required inputs are missing — matches the "never fabricate data" rule.

Accepts a pre-fetched metrics dict (from get_latest_metrics_bulk) instead of
querying the DB per ratio — critical for screener performance across many
companies.
"""


def gross_margin(metrics: dict) -> float | None:
    revenue, gross_profit = metrics.get("revenue"), metrics.get("gross_profit")
    if not revenue or gross_profit is None:
        return None
    return gross_profit / revenue


def ebitda_margin(metrics: dict) -> float | None:
    revenue, ebitda = metrics.get("revenue"), metrics.get("ebitda")
    if not revenue or ebitda is None:
        return None
    return ebitda / revenue


def net_margin(metrics: dict) -> float | None:
    revenue, net_income = metrics.get("revenue"), metrics.get("net_income")
    if not revenue or net_income is None:
        return None
    return net_income / revenue


def roe(metrics: dict) -> float | None:
    net_income, equity = metrics.get("net_income"), metrics.get("total_equity")
    if not equity or net_income is None:
        return None
    return net_income / equity


def roa(metrics: dict) -> float | None:
    net_income, assets = metrics.get("net_income"), metrics.get("total_assets")
    if not assets or net_income is None:
        return None
    return net_income / assets


def roce(metrics: dict) -> float | None:
    ebit = metrics.get("ebit")
    assets = metrics.get("total_assets")
    current_liabilities = metrics.get("current_liabilities")
    if ebit is None or assets is None or current_liabilities is None:
        return None
    capital_employed = assets - current_liabilities
    if capital_employed == 0:
        return None
    return ebit / capital_employed


def debt_to_equity(metrics: dict) -> float | None:
    debt, equity = metrics.get("total_debt"), metrics.get("total_equity")
    if not equity or debt is None:
        return None
    return debt / equity


def interest_coverage(metrics: dict) -> float | None:
    ebit, interest = metrics.get("ebit"), metrics.get("interest_expense")
    if not interest or ebit is None:
        return None
    return ebit / abs(interest)


def current_ratio(metrics: dict) -> float | None:
    current_assets = metrics.get("current_assets")
    current_liabilities = metrics.get("current_liabilities")
    if not current_liabilities or current_assets is None:
        return None
    return current_assets / current_liabilities


def cfo_to_pat(metrics: dict) -> float | None:
    cfo, pat = metrics.get("operating_cash_flow"), metrics.get("net_income")
    if not pat or cfo is None:
        return None
    return cfo / pat


def calculate_all_ratios(metrics: dict) -> dict:
    """Convenience: compute every ratio at once from a pre-fetched metrics dict."""
    return {
        "gross_margin": gross_margin(metrics),
        "ebitda_margin": ebitda_margin(metrics),
        "net_margin": net_margin(metrics),
        "roe": roe(metrics),
        "roa": roa(metrics),
        "roce": roce(metrics),
        "debt_to_equity": debt_to_equity(metrics),
        "interest_coverage": interest_coverage(metrics),
        "current_ratio": current_ratio(metrics),
        "cfo_to_pat": cfo_to_pat(metrics),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company
    from app.screener.metric_aggregator import get_latest_metrics_bulk

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found — run scripts/load_company.py first")
    else:
        metrics = get_latest_metrics_bulk(session, company.id)
        print(f"Ratios for {company.name}:\n")
        ratios = calculate_all_ratios(metrics)
        for name, value in ratios.items():
            if value is not None:
                print(f"  {name}: {value:.4f}")
            else:
                print(f"  {name}: N/A (missing data)")

    session.close()