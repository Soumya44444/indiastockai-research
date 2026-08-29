"""Unit tests for ratio calculators (app/screener/ratio_calculator.py)."""
import pytest
from app.screener.ratio_calculator import (
    gross_margin, ebitda_margin, net_margin, roe, roa, roce,
    debt_to_equity, interest_coverage, current_ratio, cfo_to_pat,
    calculate_all_ratios
)


def make_metrics(**overrides) -> dict:
    """Baseline plausible metrics dict, override individual fields per test."""
    base = {
        "revenue": 1000.0,
        "net_income": 100.0,
        "total_assets": 2000.0,
        "total_equity": 800.0,
        "total_debt": 400.0,
        "operating_cash_flow": 120.0,
        "free_cash_flow": 80.0,
        "ebitda": 250.0,
        "ebit": 180.0,
        "gross_profit": 400.0,
        "interest_expense": 20.0,
        "current_assets": 500.0,
        "current_liabilities": 300.0,
    }
    base.update(overrides)
    return base


class TestMarginRatios:
    def test_gross_margin_normal(self):
        assert gross_margin(make_metrics()) == pytest.approx(0.4)

    def test_ebitda_margin_normal(self):
        assert ebitda_margin(make_metrics()) == pytest.approx(0.25)

    def test_net_margin_normal(self):
        assert net_margin(make_metrics()) == pytest.approx(0.1)

    def test_net_margin_missing_revenue(self):
        assert net_margin(make_metrics(revenue=None)) is None

    def test_net_margin_zero_revenue(self):
        assert net_margin(make_metrics(revenue=0)) is None


class TestReturnRatios:
    def test_roe_normal(self):
        assert roe(make_metrics()) == pytest.approx(0.125)

    def test_roe_zero_equity(self):
        assert roe(make_metrics(total_equity=0)) is None

    def test_roa_normal(self):
        assert roa(make_metrics()) == pytest.approx(0.05)

    def test_roce_normal(self):
        # EBIT / (Total Assets - Current Liabilities) = 180 / (2000-300) = 180/1700
        assert roce(make_metrics()) == pytest.approx(180 / 1700)

    def test_roce_missing_ebit(self):
        assert roce(make_metrics(ebit=None)) is None

    def test_roce_zero_capital_employed(self):
        assert roce(make_metrics(total_assets=300, current_liabilities=300)) is None


class TestBalanceSheetRatios:
    def test_debt_to_equity_normal(self):
        assert debt_to_equity(make_metrics()) == pytest.approx(0.5)

    def test_debt_to_equity_zero_equity(self):
        assert debt_to_equity(make_metrics(total_equity=0)) is None

    def test_interest_coverage_normal(self):
        assert interest_coverage(make_metrics()) == pytest.approx(9.0)

    def test_interest_coverage_zero_interest(self):
        assert interest_coverage(make_metrics(interest_expense=0)) is None

    def test_interest_coverage_uses_absolute_interest(self):
        # Some providers report interest expense as negative
        assert interest_coverage(make_metrics(interest_expense=-20.0)) == pytest.approx(9.0)

    def test_current_ratio_normal(self):
        assert current_ratio(make_metrics()) == pytest.approx(500 / 300)


class TestCashFlowRatios:
    def test_cfo_to_pat_normal(self):
        assert cfo_to_pat(make_metrics()) == pytest.approx(1.2)

    def test_cfo_to_pat_zero_pat(self):
        assert cfo_to_pat(make_metrics(net_income=0)) is None


class TestCalculateAllRatios:
    def test_returns_all_expected_keys(self):
        result = calculate_all_ratios(make_metrics())
        expected_keys = {
            "gross_margin", "ebitda_margin", "net_margin", "roe", "roa", "roce",
            "debt_to_equity", "interest_coverage", "current_ratio", "cfo_to_pat"
        }
        assert set(result.keys()) == expected_keys

    def test_all_none_when_metrics_empty(self):
        result = calculate_all_ratios({})
        assert all(v is None for v in result.values())