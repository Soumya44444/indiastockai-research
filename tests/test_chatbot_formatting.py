"""Unit tests for chatbot number formatting (app/chatbot/formatting.py).
Includes a regression test for the real scale-error bug found during
development (LLM misconverting large raw numbers)."""
import pytest
from app.chatbot.formatting import format_inr, format_percent, format_ratio, format_metrics_dict


class TestFormatInr:
    def test_lakh_crore_range(self):
        # 10,572,190,000,000 = ~10.57 lakh crore (the real RELIANCE.NS revenue
        # that exposed the LLM's scale-conversion bug)
        assert format_inr(10572190000000.0) == "₹10.57 lakh crore"

    def test_crore_range(self):
        # 691,970,000,000 = ~69,197 crore (the real FCF value; not yet at
        # lakh-crore scale)
        assert format_inr(691970000000.0) == "₹69197.00 crore"

    def test_small_value_below_crore(self):
        assert format_inr(5_000_000.0) == "₹5,000,000"

    def test_none_returns_na(self):
        assert format_inr(None) == "N/A"

    def test_negative_value_preserves_sign(self):
        result = format_inr(-691970000000.0)
        assert result.startswith("-₹")

    def test_zero_value(self):
        assert format_inr(0.0) == "₹0"

    def test_regression_operating_cash_flow(self):
        # Real value that the LLM misreported as "19.2 trillion" (10x too high)
        assert format_inr(1921130000000.0) == "₹1.92 lakh crore"

    def test_regression_ebit(self):
        # Real value that the LLM misreported as "147.218 billion" (10x too low)
        assert format_inr(1472180000000.0) == "₹1.47 lakh crore"


class TestFormatPercent:
    def test_normal_percentage(self):
        assert format_percent(0.08934991095428249) == "8.93%"

    def test_none_returns_na(self):
        assert format_percent(None) == "N/A"

    def test_negative_percentage(self):
        assert format_percent(-0.15) == "-15.00%"


class TestFormatRatio:
    def test_normal_ratio(self):
        assert format_ratio(0.44025087663020035) == "0.44x"

    def test_custom_suffix(self):
        assert format_ratio(6.12, suffix="") == "6.12"

    def test_none_returns_na(self):
        assert format_ratio(None) == "N/A"


class TestFormatMetricsDict:
    def test_mixed_metric_types(self):
        metrics = {
            "revenue": 10572190000000.0,
            "roe": 0.0893,
            "debt_to_equity": 0.44,
        }
        result = format_metrics_dict(metrics)
        assert result["revenue"] == "₹10.57 lakh crore"
        assert result["roe"] == "8.93%"
        assert result["debt_to_equity"] == "0.44x"

    def test_unrecognized_key_passed_through_as_string(self):
        metrics = {"some_unknown_field": 42}
        result = format_metrics_dict(metrics)
        assert result["some_unknown_field"] == "42"