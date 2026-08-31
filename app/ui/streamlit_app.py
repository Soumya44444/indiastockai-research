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
        response = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
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
            st.info("Analyst Mode is being built in the next step — check back soon.")

    st.sidebar.divider()
    st.sidebar.caption(DISCLAIMER)


if __name__ == "__main__":
    main()