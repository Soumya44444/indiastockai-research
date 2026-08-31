"""
Integration tests for the FastAPI backend (app/api/main.py), using
FastAPI's TestClient — no running server needed.

Scope: fast endpoints only (health check, company lookups, error
handling). Slow endpoints (chat — requires Ollama; backtest and full
screener runs — take 1-2 minutes) are excluded from the automated suite
to keep it fast; they were already verified via live manual testing
during development (see project notes)."""
import pytest
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)


class TestHealthCheck:
    def test_root_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_includes_disclaimer(self):
        response = client.get("/")
        data = response.json()
        assert "disclaimer" in data
        assert "not investment advice" in data["disclaimer"].lower()


class TestCompanyEndpoints:
    def test_list_companies_returns_200(self):
        response = client.get("/companies")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_companies_excludes_benchmark_index(self):
        response = client.get("/companies")
        tickers = [c["ticker"] for c in response.json()]
        assert "^NSEI" not in tickers

    def test_get_known_company_returns_200(self):
        response = client.get("/companies/RELIANCE.NS")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "RELIANCE.NS"
        assert data["name"] == "Reliance Industries Limited"

    def test_get_unknown_company_returns_404(self):
        response = client.get("/companies/FAKENOTREAL.NS")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_financials_returns_real_data(self):
        response = client.get("/companies/RELIANCE.NS/financials")
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"]["revenue"] is not None
        assert data["metrics"]["revenue"] > 0

    def test_get_ratios_returns_expected_keys(self):
        response = client.get("/companies/RELIANCE.NS/ratios")
        assert response.status_code == 200
        ratios = response.json()["ratios"]
        assert "roe" in ratios
        assert "debt_to_equity" in ratios

    def test_get_financials_unknown_ticker_returns_404(self):
        response = client.get("/companies/FAKENOTREAL.NS/financials")
        assert response.status_code == 404


class TestScreenerEndpoints:
    def test_list_presets_returns_all_nine(self):
        response = client.get("/screener/presets")
        assert response.status_code == 200
        presets = response.json()["presets"]
        assert len(presets) == 9
        assert "strong_fundamentals" in presets
        assert "undervalued" in presets

    def test_run_unknown_preset_returns_404(self):
        response = client.get("/screener/run/not_a_real_preset")
        assert response.status_code == 404


class TestChatEndpointValidation:
    """Only tests input validation (fast, no LLM call needed) — not the
    actual LLM response, which requires Ollama and takes 10-60+ seconds."""

    def test_empty_question_returns_400(self):
        response = client.post("/chat", json={"question": "", "agentic": False})
        assert response.status_code == 400

    def test_whitespace_only_question_returns_400(self):
        response = client.post("/chat", json={"question": "   ", "agentic": False})
        assert response.status_code == 400

    def test_missing_question_field_returns_422(self):
        # Pydantic validation error for a required field
        response = client.post("/chat", json={"agentic": False})
        assert response.status_code == 422


class TestErrorHandling:
    def test_invalid_backtest_date_returns_400(self):
        response = client.get("/backtest", params={"start_date": "not-a-date", "end_date": "2026-01-01"})
        assert response.status_code == 400

    def test_risk_endpoint_unknown_ticker_returns_404(self):
        response = client.get("/companies/FAKENOTREAL.NS/risk")
        assert response.status_code == 404