"""
Ratio calculators covering Growth | Profitability | Balance Sheet | Cash Flow
(project spec Section 6). Each function returns None (not 0 or a guess) when
required inputs are missing — matches the "never fabricate data" rule.
"""
from sqlalchemy.orm import Session
from app.screener.metric_aggregator import get_latest_metric


def _val(session: Session, company_id: int, canonical_name: str, period_type: str = "annual"):
    """Shortcut: get just the numeric value, or None if unavailable."""
    result = get_latest_metric(session, company_id, canonical_name, period_type)
    return result["value"] if result else None


def gross_margin(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    revenue = _val(session, company_id, "revenue", period_type)
    gross_profit = _val(session, company_id, "gross_profit", period_type)
    if revenue in (None, 0) or gross_profit is None:
        return None
    return gross_profit / revenue


def ebitda_margin(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    revenue = _val(session, company_id, "revenue", period_type)
    ebitda = _val(session, company_id, "ebitda", period_type)
    if revenue in (None, 0) or ebitda is None:
        return None
    return ebitda / revenue


def net_margin(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    revenue = _val(session, company_id, "revenue", period_type)
    net_income = _val(session, company_id, "net_income", period_type)
    if revenue in (None, 0) or net_income is None:
        return None
    return net_income / revenue


def roe(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    """Return on Equity = Net Income / Total Equity."""
    net_income = _val(session, company_id, "net_income", period_type)
    equity = _val(session, company_id, "total_equity", period_type)
    if equity in (None, 0) or net_income is None:
        return None
    return net_income / equity


def roa(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    """Return on Assets = Net Income / Total Assets."""
    net_income = _val(session, company_id, "net_income", period_type)
    assets = _val(session, company_id, "total_assets", period_type)
    if assets in (None, 0) or net_income is None:
        return None
    return net_income / assets


def roce(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    """
    Return on Capital Employed = EBIT / Capital Employed.
    Capital Employed = Total Assets - Current Liabilities.
    """
    ebit = _val(session, company_id, "ebit", period_type)
    assets = _val(session, company_id, "total_assets", period_type)
    current_liabilities = _val(session, company_id, "current_liabilities", period_type)
    if ebit is None or assets is None or current_liabilities is None:
        return None
    capital_employed = assets - current_liabilities
    if capital_employed == 0:
        return None
    return ebit / capital_employed


def debt_to_equity(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    debt = _val(session, company_id, "total_debt", period_type)
    equity = _val(session, company_id, "total_equity", period_type)
    if equity in (None, 0) or debt is None:
        return None
    return debt / equity


def interest_coverage(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    """EBIT / Interest Expense. Higher is safer (more cushion to service debt)."""
    ebit = _val(session, company_id, "ebit", period_type)
    interest = _val(session, company_id, "interest_expense", period_type)
    if interest in (None, 0) or ebit is None:
        return None
    return ebit / abs(interest)


def current_ratio(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    current_assets = _val(session, company_id, "current_assets", period_type)
    current_liabilities = _val(session, company_id, "current_liabilities", period_type)
    if current_liabilities in (None, 0) or current_assets is None:
        return None
    return current_assets / current_liabilities


def cfo_to_pat(session: Session, company_id: int, period_type: str = "annual") -> float | None:
    """
    Cash Flow from Operations / Profit After Tax.
    Earnings-quality signal (spec Section 9): low ratio suggests profits
    aren't translating into actual cash.
    """
    cfo = _val(session, company_id, "operating_cash_flow", period_type)
    pat = _val(session, company_id, "net_income", period_type)
    if pat in (None, 0) or cfo is None:
        return None
    return cfo / pat


def calculate_all_ratios(session: Session, company_id: int, period_type: str = "annual") -> dict:
    """Convenience: compute every ratio at once, returned as a dict."""
    return {
        "gross_margin": gross_margin(session, company_id, period_type),
        "ebitda_margin": ebitda_margin(session, company_id, period_type),
        "net_margin": net_margin(session, company_id, period_type),
        "roe": roe(session, company_id, period_type),
        "roa": roa(session, company_id, period_type),
        "roce": roce(session, company_id, period_type),
        "debt_to_equity": debt_to_equity(session, company_id, period_type),
        "interest_coverage": interest_coverage(session, company_id, period_type),
        "current_ratio": current_ratio(session, company_id, period_type),
        "cfo_to_pat": cfo_to_pat(session, company_id, period_type),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal
    from app.data.models import Company

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found — run scripts/load_company.py first")
    else:
        print(f"Ratios for {company.name}:\n")
        ratios = calculate_all_ratios(session, company.id)
        for name, value in ratios.items():
            if value is not None:
                print(f"  {name}: {value:.4f}")
            else:
                print(f"  {name}: N/A (missing data)")

    session.close()