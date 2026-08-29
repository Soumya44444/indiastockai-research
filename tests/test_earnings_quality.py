"""Unit tests for earnings-quality checks (app/analysis/earnings_quality.py)."""
import pytest
from app.analysis.earnings_quality import (
    check_cfo_pat_divergence, check_weak_fcf_conversion, _is_financial_company,
    FINANCIAL_SECTORS
)


def make_metrics(**overrides) -> dict:
    base = {
        "revenue": 1000.0,
        "net_income": 100.0,
        "operating_cash_flow": 100.0,
        "free_cash_flow": 80.0,
    }
    base.update(overrides)
    return base


class FakeCompany:
    """Lightweight stand-in for a Company row, avoids DB dependency."""
    def __init__(self, sector=None):
        self.sector = sector


class TestCfoPatDivergence:
    def test_healthy_ratio_no_flag(self):
        metrics = make_metrics(operating_cash_flow=100.0, net_income=100.0)  # ratio = 1.0
        assert check_cfo_pat_divergence(metrics) is None

    def test_low_ratio_flags_warning(self):
        metrics = make_metrics(operating_cash_flow=40.0, net_income=100.0)  # ratio = 0.4
        result = check_cfo_pat_divergence(metrics)
        assert result is not None
        assert result["severity"] == "warning"

    def test_very_low_ratio_flags_high(self):
        metrics = make_metrics(operating_cash_flow=10.0, net_income=100.0)  # ratio = 0.1
        result = check_cfo_pat_divergence(metrics)
        assert result["severity"] == "high"

    def test_negative_ratio_flags_high(self):
        metrics = make_metrics(operating_cash_flow=-50.0, net_income=100.0)  # ratio = -0.5
        result = check_cfo_pat_divergence(metrics)
        assert result is not None
        assert result["severity"] == "high"

    def test_missing_data_returns_none(self):
        metrics = make_metrics(net_income=0)  # ratio calc returns None on zero PAT
        assert check_cfo_pat_divergence(metrics) is None


class TestWeakFcfConversion:
    def test_healthy_fcf_no_flag(self):
        metrics = make_metrics(free_cash_flow=90.0, net_income=100.0)  # ratio = 0.9
        assert check_weak_fcf_conversion(metrics) is None

    def test_weak_fcf_flags_warning(self):
        metrics = make_metrics(free_cash_flow=20.0, net_income=100.0)  # ratio = 0.2
        result = check_weak_fcf_conversion(metrics)
        assert result is not None
        assert result["severity"] == "warning"

    def test_negative_pat_does_not_flag(self):
        # Function requires positive PAT as denominator basis; negative/zero PAT
        # makes the ratio meaningless, so it should skip rather than misreport.
        metrics = make_metrics(free_cash_flow=20.0, net_income=-50.0)
        assert check_weak_fcf_conversion(metrics) is None


class TestFinancialSectorExclusion:
    def test_bank_is_financial(self):
        company = FakeCompany(sector="Financial Services")
        assert _is_financial_company(company) is True

    def test_non_financial_sector(self):
        company = FakeCompany(sector="Consumer Defensive")
        assert _is_financial_company(company) is False

    def test_none_sector_is_not_financial(self):
        company = FakeCompany(sector=None)
        assert _is_financial_company(company) is False

    def test_all_expected_financial_labels_present(self):
        # Regression guard: if yfinance's exact label ever changes, this
        # test should be the first thing to catch it.
        assert "Financial Services" in FINANCIAL_SECTORS