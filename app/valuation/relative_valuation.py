"""
Relative valuation engine (project spec Section 13: P/E, EV/EBITDA, P/B,
historical & peer multiples).
"""
from sqlalchemy.orm import Session
from app.data.models import Company
from app.data.providers.yfinance_provider import fetch_market_data
from app.screener.metric_aggregator import get_latest_metrics_bulk
from app.analysis.peer_comparison import find_peers


def compute_multiples(company: Company, metrics: dict) -> dict:
    """Computes P/E, EV/EBITDA, P/B from live market data + stored financials."""
    market = fetch_market_data(company.ticker)

    pe_ratio = market.get("trailing_pe")  # yfinance's own trailing P/E (reliable, uses real EPS)

    ev_ebitda = None
    ev = market.get("enterprise_value")
    ebitda = metrics.get("ebitda")
    if ev is not None and ebitda:
        ev_ebitda = ev / ebitda

    price_to_book = market.get("price_to_book")

    return {
        "current_price": market.get("current_price"),
        "market_cap": market.get("market_cap"),
        "pe_ratio": pe_ratio,
        "ev_ebitda": ev_ebitda,
        "price_to_book": price_to_book,
        "beta": market.get("beta"),
    }


def compare_valuation_to_peers(session: Session, company: Company) -> dict:
    """
    Compares a company's valuation multiples to its sector peers —
    flags whether it trades at a premium or discount, with the
    actual numbers shown (never a bare label with no basis).
    """
    metrics = get_latest_metrics_bulk(session, company.id)
    target_multiples = compute_multiples(company, metrics)

    peers = find_peers(session, company)
    peer_multiples = []
    for peer in peers:
        peer_metrics = get_latest_metrics_bulk(session, peer.id)
        pm = compute_multiples(peer, peer_metrics)
        pm["ticker"] = peer.ticker
        peer_multiples.append(pm)

    def _avg(field):
        vals = [p[field] for p in peer_multiples if p.get(field) is not None]
        return sum(vals) / len(vals) if vals else None

    peer_avg_pe = _avg("pe_ratio")
    peer_avg_ev_ebitda = _avg("ev_ebitda")

    pe_vs_peers = None
    if target_multiples["pe_ratio"] and peer_avg_pe:
        pe_vs_peers = (target_multiples["pe_ratio"] / peer_avg_pe - 1)

    return {
        "ticker": company.ticker,
        "target_multiples": target_multiples,
        "peer_avg_pe": peer_avg_pe,
        "peer_avg_ev_ebitda": peer_avg_ev_ebitda,
        "pe_premium_discount_vs_peers": pe_vs_peers,
        "peer_multiples": peer_multiples,
        "interpretation": (
            f"Trades at a {pe_vs_peers:.0%} {'premium' if pe_vs_peers > 0 else 'discount'} "
            f"to peer average P/E." if pe_vs_peers is not None
            else "Insufficient peer P/E data for comparison."
        ),
    }


if __name__ == "__main__":
    from app.data.db import SessionLocal

    session = SessionLocal()
    company = session.query(Company).filter_by(ticker="RELIANCE.NS").first()

    if not company:
        print("RELIANCE.NS not found")
    else:
        result = compare_valuation_to_peers(session, company)
        print(f"Relative Valuation: {result['ticker']}\n")
        print(f"Current Price: {result['target_multiples']['current_price']}")
        print(f"P/E: {result['target_multiples']['pe_ratio']}")
        print(f"EV/EBITDA: {result['target_multiples']['ev_ebitda']}")
        print(f"P/B: {result['target_multiples']['price_to_book']}")
        print(f"\nPeer avg P/E: {result['peer_avg_pe']}")
        print(f"Peer avg EV/EBITDA: {result['peer_avg_ev_ebitda']}")
        print(f"\n{result['interpretation']}")

    session.close()