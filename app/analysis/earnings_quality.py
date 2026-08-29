"""
Earnings-quality / forensic warning flags (project spec Section 9).
Descriptive signals only — never accusatory, never a fraud determination.
Persists to the data_quality_flags table (Phase 1 schema).

Flags implemented (scoped to what our current data sources genuinely
support well): CFO/PAT divergence, weak FCF conversion, margin anomaly
(sudden drop vs recent average), debt growth materially outpacing
earnings growth. Additional flags (receivables/inventory anomalies,
promoter pledge, contingent liabilities) require richer disclosure data
and are deferred to Phase 8 (RAG/document system).

IMPORTANT: For banks/NBFCs, negative operating cash flow and rising
"debt" (deposits/borrowings funding loans) are structurally normal —
not earnings-quality warning signs. Generic CFO/FCF/debt-growth checks
are suppressed for financial-sector companies; proper analysis needs
sector-specific metrics (NIM, GNPA, capital adequacy), planned for a
later phase per spec Section 8.
"""
from datetime import date
from sqlalchemy.orm import Session
from app.data.models import Company, DataQualityFlag
from app.screener.metric_aggregator import get_latest_metrics_bulk, calculate_metric_cagr, get_metric_series
from app.screener.ratio_calculator import cfo_to_pat, net_margin

FINANCIAL_SECTORS = {"Financial Services", "Financials", "Banks", "Banking"}


def _is_financial_company(company: Company) -> bool:
    return (company.sector or "") in FINANCIAL_SECTORS


def check_cfo_pat_divergence(metrics: dict) -> dict | None:
    """CFO significantly below PAT suggests profits aren't converting to cash."""
    ratio = cfo_to_pat(metrics)
    if ratio is None:
        return None
    if ratio < 0.5:
        return {
            "flag_type": "cfo_pat_divergence",
            "severity": "high" if ratio < 0.2 else "warning",
            "description": (
                f"Operating cash flow is only {ratio:.1f}x profit after tax. "
                f"Profits are not fully converting into cash — worth examining "
                f"working capital changes and accrual items."
            ),
        }
    return None


def check_weak_fcf_conversion(metrics: dict) -> dict | None:
    """Free cash flow much lower than net income can signal heavy capex or working-capital drag."""
    fcf = metrics.get("free_cash_flow")
    pat = metrics.get("net_income")
    if fcf is None or not pat or pat <= 0:
        return None
    ratio = fcf / pat
    if ratio < 0.3:
        return {
            "flag_type": "weak_fcf_conversion",
            "severity": "warning",
            "description": (
                f"Free cash flow is only {ratio:.1f}x net income. "
                f"Could reflect heavy capital expenditure or working-capital needs — "
                f"not necessarily negative, but worth understanding the cause."
            ),
        }
    return None


def check_margin_anomaly(session: Session, company_id: int) -> dict | None:
    """Flags a sharp, sudden drop in net margin vs the recent 3-year average."""
    series = get_metric_series(session, company_id, "net_income", limit=4)
    revenue_series = get_metric_series(session, company_id, "revenue", limit=4)

    if len(series) < 4 or len(revenue_series) < 4:
        return None

    margins = []
    for ni, rev in zip(series, revenue_series):
        if rev["value"] and rev["value"] != 0:
            margins.append(ni["value"] / rev["value"])

    if len(margins) < 4:
        return None

    historical_avg = sum(margins[:-1]) / len(margins[:-1])
    latest = margins[-1]

    if historical_avg > 0 and latest < historical_avg * 0.6:
        drop_pct = (1 - latest / historical_avg) * 100
        return {
            "flag_type": "margin_anomaly",
            "severity": "warning",
            "description": (
                f"Latest net margin ({latest:.1%}) is {drop_pct:.0f}% below the "
                f"prior 3-year average ({historical_avg:.1%}). Worth checking for "
                f"one-off items, sector headwinds, or a genuine profitability shift."
            ),
        }
    return None


def check_debt_growth_vs_earnings(session: Session, company_id: int) -> dict | None:
    """Flags when debt is growing meaningfully faster than earnings."""
    debt_cagr = calculate_metric_cagr(session, company_id, "total_debt", years=3)
    earnings_cagr = calculate_metric_cagr(session, company_id, "net_income", years=3)

    if debt_cagr is None or earnings_cagr is None:
        return None

    if debt_cagr > 0.15 and debt_cagr > earnings_cagr + 0.10:
        return {
            "flag_type": "debt_growth_outpacing_earnings",
            "severity": "warning",
            "description": (
                f"Debt has grown at {debt_cagr:.1%}/yr over 3 years, notably faster "
                f"than earnings growth of {earnings_cagr:.1%}/yr. Worth monitoring "
                f"leverage trend and the purpose of the borrowed capital."
            ),
        }
    return None


def detect_earnings_quality_flags(session: Session, company: Company) -> list[dict]:
    """
    Runs all available checks for one company, returns list of flag dicts
    (may be empty). CFO/FCF/debt-growth checks are skipped for banks/NBFCs,
    where those patterns are structurally normal rather than warning signs.
    """
    metrics = get_latest_metrics_bulk(session, company.id)
    flags = []
    is_financial = _is_financial_company(company)

    if not is_financial:
        for check_fn in [check_cfo_pat_divergence, check_weak_fcf_conversion]:
            result = check_fn(metrics)
            if result:
                flags.append(result)

        result = check_debt_growth_vs_earnings(session, company.id)
        if result:
            flags.append(result)
    else:
        flags.append({
            "flag_type": "sector_specific_analysis_pending",
            "severity": "info",
            "description": (
                "This is a financial-sector company (bank/NBFC). Generic cash-flow "
                "and debt-growth checks don't apply here — proper analysis needs "
                "sector-specific metrics (NIM, GNPA, capital adequacy), planned for "
                "a later phase."
            ),
        })

    # Margin anomaly check is still meaningful for financial companies
    result = check_margin_anomaly(session, company.id)
    if result:
        flags.append(result)

    return flags


def save_flags(session: Session, company: Company, flags: list[dict], period_end_date: date | None = None):
    """Replaces existing flags for this company with freshly computed ones."""
    session.query(DataQualityFlag).filter_by(company_id=company.id).delete()
    for f in flags:
        session.add(DataQualityFlag(
            company_id=company.id,
            flag_type=f["flag_type"],
            period_end_date=period_end_date,
            severity=f["severity"],
            description=f["description"],
        ))
    session.commit()


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()

    companies = session.query(Company).all()
    total_flags = 0

    for company in companies:
        flags = detect_earnings_quality_flags(session, company)
        if flags:
            print(f"\n{company.ticker} — {company.name} (sector: {company.sector})")
            for f in flags:
                print(f"  [{f['severity'].upper()}] {f['flag_type']}: {f['description']}")
            save_flags(session, company, flags)
            total_flags += len(flags)

    print(f"\n\nTotal flags found across {len(companies)} companies: {total_flags}")
    session.close()