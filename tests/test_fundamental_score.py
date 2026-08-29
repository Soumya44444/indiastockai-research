"""Unit tests for the weighted fundamental score engine
(app/screener/fundamental_score.py)."""
import pytest
from app.screener.fundamental_score import (
    calculate_fundamental_score, score_growth, score_profitability,
    score_balance_sheet, score_cash_flow, COMPONENT_WEIGHTS
)


def make_metrics(**overrides) -> dict:
    base = {
        "revenue": 1000.0, "net_income": 150.0, "total_assets": 2000.0,
        "total_equity": 800.0, "total_debt": 200.0, "operating_cash_flow": 160.0,
        "ebit": 200.0, "current_assets": 600.0, "current_liabilities": 300.0,
        "interest_expense": 20.0,
    }
    base.update(overrides)
    return base


class TestScoreGrowth:
    def test_strong_growth_scores_high(self):
        result = score_growth(revenue_cagr=0.25, revenue_yoy=0.22)
        assert result["score"] >= 85

    def test_weak_growth_scores_low(self):
        result = score_growth(revenue_cagr=-0.05, revenue_yoy=-0.02)
        assert result["score"] <= 40

    def test_missing_growth_data_returns_none(self):
        # When NO data is available at all, score is None (not a fabricated
        # default) — consistent with the project's "never fabricate data" rule.
        result = score_growth(revenue_cagr=None, revenue_yoy=None)
        assert result["score"] is None

    def test_partial_growth_data_uses_default_for_missing_half(self):
        # When ONE of the two inputs is missing, the _bucket_score default (50)
        # fills in for that half only, while the other half still contributes.
        result = score_growth(revenue_cagr=0.20, revenue_yoy=None)
        assert result["score"] is not None

    def test_rationale_present(self):
        result = score_growth(revenue_cagr=0.10, revenue_yoy=0.08)
        assert len(result["rationale"]) == 2


class TestScoreProfitability:
    def test_high_profitability_scores_high(self):
        metrics = make_metrics(net_income=250.0)  # 25% net margin, high ROE/ROCE
        result = score_profitability(metrics)
        assert result["score"] >= 70


class TestScoreBalanceSheet:
    def test_low_debt_high_coverage_scores_high(self):
        metrics = make_metrics(total_debt=0, interest_expense=5.0)
        result = score_balance_sheet(metrics)
        assert result["score"] >= 70

    def test_high_debt_scores_lower(self):
        low_debt_metrics = make_metrics(total_debt=50.0)
        high_debt_metrics = make_metrics(total_debt=1600.0)  # D/E = 2.0
        low_result = score_balance_sheet(low_debt_metrics)
        high_result = score_balance_sheet(high_debt_metrics)
        assert high_result["score"] < low_result["score"]


class TestScoreCashFlow:
    def test_healthy_cfo_pat_ratio_scores_max(self):
        metrics = make_metrics(operating_cash_flow=150.0, net_income=150.0)  # ratio = 1.0
        result = score_cash_flow(metrics)
        assert result["score"] == 100

    def test_very_low_cfo_pat_scores_poorly(self):
        metrics = make_metrics(operating_cash_flow=30.0, net_income=150.0)  # ratio = 0.2
        result = score_cash_flow(metrics)
        assert result["score"] == 30


class TestCalculateFundamentalScore:
    def test_valuation_and_quality_marked_pending(self):
        result = calculate_fundamental_score(make_metrics(), revenue_cagr=0.10, revenue_yoy=0.08)
        assert result["components"]["valuation"]["score"] is None
        assert result["components"]["quality"]["score"] is None
        assert "Pending" in result["components"]["valuation"]["rationale"][0]

    def test_weight_used_excludes_pending_components(self):
        result = calculate_fundamental_score(make_metrics(), revenue_cagr=0.10, revenue_yoy=0.08)
        # Growth(20) + Profitability(20) + Balance Sheet(15) + Cash Flow(15) = 70
        assert result["weight_used_pct"] == 70
        assert result["weight_pending_pct"] == 30

    def test_total_score_is_percentage_0_to_100(self):
        result = calculate_fundamental_score(make_metrics(), revenue_cagr=0.10, revenue_yoy=0.08)
        assert 0 <= result["total_score_available_weight_only"] <= 100

    def test_all_components_present(self):
        result = calculate_fundamental_score(make_metrics(), revenue_cagr=0.10, revenue_yoy=0.08)
        assert set(result["components"].keys()) == set(COMPONENT_WEIGHTS.keys())

    def test_component_weighted_contribution_matches_weight(self):
        result = calculate_fundamental_score(make_metrics(), revenue_cagr=0.10, revenue_yoy=0.08)
        growth = result["components"]["growth"]
        expected_contribution = growth["score"] * growth["weight_pct"] / 100
        assert growth["weighted_contribution"] == pytest.approx(expected_contribution, abs=0.01)