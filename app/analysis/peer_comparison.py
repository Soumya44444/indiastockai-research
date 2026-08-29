"""
Peer comparison engine (project spec Section 11).
Auto-identifies peers by sector, then compares growth, profitability,
leverage, cash flow, and valuation multiples — explaining relative
strengths/weaknesses rather than just dumping numbers.
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.screener.metric_aggregator import get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
from app.screener.ratio_calculator import calculate_all_ratios


def find_peers(session: Session, company: Company, max_peers: int = 8) -> list[Company]:
    """
    Auto-identifies peers: same sector, excluding the company itself.
    Simple rule for now — sector match is what our data currently supports;
    industry-level matching can be added once more granular data exists.
    """
    if not company.sector:
        return []

    peers = (
        session.query(Company)
        .filter(Company.sector == company.sector, Company.id != company.id)
        .limit(max_peers)
        .all()
    )
    return peers


def build_comparison_profile(session: Session, company: Company) -> dict:
    """Metrics + ratios needed for peer comparison, for one company."""
    metrics = get_latest_metrics_bulk(session, company.id)
    ratios = calculate_all_ratios(metrics)
    revenue_cagr = calculate_metric_cagr(session, company.id, "revenue", years=3)
    revenue_yoy = calculate_yoy_growth(session, company.id, "revenue")

    return {
        "ticker": company.ticker,
        "name": company.name,
        "market_cap_proxy": metrics.get("total_assets"),  # placeholder until real market cap wired in
        "revenue": metrics.get("revenue"),
        "revenue_cagr_3y": revenue_cagr,
        "revenue_yoy": revenue_yoy,
        **ratios,
    }


def _rank_and_compare(target: dict, peers: list[dict], field: str, higher_is_better: bool = True) -> dict:
    """
    Ranks target company among itself + peers on one field.
    Returns rank, total count, and a plain-language relative position.
    """
    all_profiles = [target] + peers
    valid = [(p["ticker"], p[field]) for p in all_profiles if p.get(field) is not None]

    if len(valid) < 2 or target.get(field) is None:
        return {"field": field, "rank": None, "total": len(valid), "position": "insufficient data"}

    valid.sort(key=lambda x: x[1], reverse=higher_is_better)
    rank = next(i for i, (ticker, _) in enumerate(valid, start=1) if ticker == target["ticker"])
    total = len(valid)

    if rank == 1:
        position = "best in peer group"
    elif rank <= max(1, total // 3):
        position = "above average"
    elif rank <= max(1, 2 * total // 3):
        position = "average"
    else:
        position = "below average"

    return {"field": field, "rank": rank, "total": total, "position": position}


def compare_to_peers(session: Session, company: Company, max_peers: int = 8) -> dict:
    """
    Full peer comparison: target company's ranking across key metrics
    relative to its sector peers, with a plain-language summary per metric.
    """
    peers = find_peers(session, company, max_peers)
    target_profile = build_comparison_profile(session, company)
    peer_profiles = [build_comparison_profile(session, p) for p in peers]

    comparisons = [
        _rank_and_compare(target_profile, peer_profiles, "revenue_cagr_3y", higher_is_better=True),
        _rank_and_compare(target_profile, peer_profiles, "net_margin", higher_is_better=True),
        _rank_and_compare(target_profile, peer_profiles, "roe", higher_is_better=True),
        _rank_and_compare(target_profile, peer_profiles, "roce", higher_is_better=True),
        _rank_and_compare(target_profile, peer_profiles, "debt_to_equity", higher_is_better=False),
        _rank_and_compare(target_profile, peer_profiles, "cfo_to_pat", higher_is_better=True),
    ]

    return {
        "company": target_profile["ticker"],
        "sector": company.sector,
        "peer_count": len(peer_profiles),
        "peers": [p["ticker"] for p in peer_profiles],
        "comparisons": comparisons,
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = compare_to_peers(session, company)
        print(f"Peer comparison for {result['company']} (sector: {result['sector']})")
        print(f"Peers ({result['peer_count']}): {result['peers']}\n")
        for c in result["comparisons"]:
            rank_str = f"{c['rank']}/{c['total']}" if c["rank"] else "N/A"
            print(f"  {c['field']}: rank {rank_str} — {c['position']}")

    session.close()