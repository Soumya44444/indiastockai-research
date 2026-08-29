"""Unit tests for the financial metric validation layer."""
import pytest
from app.data.validators.financial_validator import (
    classify_unit, validate_metric, validate_metrics, summarize_validation
)


class TestClassifyUnit:
    def test_ratio_metric(self):
        assert classify_unit("tax_rate_for_calcs", "INR") == "RATIO"

    def test_margin_metric(self):
        assert classify_unit("gross_margin", "INR") == "RATIO"

    def test_per_share_metric(self):
        assert classify_unit("basic_eps", "INR") == "INR_PER_SHARE"

    def test_days_metric(self):
        assert classify_unit("days_sales_outstanding", "INR") == "DAYS"

    def test_currency_metric_unaffected(self):
        assert classify_unit("total_revenue", "INR") == "INR"

    def test_no_false_substring_match(self):
        # Regression test: "operation" contains letters r-a-t-i-o but must NOT match RATIO
        assert classify_unit("net_income_from_continuing_operation", "INR") == "INR"

    def test_no_false_substring_match_variant(self):
        assert classify_unit("cash_flow_from_operations", "INR") == "INR"


class TestValidateMetric:
    def _make_record(self, metric_name="total_revenue", value=1000.0, unit="INR"):
        return {
            "metric_name": metric_name,
            "statement_type": "income",
            "period_type": "annual",
            "period_end_date": "2026-03-31",
            "value": value,
            "unit": unit,
            "source": "yfinance",
        }

    def test_normal_currency_value_is_ok(self):
        record = self._make_record(value=1_000_000.0)
        result = validate_metric(record)
        assert result["data_quality_status"] == "ok"
        assert result["is_missing"] is False

    def test_missing_value_flagged_missing(self):
        record = self._make_record(value=None)
        result = validate_metric(record)
        assert result["data_quality_status"] == "missing"
        assert result["is_missing"] is True

    def test_implausible_ratio_flagged(self):
        record = self._make_record(metric_name="tax_rate_for_calcs", value=50.0)  # 5000%, implausible
        result = validate_metric(record)
        assert result["data_quality_status"] == "flagged"

    def test_plausible_ratio_ok(self):
        record = self._make_record(metric_name="tax_rate_for_calcs", value=0.25)  # 25%, normal
        result = validate_metric(record)
        assert result["data_quality_status"] == "ok"

    def test_implausibly_large_currency_flagged(self):
        record = self._make_record(value=1e15)  # absurdly large
        result = validate_metric(record)
        assert result["data_quality_status"] == "flagged"

    def test_does_not_mutate_input(self):
        record = self._make_record()
        original = dict(record)
        validate_metric(record)
        assert record == original


class TestSummarize:
    def test_summary_counts(self):
        records = [
            {"data_quality_status": "ok"},
            {"data_quality_status": "ok"},
            {"data_quality_status": "flagged"},
            {"data_quality_status": "missing"},
        ]
        summary = summarize_validation(records)
        assert summary == {"total": 4, "ok": 2, "flagged": 1, "missing": 1}