"""
Deterministic tool registry (project spec Section 19). Every tool here
wraps an already-tested, real calculation module from earlier phases —
the LLM (Phase 9 Step 2+) only selects which tool to call and phrases
the final answer. It NEVER computes or invents a financial number itself.
"""
from app.data.db import SessionLocal
from app.data.models import Company
from app.screener.metric_aggregator import get_latest_metrics_bulk, calculate_metric_cagr, calculate_yoy_growth
from app.screener.ratio_calculator import calculate_all_ratios
from app.screener.fundamental_score import calculate_fundamental_score
from app.screener.presets import run_preset, PRESETS
from app.screener.custom_filter import run_custom_filter
from app.analysis.peer_comparison import compare_to_peers
from app.analysis.earnings_quality import detect_earnings_quality_flags
from app.analysis.business_profile import build_business_industry_profile
from app.forecasting.forecast_engine import generate_forecast
from app.valuation.relative_valuation import compare_valuation_to_peers
from app.valuation.dcf_engine import run_dcf
from app.valuation.ddm_valuation import run_ddm
from app.valuation.price_targets import generate_price_targets
from app.risk.returns import get_daily_returns, get_daily_returns_by_date, calculate_beta, align_return_series
from app.risk.risk_metrics import annualized_volatility, sharpe_ratio, sortino_ratio
from app.risk.drawdown_var import calculate_max_drawdown, calculate_historical_var_cvar


def _get_company(session, ticker: str) -> Company | None:
    return session.query(Company).filter_by(ticker=ticker.upper()).first()


def _not_found(ticker: str) -> dict:
    return {"available": False, "reason": f"Company '{ticker}' not found in database. It may not be loaded, or the ticker format is wrong (expected e.g. RELIANCE.NS)."}


def get_company_financials(ticker: str) -> dict:
    """Tool: fetch a company's latest core financial metrics."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        metrics = get_latest_metrics_bulk(session, company.id)
        return {"available": True, "ticker": company.ticker, "name": company.name, "metrics": metrics}
    finally:
        session.close()


def calculate_ratios(ticker: str) -> dict:
    """Tool: compute all financial ratios for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        metrics = get_latest_metrics_bulk(session, company.id)
        ratios = calculate_all_ratios(metrics)
        return {"available": True, "ticker": company.ticker, "ratios": ratios}
    finally:
        session.close()


def get_fundamental_score(ticker: str) -> dict:
    """Tool: compute the weighted fundamental score for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
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
        return {"available": True, "ticker": company.ticker, "score_breakdown": result}
    finally:
        session.close()


def screen_stocks(preset_name: str) -> dict:
    """Tool: run a named screener preset across all companies."""
    if preset_name not in PRESETS:
        return {"available": False, "reason": f"Unknown preset '{preset_name}'. Available: {list(PRESETS.keys())}"}
    session = SessionLocal()
    try:
        results = run_preset(session, preset_name)
        matched = [r for r in results if r["matched"]]
        return {"available": True, "preset": preset_name, "matched_count": len(matched),
                "matches": [{"ticker": r["ticker"], "name": r["name"], "score": r["fundamental_score"]} for r in matched]}
    finally:
        session.close()


def compare_peers(ticker: str) -> dict:
    """Tool: compare a company's fundamentals to its sector peers."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        result = compare_to_peers(session, company)
        return {"available": True, **result}
    finally:
        session.close()


def analyze_earnings_quality(ticker: str) -> dict:
    """Tool: get earnings-quality/forensic flags for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        flags = detect_earnings_quality_flags(session, company)
        return {"available": True, "ticker": company.ticker, "flags": flags}
    finally:
        session.close()


def analyze_business(ticker: str) -> dict:
    """Tool: get business/industry descriptive profile for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        profile = build_business_industry_profile(session, company)
        return {"available": True, **profile}
    finally:
        session.close()


def forecast_financials(ticker: str, years: int = 3) -> dict:
    """Tool: generate Bear/Base/Bull financial forecast for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        result = generate_forecast(session, company.id, years=years)
        return {"available": result.get("available", False), "ticker": company.ticker, **result}
    finally:
        session.close()


def calculate_valuation(ticker: str) -> dict:
    """Tool: get relative valuation, DCF, and DDM for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        relative = compare_valuation_to_peers(session, company)
        dcf = run_dcf(session, company)
        ddm = run_ddm(session, company)
        return {"available": True, "ticker": company.ticker, "relative_valuation": relative,
                "dcf": dcf, "ddm": ddm}
    finally:
        session.close()


def calculate_price_target(ticker: str) -> dict:
    """Tool: get Bear/Base/Bull price targets for a company."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        if not company:
            return _not_found(ticker)
        result = generate_price_targets(session, company)
        return {"available": result.get("available", False), "ticker": company.ticker, **result}
    finally:
        session.close()


def calculate_risk(ticker: str) -> dict:
    """Tool: full risk profile — Beta, volatility, Sharpe, Sortino, Max DD, VaR/CVaR."""
    session = SessionLocal()
    try:
        company = _get_company(session, ticker)
        nifty = _get_company(session, "^NSEI")
        if not company:
            return _not_found(ticker)
        if not nifty:
            return {"available": False, "reason": "NIFTY 50 benchmark not loaded — cannot compute beta."}

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
            "available": True, "ticker": company.ticker,
            "beta": beta_result, "volatility": vol, "sharpe": sharpe, "sortino": sortino,
            "max_drawdown": dd, "var_cvar": var_cvar,
        }
    finally:
        session.close()


def run_backtest_tool(start_date: str, end_date: str, top_n: int = 10) -> dict:
    """Tool: run a fundamentals-based backtest between two dates (YYYY-MM-DD)."""
    from datetime import date as date_cls
    from app.backtesting.backtest_engine import run_backtest
    from app.backtesting.performance import calculate_backtest_performance

    session = SessionLocal()
    try:
        start = date_cls.fromisoformat(start_date)
        end = date_cls.fromisoformat(end_date)
        backtest = run_backtest(session, start, end, rebalance_frequency_months=3, top_n=top_n)
        performance = calculate_backtest_performance(backtest)
        return {"available": performance.get("available", False), **performance}
    finally:
        session.close()


def search_documents_tool(query: str, ticker: str | None = None) -> dict:
    """
    Tool: semantic search over ingested documents, with citations.

    Import is deliberately LOCAL (not top-level) — app.rag.retrieval pulls
    in ChromaDB + sentence-transformers (which loads PyTorch), which alone
    can use 300-500MB+ of RAM just from being imported. Keeping this import
    lazy means that memory is only spent the first time someone actually
    calls this tool, instead of at server startup — this matters a lot on
    memory-constrained free-tier hosting (e.g. Render's 512MB limit), where
    an eager top-level import here caused the API to be OOM-killed (exit
    137) before it could even open a port.
    """
    from app.rag.retrieval import search_documents, format_citation

    result = search_documents(query, top_k=5, ticker=ticker)
    if not result["available"]:
        return result
    return {
        "available": True,
        "query": query,
        "matches": [
            {"text": m["text"], "citation": format_citation(m), "relevance": m["relevance_score"]}
            for m in result["matches"]
        ],
    }


# Tool registry: name -> (function, description) for the LLM orchestration layer.
TOOL_REGISTRY = {
    "get_company_financials": {
        "fn": get_company_financials,
        "description": "Get a company's latest core financial metrics (revenue, net income, assets, etc.). Args: ticker (e.g. 'RELIANCE.NS')",
    },
    "calculate_ratios": {
        "fn": calculate_ratios,
        "description": "Compute financial ratios (margins, ROE, ROCE, debt-to-equity, etc.) for a company. Args: ticker",
    },
    "get_fundamental_score": {
        "fn": get_fundamental_score,
        "description": "Get the weighted fundamental score (0-100) with component breakdown for a company. Args: ticker",
    },
    "screen_stocks": {
        "fn": screen_stocks,
        "description": f"Screen all companies using a preset filter. Args: preset_name (one of {list(PRESETS.keys())})",
    },
    "compare_peers": {
        "fn": compare_peers,
        "description": "Compare a company's fundamentals to its sector peers. Args: ticker",
    },
    "analyze_earnings_quality": {
        "fn": analyze_earnings_quality,
        "description": "Get earnings-quality/forensic warning flags for a company. Args: ticker",
    },
    "analyze_business": {
        "fn": analyze_business,
        "description": "Get business model, sector, industry, and descriptive profile for a company. Args: ticker",
    },
    "forecast_financials": {
        "fn": forecast_financials,
        "description": "Generate a Bear/Base/Bull financial forecast for a company. Args: ticker, years (optional, default 3)",
    },
    "calculate_valuation": {
        "fn": calculate_valuation,
        "description": "Get relative valuation (P/E, EV/EBITDA), DCF, and DDM valuation for a company. Args: ticker",
    },
    "calculate_price_target": {
        "fn": calculate_price_target,
        "description": "Get Bear/Base/Bull price targets with upside/downside and margin of safety. Args: ticker",
    },
    "calculate_risk": {
        "fn": calculate_risk,
        "description": "Get full risk profile: Beta, volatility, Sharpe, Sortino, Max Drawdown, VaR/CVaR. Args: ticker",
    },
    "run_backtest": {
        "fn": run_backtest_tool,
        "description": "Run a fundamentals-based backtest between two dates. Args: start_date, end_date (YYYY-MM-DD), top_n (optional, default 10)",
    },
    "search_documents": {
        "fn": search_documents_tool,
        "description": "Semantic search over ingested research documents (PDFs), returns cited excerpts. Args: query, ticker (optional filter)",
    },
}


if __name__ == "__main__":
    print(f"Tool registry: {len(TOOL_REGISTRY)} tools registered\n")
    for name, info in TOOL_REGISTRY.items():
        print(f"  {name}: {info['description']}")

    print("\n--- Quick smoke test: get_company_financials('RELIANCE.NS') ---")
    result = get_company_financials("RELIANCE.NS")
    print(f"Available: {result['available']}")
    if result["available"]:
        print(f"Company: {result['name']}")
        print(f"Revenue: {result['metrics'].get('revenue')}")