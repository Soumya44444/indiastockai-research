"""
LLM orchestration layer (project spec Section 19-20). Uses Ollama
(local, zero-cost) to decide which deterministic tool(s) to call for a
given question, then phrases the final answer FROM the tool's real
output — the LLM never invents a financial number itself.

Shows only the high-level workflow to the user (Question -> Tools used
-> Evidence -> Answer), per spec Section 20 — private model reasoning
is not exposed.
"""
import json
import ollama
from app.chatbot.tools import TOOL_REGISTRY

MODEL_NAME = "llama3.2"


def _build_tool_descriptions() -> str:
    """Formats the tool registry into a prompt-friendly description list."""
    lines = []
    for name, info in TOOL_REGISTRY.items():
        lines.append(f"- {name}: {info['description']}")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return f"""You are a financial research assistant for Indian equities. You have access to these tools:

{_build_tool_descriptions()}

Given a user's question, respond with ONLY a JSON object (no other text) in this exact format:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Rules:
- Pick exactly ONE tool that best answers the question.
- Ticker format is always like "RELIANCE.NS", "TCS.NS" (NSE suffix).
- If the question doesn't clearly map to any tool, respond with: {{"tool": null, "args": {{}}}}
- Never invent or guess a financial number yourself — only select a tool.
"""


def select_tool(user_question: str) -> dict:
    """
    Asks the LLM which tool to call for a given question. Returns the
    parsed {tool, args} dict, or an error if the LLM's response isn't
    valid JSON (fails safely rather than guessing what it meant).
    """
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": user_question},
        ],
    )

    raw_content = response["message"]["content"].strip()

    # Models sometimes wrap JSON in markdown code fences despite instructions — strip if present.
    if raw_content.startswith("```"):
        raw_content = raw_content.strip("`")
        if raw_content.lower().startswith("json"):
            raw_content = raw_content[4:].strip()

    try:
        parsed = json.loads(raw_content)
        return {"available": True, "tool": parsed.get("tool"), "args": parsed.get("args", {})}
    except json.JSONDecodeError:
        return {"available": False, "reason": f"LLM did not return valid JSON. Raw response: {raw_content[:200]}"}


def call_tool(tool_name: str, args: dict) -> dict:
    """Executes the selected tool with the given arguments."""
    if tool_name not in TOOL_REGISTRY:
        return {"available": False, "reason": f"Unknown tool: {tool_name}"}

    fn = TOOL_REGISTRY[tool_name]["fn"]
    try:
        return fn(**args)
    except TypeError as e:
        return {"available": False, "reason": f"Tool called with invalid arguments: {e}"}
    except Exception as e:
        return {"available": False, "reason": f"Tool execution failed: {e}"}


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is Reliance's ROE and other ratios?"
    print(f"Question: {question}\n")

    print("Asking LLM which tool to use...")
    selection = select_tool(question)

    if not selection["available"]:
        print(f"Tool selection failed: {selection['reason']}")
    elif selection["tool"] is None:
        print("LLM determined no tool matches this question.")
    else:
        print(f"Selected tool: {selection['tool']}")
        print(f"Args: {selection['args']}\n")

        result = call_tool(selection["tool"], selection["args"])
        print("Tool result (raw):")
        print(json.dumps(result, indent=2, default=str)[:1000])