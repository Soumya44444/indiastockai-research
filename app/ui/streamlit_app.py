"""
Streamlit UI (project spec Section 3, 12, 26): Simple Mode for
non-technical users, Analyst Mode for full transparency. Calls the
FastAPI backend (app/api/main.py) rather than the database directly —
keeps the UI layer thin and reuses every already-tested calculation.

STRICT RULE (per spec Section 26): no investment-advice language.
Every page carries a visible disclaimer.
"""
import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="IndiaStockAI Research Workstation", layout="wide")

DISCLAIMER = (
    "⚠️ **For research/educational purposes only.** This is not investment "
    "advice. All figures are derived from free/public data sources and "
    "carry known limitations — see LIMITATIONS.md in the project repository."
)


def api_get(path: str, params: dict | None = None) -> dict | None:
    """Calls the FastAPI backend, returns None (and shows an error) on failure."""
    try:
        response = requests.get(f"{API_BASE}{path}", params=params, timeout=60)
        if response.status_code == 404:
            st.error(f"Not found: {response.json().get('detail', 'Unknown error')}")
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error(
            "⚠️ Cannot connect to the API backend. Make sure it's running: "
            "`uvicorn app.api.main:app --reload` in a separate terminal."
        )
        return None
    except requests.exceptions.Timeout:
        st.error("Request timed out. This calculation may take longer — try again.")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def render_simple_mode(ticker: str):
    """Simple Mode: clean, non-technical summary (spec Section 3)."""
    st.subheader(f"Overview: {ticker}")

    company = api_get(f"/companies/{ticker}")
    if not company:
        return
    st.markdown(f"**{company['name']}** · {company.get('sector', 'N/A')} · {company.get('industry', 'N/A')}")

    score_data = api_get(f"/companies/{ticker}/score")
    if score_data:
        breakdown = score_data["score_breakdown"]
        total = breakdown.get("total_score_available_weight_only")

        col1, col2 = st.columns([1, 2])
        with col1:
            if total is not None:
                st.metric("Overall Fundamental Score", f"{total:.1f} / 100")
                st.caption(f"Based on {breakdown['weight_used_pct']:.0f}% of full weighting "
                           f"(remaining components pending future phases)")

        with col2:
            st.markdown("**What this means:**")
            for name, comp in breakdown["components"].items():
                if comp["score"] is not None:
                    label = name.replace("_", " ").title()
                    st.write(f"- **{label}**: {comp['score']}/100 — {comp['rationale'][0]}")

    st.divider()
    st.info(
        "For full technical detail (all ratios, DCF assumptions, risk metrics), "
        "switch to **Analyst Mode** in the sidebar."
    )


def render_analyst_mode(ticker: str):
    """
    Analyst Mode: full technical transparency (spec Section 3: "Analyst
    Mode must be fully transparent and auditable"). Every number shown
    with its methodology/source.
    """
    st.subheader(f"Analyst View: {ticker}")

    company = api_get(f"/companies/{ticker}")
    if not company:
        return
    st.markdown(f"**{company['name']}** · {company.get('sector', 'N/A')} · {company.get('industry', 'N/A')}")

    tabs = st.tabs(["Fundamental Score", "Ratios", "Valuation", "Risk", "Forecast"])

    with tabs[0]:
        score_data = api_get(f"/companies/{ticker}/score")
        if score_data:
            breakdown = score_data["score_breakdown"]
            st.metric("Total Score (available weight)", f"{breakdown.get('total_score_available_weight_only')} / 100")
            st.caption(breakdown.get("note", ""))
            for name, comp in breakdown["components"].items():
                with st.expander(f"{name.replace('_', ' ').title()} — score: {comp['score']} (weight: {comp['weight_pct']}%)"):
                    for r in comp["rationale"]:
                        st.write(f"- {r}")
                    if comp.get("weighted_contribution") is not None:
                        st.caption(f"Weighted contribution to total: {comp['weighted_contribution']}")

    with tabs[1]:
        ratios_data = api_get(f"/companies/{ticker}/ratios")
        if ratios_data:
            st.json(ratios_data["ratios"])

    with tabs[2]:
        with st.spinner("Computing DCF, DDM, and relative valuation (may take a moment)..."):
            valuation_data = api_get(f"/companies/{ticker}/valuation")
        if valuation_data:
            dcf = valuation_data.get("dcf", {})
            if dcf.get("available"):
                st.markdown("**DCF Valuation**")
                st.caption(dcf.get("methodology_note", ""))
                for scenario, vals in dcf.get("scenarios", {}).items():
                    if vals.get("available"):
                        st.write(f"- **{scenario.title()}**: Fair Value/Share = ₹{vals['fair_value_per_share']:,.2f} "
                                 f"(EV = ₹{vals['enterprise_value']:,.0f})")
            else:
                st.warning(f"DCF not available: {dcf.get('reason', 'Unknown reason')}")

            ddm = valuation_data.get("ddm", {})
            st.markdown("**DDM Cross-Check**")
            if ddm.get("available"):
                st.write(f"Fair Value/Share: ₹{ddm['fair_value_per_share']:,.2f}")
                st.caption(ddm.get("methodology_note", ""))
            else:
                st.info(f"DDM not applicable: {ddm.get('reason', 'Unknown reason')}")

            relative = valuation_data.get("relative_valuation", {})
            st.markdown("**Relative Valuation**")
            st.json(relative.get("target_multiples", {}))

        price_targets = api_get(f"/companies/{ticker}/price-targets")
        if price_targets and price_targets.get("available"):
            st.markdown("**Price Targets**")
            for scenario, t in price_targets.get("targets", {}).items():
                if t.get("available"):
                    st.write(f"- **{scenario.title()}**: ₹{t['target_price']:,.2f} "
                             f"(Upside: {t['upside_pct']:.1%}, Margin of Safety: {t['margin_of_safety_pct']:.1%})")

    with tabs[3]:
        with st.spinner("Computing risk metrics..."):
            risk_data = api_get(f"/companies/{ticker}/risk")
        if risk_data:
            col1, col2, col3 = st.columns(3)
            beta = risk_data.get("beta", {})
            vol = risk_data.get("volatility", {})
            sharpe = risk_data.get("sharpe", {})

            with col1:
                if beta.get("available"):
                    st.metric("Beta (self-computed vs NIFTY 50)", f"{beta['beta']:.3f}")
                    st.caption(f"Correlation: {beta['correlation_to_benchmark']:.3f}")
            with col2:
                if vol.get("available"):
                    st.metric("Annualized Volatility", f"{vol['annualized_volatility']:.1%}")
            with col3:
                if sharpe.get("available"):
                    st.metric("Sharpe Ratio", f"{sharpe['sharpe_ratio']:.3f}")

            dd = risk_data.get("max_drawdown", {})
            if dd.get("available"):
                st.markdown(f"**Max Drawdown**: {dd['max_drawdown_pct']:.1%} "
                            f"(Peak: {dd['peak_date']}, Trough: {dd['trough_date']}, "
                            f"Recovered: {dd.get('recovered', 'N/A')})")

            var_cvar = risk_data.get("var_cvar", {})
            if var_cvar.get("available"):
                st.markdown(f"**1-Day VaR/CVaR (95% confidence)**: VaR = {var_cvar['var_pct']:.2%}, "
                            f"CVaR = {var_cvar['cvar_pct']:.2%}")
                st.caption(var_cvar.get("interpretation", ""))

    with tabs[4]:
        with st.spinner("Generating forecast..."):
            forecast_data = api_get(f"/companies/{ticker}/forecast")
        if forecast_data and forecast_data.get("available"):
            st.caption(forecast_data.get("methodology_note", ""))
            for scenario, years_data in forecast_data.get("forecasts", {}).items():
                with st.expander(f"{scenario.title()} Scenario"):
                    for y in years_data:
                        st.write(f"Year {y['year']}: Revenue = ₹{y['revenue']:,.0f}, "
                                 f"FCF = ₹{y['fcf']:,.0f}" if y.get('fcf') is not None else
                                 f"Year {y['year']}: Revenue = ₹{y['revenue']:,.0f}")
        elif forecast_data:
            st.warning(f"Forecast not available: {forecast_data.get('reason', 'Unknown reason')}")


def render_home():
    st.title("📊 IndiaStockAI Research Workstation")
    st.markdown(
        "AI-powered fundamental equity research and risk analytics platform "
        "for Indian equities — screening, valuation, forecasting, portfolio "
        "risk, backtesting, and a source-grounded research chatbot."
    )
    st.warning(DISCLAIMER)

    st.divider()
    st.markdown("### Get started")
    st.markdown(
        "Use the sidebar to search for a company, run the screener, or "
        "chat with the AI research assistant."
    )


def main():
    st.sidebar.title("Navigation")
    mode = st.sidebar.radio("Mode", ["Simple Mode", "Analyst Mode"])
    st.sidebar.divider()

    ticker_input = st.sidebar.text_input("Company ticker (e.g. RELIANCE.NS)", value="")

    if not ticker_input:
        render_home()
    else:
        ticker = ticker_input.strip().upper()
        if mode == "Simple Mode":
            render_simple_mode(ticker)
        else:
            render_analyst_mode(ticker)

    st.sidebar.divider()
    st.sidebar.caption(DISCLAIMER)


if __name__ == "__main__":
    main()