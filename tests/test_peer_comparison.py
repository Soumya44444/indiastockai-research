"""Unit tests for peer ranking logic (app/analysis/peer_comparison.py)."""
import pytest
from app.analysis.peer_comparison import _rank_and_compare


class TestRankAndCompare:
    def test_best_in_group_higher_is_better(self):
        target = {"ticker": "A", "roe": 0.30}
        peers = [{"ticker": "B", "roe": 0.20}, {"ticker": "C", "roe": 0.10}]
        result = _rank_and_compare(target, peers, "roe", higher_is_better=True)
        assert result["rank"] == 1
        assert result["position"] == "best in peer group"

    def test_worst_in_group_higher_is_better(self):
        target = {"ticker": "A", "roe": 0.05}
        peers = [{"ticker": "B", "roe": 0.20}, {"ticker": "C", "roe": 0.30}]
        result = _rank_and_compare(target, peers, "roe", higher_is_better=True)
        assert result["rank"] == 3
        assert result["position"] == "below average"

    def test_lower_is_better_field(self):
        # e.g. debt_to_equity: lower is better, so low value should rank 1st
        target = {"ticker": "A", "debt_to_equity": 0.1}
        peers = [{"ticker": "B", "debt_to_equity": 0.5}, {"ticker": "C", "debt_to_equity": 0.8}]
        result = _rank_and_compare(target, peers, "debt_to_equity", higher_is_better=False)
        assert result["rank"] == 1
        assert result["position"] == "best in peer group"

    def test_missing_target_value_returns_insufficient_data(self):
        target = {"ticker": "A", "roe": None}
        peers = [{"ticker": "B", "roe": 0.20}]
        result = _rank_and_compare(target, peers, "roe")
        assert result["rank"] is None
        assert result["position"] == "insufficient data"

    def test_no_peers_returns_insufficient_data(self):
        target = {"ticker": "A", "roe": 0.20}
        result = _rank_and_compare(target, [], "roe")
        assert result["rank"] is None
        assert result["position"] == "insufficient data"

    def test_peers_with_missing_values_are_excluded_from_ranking(self):
        target = {"ticker": "A", "roe": 0.20}
        peers = [{"ticker": "B", "roe": None}, {"ticker": "C", "roe": 0.10}]
        result = _rank_and_compare(target, peers, "roe", higher_is_better=True)
        # Only A and C have valid values -> target ranks 1st of 2, not 1st of 3
        assert result["total"] == 2
        assert result["rank"] == 1