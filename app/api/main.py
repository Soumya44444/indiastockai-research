"""
FastAPI backend (project spec Section 23-24). Exposes the platform's
analysis modules as REST endpoints with validation, type hints, and
auto-generated OpenAPI docs. No new business logic here — every endpoint
wraps an already-tested function from earlier phases.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any

from app.data.db import SessionLocal
from app.data.models import Company
from app.screener.metric_aggregator import get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
from app.screener.ratio_calculator import calculate_all_ratios
from app.screener.fundamental_score import calculate_fundamental_score
from app.screener.presets import run_preset, PRESETS
from app.valuation.price_targets import generate_price_targets

app = FastAPI(
    title="IndiaStockAI Research Workstation API",
    description=(
        "AI-powered fundamental equity research and risk analytics platform "
        "for Indian equities. IMPORTANT: This tool provides analytical output "
        "for educational/research purposes only and does NOT constitute "
        "investment advice. All figures are derived from free/public data "
        "sources (yfinance) and carry the limitations documented in "
        "LIMITATIONS.md at the project root."
    ),
    version="0.1.0",
)


class CompanyResponse(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None


class ErrorResponse(BaseModel):
    detail: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_company_or_404(session, ticker: str) -> Company:
    company = session.query(Company).filter_by(ticker=ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{ticker}' not found. Expected format e.g. 'RELIANCE.NS'.")
    return company


@app.get("/", tags=["Health"])
def root():
    """Health check / API info."""
    return {
        "status": "ok",
        "name": "IndiaStockAI Research Workstation API",
        "disclaimer": "For research/educational purposes only. Not investment advice.",
    }


@app.get("/companies", response_model=list[CompanyResponse], tags=["Companies"])
def list_companies():
    """List all companies currently loaded in the database."""
    session = SessionLocal()
    try:
        companies = session.query(Company).filter(Company.ticker != "^NSEI").all()
        return [
            CompanyResponse(ticker=c.ticker, name=c.name, sector=c.sector, industry=c.industry)
            for c in companies
        ]
    finally:
        session.close()


@app.get("/companies/{ticker}", response_model=CompanyResponse, tags=["Companies"],
          responses={404: {"model": ErrorResponse}})
def get_company(ticker: str):
    """Get basic info for a single company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        return CompanyResponse(ticker=company.ticker, name=company.name,
                                sector=company.sector, industry=company.industry)
    finally:
        session.close()


@app.get("/companies/{ticker}/financials", tags=["Financials"],
          responses={404: {"model": ErrorResponse}})
def get_financials(ticker: str):
    """Get latest core financial metrics for a company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        metrics = get_latest_metrics_bulk(session, company.id)
        return {"ticker": company.ticker, "metrics": metrics}
    finally:
        session.close()


@app.get("/companies/{ticker}/ratios", tags=["Financials"],
          responses={404: {"model": ErrorResponse}})
def get_ratios(ticker: str):
    """Get all computed financial ratios for a company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        metrics = get_latest_metrics_bulk(session, company.id)
        ratios = calculate_all_ratios(metrics)
        return {"ticker": company.ticker, "ratios": ratios}
    finally:
        session.close()


@app.get("/companies/{ticker}/score", tags=["Screener"],
          responses={404: {"model": ErrorResponse}})
def get_score(ticker: str):
    """Get the weighted fundamental score breakdown for a company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        metrics = get_latest_metrics_bulk(session, company.id)
        revenue_cagr = calculate_metric_cagr(session, company.id, "revenue", years=3)
        revenue_yoy = calculate_yoy_growth(session, company.id, "revenue")

        valuation_upside = None
        try:
            pt = generate_price_targets(session, company)
            if pt["available"] and pt["targets"]["base"]["available"]:
                valuation_upside = pt["targets"]["base"]["upside_pct"]
        except Exception:
            pass

        result = calculate_fundamental_score(metrics, revenue_cagr, revenue_yoy, valuation_upside)
        return {"ticker": company.ticker, "score_breakdown": result}
    finally:
        session.close()


@app.get("/screener/presets", tags=["Screener"])
def list_presets():
    """List all available screener presets."""
    return {"presets": list(PRESETS.keys())}


@app.get("/screener/run/{preset_name}", tags=["Screener"],
          responses={404: {"model": ErrorResponse}})
def run_screener(preset_name: str):
    """Run a named screener preset across all companies. This is slower
    (computes DCF valuation for every company) — may take 1-2 minutes."""
    if preset_name not in PRESETS:
        raise HTTPException(status_code=404, detail=f"Unknown preset '{preset_name}'. Available: {list(PRESETS.keys())}")

    session = SessionLocal()
    try:
        results = run_preset(session, preset_name)
        matched = [r for r in results if r["matched"]]
        return {
            "preset": preset_name,
            "matched_count": len(matched),
            "matches": [{"ticker": r["ticker"], "name": r["name"], "score": r["fundamental_score"]} for r in matched],
        }
    finally:
        session.close()