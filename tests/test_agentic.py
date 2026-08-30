"""Unit tests for agentic orchestration pure-logic pieces
(app/chatbot/agentic_planner.py and app/chatbot/agentic_graph.py's
non-LLM node logic)."""
import pytest
from app.chatbot.agentic_planner import plan_tool_calls, MAX_TOOL_CALLS_PER_QUERY
from app.chatbot.tools import TOOL_REGISTRY


class TestPlanToolCallsValidation:
    """These tests exercise plan_tool_calls' validation logic by feeding
    it questions and checking the returned plan's structure — they don't
    mock the LLM call itself (that's covered by the manual integration
    tests already run against real Ollama output), but validate that
    ANY plan returned respects the registry and cap constraints."""

    def test_valid_plan_only_uses_known_tools(self):
        result = plan_tool_calls("What is Reliance's ROE?")
        if result["available"]:
            for step in result["plan"]:
                assert step["tool"] in TOOL_REGISTRY

    def test_plan_never_exceeds_max_calls(self):
        result = plan_tool_calls("Compare Reliance and TCS on fundamentals")
        if result["available"]:
            assert len(result["plan"]) <= MAX_TOOL_CALLS_PER_QUERY


class TestPlanStructureValidationLogic:
    """Directly tests the validation logic inside plan_tool_calls by
    constructing malformed inputs bypassing the LLM call, via monkeypatching."""

    def test_rejects_non_list_response(self, monkeypatch):
        import app.chatbot.agentic_planner as planner_module

        class FakeResponse:
            def __getitem__(self, key):
                return {"content": '{"not": "a list"}'}

        monkeypatch.setattr(planner_module.ollama, "chat", lambda **kwargs: FakeResponse())
        result = plan_tool_calls("test question")
        assert result["available"] is False
        assert "not a list" in result["reason"].lower()

    def test_rejects_invalid_json(self, monkeypatch):
        import app.chatbot.agentic_planner as planner_module

        class FakeResponse:
            def __getitem__(self, key):
                return {"content": "this is not json at all"}

        monkeypatch.setattr(planner_module.ollama, "chat", lambda **kwargs: FakeResponse())
        result = plan_tool_calls("test question")
        assert result["available"] is False

    def test_rejects_unknown_tool_in_plan(self, monkeypatch):
        import app.chatbot.agentic_planner as planner_module
        import json as json_module

        class FakeResponse:
            def __getitem__(self, key):
                return {"content": json_module.dumps([{"tool": "nonexistent_tool", "args": {}}])}

        monkeypatch.setattr(planner_module.ollama, "chat", lambda **kwargs: FakeResponse())
        result = plan_tool_calls("test question")
        assert result["available"] is False
        assert "unknown tool" in result["reason"].lower()

    def test_rejects_plan_exceeding_max_calls(self, monkeypatch):
        import app.chatbot.agentic_planner as planner_module
        import json as json_module

        oversized_plan = [{"tool": "get_company_financials", "args": {"ticker": "X.NS"}}] * (MAX_TOOL_CALLS_PER_QUERY + 1)

        class FakeResponse:
            def __getitem__(self, key):
                return {"content": json_module.dumps(oversized_plan)}

        monkeypatch.setattr(planner_module.ollama, "chat", lambda **kwargs: FakeResponse())
        result = plan_tool_calls("test question")
        assert result["available"] is False
        assert "exceeded" in result["reason"].lower()

    def test_strips_markdown_code_fences(self, monkeypatch):
        import app.chatbot.agentic_planner as planner_module
        import json as json_module

        valid_plan = [{"tool": "get_company_financials", "args": {"ticker": "RELIANCE.NS"}}]
        fenced_content = f"```json\n{json_module.dumps(valid_plan)}\n```"

        class FakeResponse:
            def __getitem__(self, key):
                return {"content": fenced_content}

        monkeypatch.setattr(planner_module.ollama, "chat", lambda **kwargs: FakeResponse())
        result = plan_tool_calls("test question")
        assert result["available"] is True
        assert result["plan"] == valid_plan


class TestAgenticGraphNodes:
    """Tests the execute_node's tool-execution logic directly (no LLM
    involved in this node) using a real, fast tool call."""

    def test_execute_node_runs_real_tool_and_formats(self):
        from app.chatbot.agentic_graph import execute_node

        state = {
            "question": "test", "plan": [{"tool": "get_company_financials", "args": {"ticker": "RELIANCE.NS"}}],
            "plan_error": None, "tool_results": [], "formatted_results": [],
            "answer": "", "verified": False, "unmatched_numbers": [],
        }
        result_state = execute_node(state)
        assert len(result_state["tool_results"]) == 1
        assert result_state["tool_results"][0]["tool"] == "get_company_financials"
        assert result_state["tool_results"][0]["result"]["available"] is True

    def test_execute_node_skips_when_plan_error(self):
        from app.chatbot.agentic_graph import execute_node

        state = {
            "question": "test", "plan": [], "plan_error": "some planning error",
            "tool_results": [], "formatted_results": [],
            "answer": "", "verified": False, "unmatched_numbers": [],
        }
        result_state = execute_node(state)
        assert result_state["tool_results"] == []

    def test_execute_node_handles_tool_exception_gracefully(self):
        from app.chatbot.agentic_graph import execute_node

        # Invalid ticker triggers the tool's own "not found" path, not a crash
        state = {
            "question": "test", "plan": [{"tool": "get_company_financials", "args": {"ticker": "NOTREAL.NS"}}],
            "plan_error": None, "tool_results": [], "formatted_results": [],
            "answer": "", "verified": False, "unmatched_numbers": [],
        }
        result_state = execute_node(state)
        assert result_state["tool_results"][0]["result"]["available"] is False