"""Unit tests for risk metrics (app/risk/risk_metrics.py and
app/risk/returns.py's pure-logic pieces)."""
import pytest
import numpy as np
from app.risk.risk_metrics import annualized_volatility, sharpe_ratio, sortino_ratio
from app.risk.returns import calculate_beta, align_return_series
from app.risk.drawdown_var import calculate_historical_var_cvar


def make_returns(n=252, mean=0.0005, std=0.015, seed=42):
    rng = np.random.default_rng(seed)
    return list(rng.normal(mean, std, n))


class TestAnnualizedVolatility:
    def test_normal_case(self):
        returns = make_returns()
        result = annualized_volatility(returns)
        assert result["available"] is True
        assert result["annualized_volatility"] > 0

    def test_insufficient_data(self):
        result = annualized_volatility([0.01, -0.01])
        assert result["available"] is False

    def test_higher_std_gives_higher_annualized_vol(self):
        low_vol = annualized_volatility(make_returns(std=0.005))
        high_vol = annualized_volatility(make_returns(std=0.03))
        assert high_vol["annualized_volatility"] > low_vol["annualized_volatility"]


class TestSharpeRatio:
    def test_positive_excess_return_gives_positive_sharpe(self):
        # High mean return, low risk-free rate
        returns = make_returns(mean=0.003, std=0.01)
        result = sharpe_ratio(returns, risk_free_rate_annual=0.02)
        assert result["available"] is True
        assert result["sharpe_ratio"] > 0

    def test_negative_excess_return_gives_negative_sharpe(self):
        returns = make_returns(mean=-0.002, std=0.01)
        result = sharpe_ratio(returns, risk_free_rate_annual=0.10)
        assert result["sharpe_ratio"] < 0

    def test_insufficient_data(self):
        result = sharpe_ratio([0.01] * 5)
        assert result["available"] is False

    def test_zero_volatility_undefined(self):
        result = sharpe_ratio([0.0] * 30)
        assert result["available"] is False


class TestSortinoRatio:
    def test_normal_case_with_mixed_returns(self):
        returns = make_returns()
        result = sortino_ratio(returns)
        assert result["available"] is True

    def test_no_downside_returns_undefined(self):
        # All positive returns -> no downside deviation to compute
        result = sortino_ratio([0.01] * 30)
        assert result["available"] is False
        assert "downside" in result["reason"].lower()

    def test_downside_days_count_matches_actual_negatives(self):
        returns = [0.01, -0.02, 0.005, -0.01, 0.02] * 10  # 20 negative out of 50
        result = sortino_ratio(returns)
        assert result["downside_days_count"] == 20


class TestCalculateBeta:
    def test_perfectly_correlated_series_beta_one(self):
        bench = make_returns()
        stock = bench  # identical series -> beta should be 1.0, correlation 1.0
        result = calculate_beta(stock, bench)
        assert result["available"] is True
        assert result["beta"] == pytest.approx(1.0, abs=0.01)
        assert result["correlation_to_benchmark"] == pytest.approx(1.0, abs=0.01)

    def test_scaled_series_beta_reflects_scale(self):
        bench = make_returns()
        stock = [r * 2 for r in bench]  # exactly 2x as volatile, same direction
        result = calculate_beta(stock, bench)
        assert result["beta"] == pytest.approx(2.0, abs=0.05)

    def test_insufficient_overlap(self):
        result = calculate_beta([0.01] * 5, [0.01] * 5)
        assert result["available"] is False


class TestAlignReturnSeries:
    def test_aligns_on_common_dates_only(self):
        from datetime import date
        a = {date(2026, 1, 1): 0.01, date(2026, 1, 2): 0.02, date(2026, 1, 3): 0.03}
        b = {date(2026, 1, 2): 0.05, date(2026, 1, 3): 0.06, date(2026, 1, 4): 0.07}
        aligned_a, aligned_b = align_return_series(a, b)
        # Only Jan 2 and Jan 3 are common
        assert aligned_a == [0.02, 0.03]
        assert aligned_b == [0.05, 0.06]

    def test_no_common_dates_returns_empty(self):
        from datetime import date
        a = {date(2026, 1, 1): 0.01}
        b = {date(2026, 2, 1): 0.02}
        aligned_a, aligned_b = align_return_series(a, b)
        assert aligned_a == []
        assert aligned_b == []


class TestHistoricalVarCvar:
    def test_normal_case(self):
        returns = make_returns()
        result = calculate_historical_var_cvar(returns, confidence_level=0.95)
        assert result["available"] is True
        assert result["var_pct"] < 0  # a loss, expressed as negative
        assert result["cvar_pct"] <= result["var_pct"]  # CVaR should be worse (more negative) than VaR

    def test_insufficient_data(self):
        result = calculate_historical_var_cvar([0.01] * 10)
        assert result["available"] is False

    def test_higher_confidence_gives_larger_var(self):
        returns = make_returns()
        var_95 = calculate_historical_var_cvar(returns, confidence_level=0.95)
        var_99 = calculate_historical_var_cvar(returns, confidence_level=0.99)
        # 99% confidence VaR should be more extreme (more negative) than 95%
        assert var_99["var_pct"] <= var_95["var_pct"]

    def test_methodology_disclosed(self):
        result = calculate_historical_var_cvar(make_returns())
        assert "historical simulation" in result["methodology"].lower()
        assert result["confidence_level"] == 0.95
        assert result["time_horizon_days"] == 1

    def test_time_horizon_scaling(self):
        returns = make_returns()
        var_1day = calculate_historical_var_cvar(returns, time_horizon_days=1)
        var_10day = calculate_historical_var_cvar(returns, time_horizon_days=10)
        # sqrt(10) scaling should make the 10-day VaR larger in magnitude
        assert abs(var_10day["var_pct"]) > abs(var_1day["var_pct"])