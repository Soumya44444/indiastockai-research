"""Unit tests for backtest performance calculations
(app/backtesting/performance.py)."""
import pytest
from datetime import date
from app.backtesting.performance import (
    calculate_cagr_from_periods, calculate_period_volatility,
    calculate_period_sharpe, calculate_period_sortino, calculate_win_rate,
    build_equity_curve, calculate_max_drawdown_from_curve,
    calculate_backtest_performance
)


class TestCagrFromPeriods:
    def test_flat_returns_zero_cagr(self):
        # 4 quarters of 0% each -> 0% CAGR
        result = calculate_cagr_from_periods([0.0, 0.0, 0.0, 0.0], periods_per_year=4)
        assert result == pytest.approx(0.0)

    def test_steady_growth(self):
        # 4 quarters of 5% each, compounded, 1 year -> (1.05)^4 - 1
        result = calculate_cagr_from_periods([0.05, 0.05, 0.05, 0.05], periods_per_year=4)
        assert result == pytest.approx(1.05**4 - 1)

    def test_empty_returns_none(self):
        assert calculate_cagr_from_periods([], periods_per_year=4) is None

    def test_negative_returns_produce_negative_cagr(self):
        result = calculate_cagr_from_periods([-0.05, -0.05, -0.05, -0.05], periods_per_year=4)
        assert result < 0


class TestPeriodVolatility:
    def test_zero_volatility_for_constant_returns(self):
        result = calculate_period_volatility([0.02, 0.02, 0.02, 0.02], periods_per_year=4)
        assert result == pytest.approx(0.0)

    def test_insufficient_data(self):
        assert calculate_period_volatility([0.01], periods_per_year=4) is None

    def test_higher_dispersion_higher_vol(self):
        low = calculate_period_volatility([0.01, 0.011, 0.009, 0.01], periods_per_year=4)
        high = calculate_period_volatility([0.05, -0.05, 0.08, -0.08], periods_per_year=4)
        assert high > low


class TestWinRate:
    def test_all_positive(self):
        assert calculate_win_rate([0.01, 0.02, 0.03]) == 1.0

    def test_half_positive(self):
        assert calculate_win_rate([0.01, -0.01, 0.02, -0.02]) == 0.5

    def test_empty_returns_none(self):
        assert calculate_win_rate([]) is None


class TestEquityCurve:
    def test_compounds_correctly(self):
        periods = [
            {"period_start": date(2025, 1, 1), "period_end": date(2025, 4, 1), "available": True, "portfolio_return_pct": 0.10},
            {"period_start": date(2025, 4, 1), "period_end": date(2025, 7, 1), "available": True, "portfolio_return_pct": -0.05},
        ]
        curve = build_equity_curve(periods, starting_value=100.0)
        assert curve[0]["value"] == 100.0
        assert curve[1]["value"] == pytest.approx(110.0)
        assert curve[2]["value"] == pytest.approx(110.0 * 0.95)

    def test_skips_unavailable_periods(self):
        periods = [
            {"period_start": date(2025, 1, 1), "period_end": date(2025, 4, 1), "available": True, "portfolio_return_pct": 0.10},
            {"period_start": date(2025, 4, 1), "period_end": date(2025, 7, 1), "available": False},
        ]
        curve = build_equity_curve(periods, starting_value=100.0)
        assert len(curve) == 2  # start point + 1 valid period only


class TestMaxDrawdownFromCurve:
    def test_simple_drawdown(self):
        curve = [
            {"date": date(2025, 1, 1), "value": 100.0},
            {"date": date(2025, 4, 1), "value": 120.0},  # new peak
            {"date": date(2025, 7, 1), "value": 90.0},   # trough: (90-120)/120 = -25%
            {"date": date(2025, 10, 1), "value": 110.0},
        ]
        result = calculate_max_drawdown_from_curve(curve)
        assert result["available"] is True
        assert result["max_drawdown_pct"] == pytest.approx(-0.25)
        assert result["peak_date"] == date(2025, 4, 1)
        assert result["trough_date"] == date(2025, 7, 1)

    def test_no_drawdown_monotonic_increase(self):
        curve = [{"date": date(2025, 1, 1), "value": 100.0}, {"date": date(2025, 4, 1), "value": 110.0}]
        result = calculate_max_drawdown_from_curve(curve)
        assert result["max_drawdown_pct"] == pytest.approx(0.0)


class TestCalculateBacktestPerformance:
    def test_full_pipeline_with_mock_backtest_result(self):
        mock_backtest = {
            "available": True,
            "rebalance_frequency_months": 3,
            "periods": [
                {"period_start": date(2025, 1, 1), "period_end": date(2025, 4, 1), "available": True,
                 "portfolio_return_pct": 0.10, "benchmark_return_pct": 0.08, "turnover": 1.0},
                {"period_start": date(2025, 4, 1), "period_end": date(2025, 7, 1), "available": True,
                 "portfolio_return_pct": -0.05, "benchmark_return_pct": -0.04, "turnover": 0.3},
                {"period_start": date(2025, 7, 1), "period_end": date(2025, 10, 1), "available": False,
                 "reason": "No data"},
            ],
        }
        result = calculate_backtest_performance(mock_backtest)
        assert result["available"] is True
        assert result["period_count"] == 2
        assert result["excluded_period_count"] == 1
        assert result["win_rate"] == 0.5
        assert result["cagr"] is not None
        assert result["alpha_vs_benchmark"] is not None

    def test_unavailable_backtest_propagates_reason(self):
        result = calculate_backtest_performance({"available": False, "reason": "test reason"})
        assert result["available"] is False
        assert result["reason"] == "test reason"

    def test_no_usable_periods(self):
        mock_backtest = {
            "available": True,
            "rebalance_frequency_months": 3,
            "periods": [{"period_start": date(2025, 1, 1), "period_end": date(2025, 4, 1), "available": False, "reason": "no data"}],
        }
        result = calculate_backtest_performance(mock_backtest)
        assert result["available"] is False