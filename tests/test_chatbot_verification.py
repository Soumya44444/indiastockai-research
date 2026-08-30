"""Unit tests for the answer-verification safety guardrail
(app/chatbot/chat.py::_verify_answer_numbers). This guardrail was added
after live testing showed the LLM could introduce digit-transposition
errors even when copying already-correctly-formatted numbers — these
tests lock in that specific failure mode as a permanent regression check."""
import pytest
from app.chatbot.chat import _verify_answer_numbers, _flatten_to_readable_lines


class TestVerifyAnswerNumbers:
    def test_correct_answer_verifies(self):
        formatted_result = {"metrics": {"revenue": "₹10.57 lakh crore", "roe": "8.93%"}}
        answer = "Reliance's revenue is ₹10.57 lakh crore and its ROE is 8.93%."
        result = _verify_answer_numbers(answer, formatted_result)
        assert result["verified"] is True
        assert result["unmatched_numbers"] == []

    def test_regression_digit_transposition_caught(self):
        # The exact real bug: LLM wrote "96,797" when the real value was
        # "69,197" — this must always be caught, never silently pass.
        formatted_result = {"metrics": {"free_cash_flow": "₹69197.00 crore"}}
        answer = "Reliance's free cash flow is ₹96,797.00 crore."
        result = _verify_answer_numbers(answer, formatted_result)
        assert result["verified"] is False
        assert any("96,797" in n or "96797" in n for n in result["unmatched_numbers"])

    def test_regression_scale_error_caught(self):
        # The other real bug: LLM invented "19.2 lakh crore" when the real
        # value was "1.92 lakh crore" — must be caught.
        formatted_result = {"metrics": {"operating_cash_flow": "₹1.92 lakh crore"}}
        answer = "Operating cash flow was ₹19.2 lakh crore."
        result = _verify_answer_numbers(answer, formatted_result)
        assert result["verified"] is False

    def test_small_numbers_below_threshold_ignored(self):
        # Numbers under 3 digits (e.g. "8.93" in "8.93%") shouldn't cause
        # false positives from incidental short numeric tokens in prose.
        formatted_result = {"metrics": {"roe": "8.93%"}}
        answer = "The company has 5 business segments and an ROE of 8.93%."
        result = _verify_answer_numbers(answer, formatted_result)
        assert result["verified"] is True

    def test_empty_answer_verifies_trivially(self):
        formatted_result = {"metrics": {"revenue": "₹10.57 lakh crore"}}
        result = _verify_answer_numbers("No numeric claims here.", formatted_result)
        assert result["verified"] is True

    def test_nested_dict_values_checked(self):
        formatted_result = {
            "targets": {"base": {"upside_pct": "-41.90%"}}
        }
        # upside_pct isn't in the known-keys set used by the flatten walk
        # in chat.py's _prepare_evidence_for_llm, but this test checks the
        # verification function's own recursive collection independently.
        answer = "The upside is -41.90%."
        result = _verify_answer_numbers(answer, formatted_result)
        assert result["verified"] is True


class TestFlattenToReadableLines:
    def test_flat_dict(self):
        obj = {"revenue": "₹10.57 lakh crore", "roe": "8.93%"}
        lines = _flatten_to_readable_lines(obj)
        assert len(lines) == 2
        assert any("revenue" in l for l in lines)

    def test_nested_dict_uses_dotted_prefix(self):
        obj = {"metrics": {"revenue": "₹10.57 lakh crore"}}
        lines = _flatten_to_readable_lines(obj)
        assert any("metrics.revenue" in l or "metrics revenue" in l for l in lines)

    def test_underscores_replaced_with_spaces_in_labels(self):
        obj = {"operating_cash_flow": "₹1.92 lakh crore"}
        lines = _flatten_to_readable_lines(obj)
        assert any("operating cash flow" in l for l in lines)