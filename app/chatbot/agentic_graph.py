"""
LangGraph state graph for agentic orchestration (project spec Section 20).
Formalizes the pipeline as: Plan -> Execute Tools -> Synthesize Answer.
Each node is a distinct, inspectable step — matching the spec's
requirement to show "Question -> Tools used -> Evidence -> Answer" as
the high-level workflow, without exposing private model chain-of-thought.
"""
import json
from typing import TypedDict
from langgraph.graph import StateGraph, END

from app.chatbot.agentic_planner import plan_tool_calls
from app.chatbot.tools import TOOL_REGISTRY
from app.chatbot.chat import (
    _prepare_evidence_for_llm, synthesize_answer, _verify_answer_numbers,
    _flatten_to_readable_lines
)


class AgentState(TypedDict):
    question: str
    plan: list[dict]
    plan_error: str | None
    tool_results: list[dict]      # raw results, one per planned tool call
    formatted_results: list[dict]  # pre-formatted (for LLM safety, per Phase 9)
    answer: str
    verified: bool
    unmatched_numbers: list[str]


def plan_node(state: AgentState) -> AgentState:
    """Node 1: LLM plans which tool(s) to call."""
    planning_result = plan_tool_calls(state["question"])
    if not planning_result["available"]:
        return {**state, "plan": [], "plan_error": planning_result["reason"]}
    return {**state, "plan": planning_result["plan"], "plan_error": None}


def execute_node(state: AgentState) -> AgentState:
    """Node 2: execute every planned tool call deterministically (real data, no LLM here)."""
    if state["plan_error"] or not state["plan"]:
        return {**state, "tool_results": [], "formatted_results": []}

    tool_results = []
    formatted_results = []
    for step in state["plan"]:
        tool_name = step["tool"]
        args = step["args"]
        fn = TOOL_REGISTRY[tool_name]["fn"]
        try:
            result = fn(**args)
        except Exception as e:
            result = {"available": False, "reason": f"Tool execution failed: {e}"}

        tool_results.append({"tool": tool_name, "args": args, "result": result})
        formatted_results.append({
            "tool": tool_name, "args": args,
            "result": _prepare_evidence_for_llm(result),
        })

    return {**state, "tool_results": tool_results, "formatted_results": formatted_results}


def synthesize_node(state: AgentState) -> AgentState:
    """Node 3: LLM phrases the final answer from ALL combined (pre-formatted) evidence."""
    if state["plan_error"]:
        return {
            **state, "answer": "I couldn't plan how to answer that question with the tools I have.",
            "verified": False, "unmatched_numbers": [],
        }

    if not state["formatted_results"]:
        return {
            **state,
            "answer": "I don't have a tool that can answer this question. I can help with company financials, ratios, valuation, risk metrics, screening, forecasts, backtests, and document search.",
            "verified": False, "unmatched_numbers": [],
        }

    # Combine all formatted results into one evidence payload for the LLM.
    combined_evidence = {f"result_{i}": r for i, r in enumerate(state["formatted_results"])}

    # Reuse Phase 9's synthesis + verification logic against the combined evidence.
    tool_names = ", ".join(r["tool"] for r in state["formatted_results"])
    answer_text = synthesize_answer(state["question"], tool_names, combined_evidence)

    verification = _verify_answer_numbers(answer_text, combined_evidence)
    if not verification["verified"]:
        readable_lines = _flatten_to_readable_lines(combined_evidence)
        answer_text = (
            "I found the data, but my phrasing contained a number that didn't "
            "match the verified source data, so here are the raw verified "
            "figures instead:\n\n" + "\n".join(readable_lines)
        )

    return {
        **state, "answer": answer_text,
        "verified": verification["verified"],
        "unmatched_numbers": verification["unmatched_numbers"],
    }


def build_agent_graph():
    """Builds and compiles the LangGraph state graph: plan -> execute -> synthesize."""
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()


def ask_agentic(question: str) -> dict:
    """Runs the full agentic pipeline for a question. Returns the final
    state, including the full audit trail (plan, tool results, answer)."""
    app_graph = build_agent_graph()
    initial_state: AgentState = {
        "question": question, "plan": [], "plan_error": None,
        "tool_results": [], "formatted_results": [],
        "answer": "", "verified": False, "unmatched_numbers": [],
    }
    final_state = app_graph.invoke(initial_state)
    return final_state


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Compare Reliance and TCS on fundamental score"
    print(f"Question: {question}\n")

    result = ask_agentic(question)

    print("=" * 60)
    print("PLAN:")
    for step in result["plan"]:
        print(f"  {step['tool']}({step['args']})")

    print("\nANSWER:")
    print(result["answer"])
    print("=" * 60)

    print(f"\nVerified: {result['verified']}")
    if result["unmatched_numbers"]:
        print(f"Unmatched numbers caught: {result['unmatched_numbers']}")