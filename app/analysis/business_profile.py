"""
Business & industry analysis (project spec Section 7).
Descriptive layer: business model, geography, sector/industry
positioning, scale (employee count). Combines live yfinance metadata
with our own peer-count context.

This is intentionally descriptive, not scored — competitive advantage
and regulatory risk assessment need qualitative judgment or richer
disclosure data (10-K/annual-report style text), which belongs in
Phase 8's RAG/document system rather than being guessed here.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.data.providers.yfinance_provider import fetch_business_profile
from app.analysis.peer_comparison import find_peers


def build_business_industry_profile(session: Session, company: Company) -> dict:
    """
    Assembles the descriptive business/industry summary for one company.
    Any field yfinance doesn't provide is explicitly marked "not available"
    rather than left silently blank — consistent with the project's
    never-fabricate-data principle.
    """
    live_profile = fetch_business_profile(company.ticker)
    peers = find_peers(session, company)

    def _or_na(value):
        return value if value not in (None, "", 0) else "Not available"

    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": _or_na(company.sector),
        "industry": _or_na(company.industry),
        "country": _or_na(live_profile.get("country")),
        "headquarters_city": _or_na(live_profile.get("city")),
        "employees": _or_na(live_profile.get("full_time_employees")),
        "business_summary": _or_na(live_profile.get("business_summary")),
        "peer_count_in_sector": len(peers),
        "peer_tickers": [p.ticker for p in peers],
        "notes": [
            "Competitive advantage and regulatory risk assessment require "
            "qualitative analysis of disclosures (10-K/annual report text) — "
            "planned for Phase 8 (RAG/document system), not fabricated here.",
            "Revenue segment breakdown and customer/supplier concentration "
            "require structured segment data not available from this data "
            "source; noted as a known limitation.",
        ],
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        profile = build_business_industry_profile(session, company)
        print(f"Business & Industry Profile: {profile['name']} ({profile['ticker']})\n")
        print(f"Sector: {profile['sector']}")
        print(f"Industry: {profile['industry']}")
        print(f"Country: {profile['country']}")
        print(f"HQ City: {profile['headquarters_city']}")
        print(f"Employees: {profile['employees']}")
        print(f"Peers in sector: {profile['peer_count_in_sector']} ({profile['peer_tickers']})")
        print(f"\nBusiness Summary:\n{profile['business_summary'][:500]}...")
        print("\nLimitations noted:")
        for n in profile["notes"]:
            print(f"  - {n}")

    session.close()