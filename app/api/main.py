"""
FastAPI backend (project spec Section 23-24). Exposes the platform's
analysis modules as REST endpoints with validation, type hints, and
auto-generated OpenAPI docs. No new business logic here — every endpoint
wraps an already-tested function from earlier phases.
"""
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.data.db import SessionLocal
from app.data.models import Company
from app.screener.metric_aggregator import get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
from app.screener.ratio_calculator import calculate_all_ratios
from app.screener.fundamental_score import calculate_fundamental_score
from app.screener.presets import run_preset, PRESETS
from app.valuation.price_targets import generate_price_targets
from app.valuation.relative_valuation import compare_valuation_to_peers
from app.valuation.dcf_engine import run_dcf
from app.valuation.ddm_valuation import run_ddm
from app.forecasting.forecast_engine import generate_forecast
from app.risk.returns import get_daily_returns, get_daily_returns_by_date, calculate_beta, align_return_series
from app.risk.risk_metrics import annualized_volatility, sharpe_ratio, sortino_ratio
from app.risk.drawdown_var import calculate_max_drawdown, calculate_historical_var_cvar
from app.backtesting.backtest_engine import run_backtest
from app.backtesting.performance import calculate_backtest_performance

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


@app.get("/companies/{ticker}/valuation", tags=["Valuation"],
          responses={404: {"model": ErrorResponse}})
def get_valuation(ticker: str):
    """Get relative valuation (P/E, EV/EBITDA), DCF, and DDM for a company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        relative = compare_valuation_to_peers(session, company)
        dcf = run_dcf(session, company)
        ddm = run_ddm(session, company)
        return {"ticker": company.ticker, "relative_valuation": relative, "dcf": dcf, "ddm": ddm}
    finally:
        session.close()


@app.get("/companies/{ticker}/price-targets", tags=["Valuation"],
          responses={404: {"model": ErrorResponse}})
def get_price_targets(ticker: str):
    """Get Bear/Base/Bull price targets with upside/downside and margin of safety."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        result = generate_price_targets(session, company)
        return {"ticker": company.ticker, **result}
    finally:
        session.close()


@app.get("/companies/{ticker}/forecast", tags=["Forecasting"],
          responses={404: {"model": ErrorResponse}})
def get_forecast(ticker: str, years: int = 3):
    """Get Bear/Base/Bull financial forecast for a company."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        result = generate_forecast(session, company.id, years=years)
        return {"ticker": company.ticker, **result}
    finally:
        session.close()


@app.get("/companies/{ticker}/risk", tags=["Risk"],
          responses={404: {"model": ErrorResponse}})
def get_risk(ticker: str):
    """Get full risk profile: Beta, volatility, Sharpe, Sortino, Max Drawdown, VaR/CVaR."""
    session = SessionLocal()
    try:
        company = _get_company_or_404(session, ticker)
        nifty = session.query(Company).filter_by(ticker="^NSEI").first()
        if not nifty:
            raise HTTPException(status_code=503, detail="NIFTY 50 benchmark not loaded — cannot compute beta.")

        stock_by_date = get_daily_returns_by_date(session, company.id, days=252)
        bench_by_date = get_daily_returns_by_date(session, nifty.id, days=252)
        aligned_stock, aligned_bench = align_return_series(stock_by_date, bench_by_date)
        beta_result = calculate_beta(aligned_stock, aligned_bench)

        returns = get_daily_returns(session, company.id, days=252)
        vol = annualized_volatility(returns)
        sharpe = sharpe_ratio(returns)
        sortino = sortino_ratio(returns)
        dd = calculate_max_drawdown(session, company.id, days=252)
        var_cvar = calculate_historical_var_cvar(returns, confidence_level=0.95, time_horizon_days=1)

        return {
            "ticker": company.ticker, "beta": beta_result, "volatility": vol,
            "sharpe": sharpe, "sortino": sortino, "max_drawdown": dd, "var_cvar": var_cvar,
        }
    finally:
        session.close()


@app.get("/backtest", tags=["Backtesting"])
def run_backtest_endpoint(start_date: str, end_date: str, top_n: int = 10):
    """
    Run a fundamentals-based backtest between two dates (YYYY-MM-DD).
    Recommended start_date >= 2025-07-01 given our quarterly data coverage
    (see LIMITATIONS.md). This endpoint is slow — may take 1-2 minutes.
    """
    session = SessionLocal()
    try:
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format.")

        backtest = run_backtest(session, start, end, rebalance_frequency_months=3, top_n=top_n)
        performance = calculate_backtest_performance(backtest)
        return performance
    finally:
        session.close()