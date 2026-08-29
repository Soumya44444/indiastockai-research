"""Unit tests for the valuation engine's pure-logic pieces
(DCF discounting, DDM growth estimation, valuation scoring, price targets)."""
import pytest
from app.valuation.dcf_engine import _discount_fcf_series
from app.valuation.ddm_valuation import estimate_sustainable_growth
from app.valuation.price_targets import _upside
from app.screener.fundamental_score import score_valuation


class TestDiscountFcfSeries:
    def test_basic_discounting_produces_positive_ev(self):
        result = _discount_fcf_series([100.0, 110.0, 121.0], wacc=0.10, terminal_growth=0.04)
        assert result["available"] is True
        assert result["enterprise_value"] > 0

    def test_wacc_must_exceed_terminal_growth(self):
        result = _discount_fcf_series([100.0], wacc=0.04, terminal_growth=0.04)
        assert result["available"] is False
        assert "must exceed" in result["reason"]

    def test_wacc_below_terminal_growth_is_invalid(self):
        result = _discount_fcf_series([100.0], wacc=0.03, terminal_growth=0.05)
        assert result["available"] is False

    def test_terminal_value_is_majority_of_ev_for_short_horizon(self):
        # With only 1 explicit year and a perpetuity beyond it, terminal
        # value should dominate — a known, expected DCF characteristic.
        result = _discount_fcf_series([100.0], wacc=0.10, terminal_growth=0.04)
        assert result["terminal_value_pct_of_ev"] > 0.8

    def test_higher_wacc_produces_lower_ev(self):
        low_wacc = _discount_fcf_series([100.0, 100.0], wacc=0.08, terminal_growth=0.03)
        high_wacc = _discount_fcf_series([100.0, 100.0], wacc=0.15, terminal_growth=0.03)
        assert high_wacc["enterprise_value"] < low_wacc["enterprise_value"]


class TestEstimateSustainableGrowth:
    def test_normal_case(self):
        metrics = {"net_income": 100.0, "total_equity": 800.0}  # ROE = 12.5%
        market = {"payout_ratio": 0.4}  # retention = 60%
        result = estimate_sustainable_growth(metrics, market)
        assert result["available"] is True
        assert result["growth_rate"] == pytest.approx(0.6 * 0.125)

    def test_missing_payout_ratio_unavailable(self):
        metrics = {"net_income": 100.0, "total_equity": 800.0}
        market = {"payout_ratio": None}
        result = estimate_sustainable_growth(metrics, market)
        assert result["available"] is False

    def test_missing_roe_unavailable(self):
        metrics = {"net_income": None, "total_equity": 800.0}
        market = {"payout_ratio": 0.4}
        result = estimate_sustainable_growth(metrics, market)
        assert result["available"] is False

    def test_payout_ratio_bounded_above_one(self):
        # Some companies report payout ratios slightly over 100% (paying
        # more than earnings) — should be sanity-capped, not break the calc.
        metrics = {"net_income": 100.0, "total_equity": 800.0}
        market = {"payout_ratio": 1.5}
        result = estimate_sustainable_growth(metrics, market)
        assert result["available"] is True
        assert result["retention_ratio"] == 0.0  # capped at payout=1.0
        assert result["growth_rate"] == 0.0


class TestUpsideCalculation:
    def test_positive_upside(self):
        assert _upside(current_price=100.0, target_price=120.0) == pytest.approx(0.20)

    def test_negative_upside_downside_case(self):
        assert _upside(current_price=100.0, target_price=80.0) == pytest.approx(-0.20)

    def test_zero_upside_when_equal(self):
        assert _upside(current_price=100.0, target_price=100.0) == 0.0


class TestScoreValuation:
    def test_high_upside_scores_high(self):
        result = score_valuation(0.35)
        assert result["score"] == 100

    def test_deeply_overvalued_scores_low(self):
        result = score_valuation(-0.50)
        assert result["score"] == 15

    def test_fairly_valued_scores_middle(self):
        result = score_valuation(0.05)
        assert result["score"] == 70

    def test_missing_data_uses_default(self):
        result = score_valuation(None)
        assert result["score"] == 50  # _bucket_score default
        assert "N/A" in result["rationale"][0]

    def test_rationale_shows_percentage(self):
        result = score_valuation(0.123)
        assert "12.3%" in result["rationale"][0]