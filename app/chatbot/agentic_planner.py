"""
Multi-tool query planning (project spec Section 20: Agentic Architecture).
Extends Phase 9's single-tool orchestration to handle questions that
genuinely need MULTIPLE tool calls (e.g. "Compare Reliance and TCS",
"Is Infosys a good investment?"). The LLM plans a SEQUENCE of tool
calls; each is executed deterministically; results are combined before
final answer synthesis. The LLM still never invents a number — it only
selects tools and (later) phrases the answer from real combined evidence.
"""
import json
import ollama
from app.chatbot.tools import TOOL_REGISTRY

MODEL_NAME = "llama3.2"
MAX_TOOL_CALLS_PER_QUERY = 4  # sanity cap — prevents runaway plans


def _build_tool_descriptions() -> str:
    lines = []
    for name, info in TOOL_REGISTRY.items():
        lines.append(f"- {name}: {info['description']}")
    return "\n".join(lines)


def _build_planning_prompt() -> str:
    return f"""You are a financial research planning assistant for Indian equities. You have access to these tools:

{_build_tool_descriptions()}

Given a user's question, respond with ONLY a JSON array of tool calls
needed to fully answer it (no other text). Each item in the array must be:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Rules:
- For a SIMPLE question about ONE company/topic, return an array with ONE tool call.
- For a COMPARISON question (e.g. "compare X and Y"), return one tool call PER company, using the SAME tool for each so results are comparable.
- For a BROAD question (e.g. "is X a good investment?"), you may plan up to {MAX_TOOL_CALLS_PER_QUERY} DIFFERENT tools (e.g. fundamental score + valuation + risk) for the SAME company, to build a complete picture.
- Never plan more than {MAX_TOOL_CALLS_PER_QUERY} tool calls total.
- Ticker format is always like "RELIANCE.NS", "TCS.NS" (NSE suffix).
- If nothing matches, return an empty array: []

Example for "Compare Reliance and TCS on fundamentals":
[{{"tool": "get_fundamental_score", "args": {{"ticker": "RELIANCE.NS"}}}}, {{"tool": "get_fundamental_score", "args": {{"ticker": "TCS.NS"}}}}]
"""


def plan_tool_calls(user_question: str) -> dict:
    """
    Asks the LLM to plan a sequence of tool calls for a question.
    Fails safely (returns available=False) rather than guessing if the
    LLM's response isn't valid JSON or exceeds the sanity cap.
    """
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": _build_planning_prompt()},
            {"role": "user", "content": user_question},
        ],
    )

    raw_content = response["message"]["content"].strip()

    if raw_content.startswith("```"):
        raw_content = raw_content.strip("`")
        if raw_content.lower().startswith("json"):
            raw_content = raw_content[4:].strip()

    try:
        plan = json.loads(raw_content)
    except json.JSONDecodeError:
        return {"available": False, "reason": f"LLM did not return valid JSON. Raw response: {raw_content[:200]}"}

    if not isinstance(plan, list):
        return {"available": False, "reason": "LLM response was valid JSON but not a list of tool calls."}

    if len(plan) > MAX_TOOL_CALLS_PER_QUERY:
        return {"available": False, "reason": f"Plan exceeded max allowed tool calls ({MAX_TOOL_CALLS_PER_QUERY})."}

    for step in plan:
        if not isinstance(step, dict) or "tool" not in step:
            return {"available": False, "reason": f"Malformed plan step: {step}"}
        if step["tool"] not in TOOL_REGISTRY:
            return {"available": False, "reason": f"Plan references unknown tool: {step['tool']}"}

    return {"available": True, "plan": plan}


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Compare Reliance and TCS on fundamentals"
    print(f"Question: {question}\n")

    result = plan_tool_calls(question)
    if not result["available"]:
        print(f"Planning failed: {result['reason']}")
    else:
        print(f"Planned {len(result['plan'])} tool call(s):")
        for step in result["plan"]:
            print(f"  {step['tool']}({step['args']})")