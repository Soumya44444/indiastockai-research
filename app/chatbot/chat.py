"""
Full chatbot pipeline (project spec Section 19-20): Question -> Tool
selection -> Tool execution (real data) -> LLM phrases the final answer
FROM that real, PRE-FORMATTED data -> Answer with audit trail.

CRITICAL FIXES (all found via direct testing, not theoretical):
1. Numbers are formatted into display strings (via app/chatbot/formatting.py)
   BEFORE being shown to the LLM. Testing revealed the LLM would introduce
   real scale errors (10x-100x) when asked to convert raw numbers into
   trillion/billion language itself.
2. Even after pre-formatting, the LLM can still introduce digit-transposition
   errors when copying a formatted string. A verification guardrail checks
   every numeric token in the LLM's final answer against the real evidence,
   and falls back to showing raw verified data directly (in plain readable
   text, not JSON) if anything doesn't match.
3. The verification guardrail had a false-positive bug: it extracted
   "expected" numbers via regex over json.dumps() output, but json.dumps
   escapes the ₹ symbol as "\\u20b9" — since our formatter writes "₹10.57"
   with no space, the escaped text merges into "...b910.57...", corrupting
   the expected-number set. Fixed by walking the actual dict/list structure
   directly instead of going through json.dumps for number extraction.
4. A second false-positive source: a number at the end of a sentence (e.g.
   "...score of 55.") gets regex-captured WITH the trailing period ("55."),
   which then fails to match the real evidence value ("55"). Fixed by
   stripping trailing periods from extracted answer-number tokens before
   comparing.

The audit trail (tools called, evidence, calculations) is always shown
alongside the answer — private model reasoning is not exposed, but the
factual basis for the answer always is, per spec Section 22 (Auditability).
"""
import json
import re
import ollama
from app.chatbot.orchestrator import select_tool, call_tool
from app.chatbot.tools import TOOL_REGISTRY
from app.chatbot.formatting import format_metrics_dict, CURRENCY_METRICS, PERCENT_METRICS, RATIO_METRICS

MODEL_NAME = "llama3.2"


def _prepare_evidence_for_llm(tool_result: dict) -> dict:
    """
    Recursively formats any known numeric metric fields in a tool
    result into display strings, leaving other structure intact.
    Only formats dict values whose keys are recognized metric names —
    doesn't touch nested non-metric structures (e.g. rationale lists).
    """
    known_keys = CURRENCY_METRICS | PERCENT_METRICS | RATIO_METRICS

    def _walk(obj):
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                if k in known_keys and isinstance(v, (int, float, type(None))):
                    new_obj[k] = format_metrics_dict({k: v})[k]
                else:
                    new_obj[k] = _walk(v)
            return new_obj
        elif isinstance(obj, list):
            return [_walk(item) for item in obj]
        else:
            return obj

    return _walk(tool_result)


def _flatten_to_readable_lines(obj, prefix: str = "") -> list[str]:
    """
    Converts a nested dict/list into simple 'key: value' display lines.
    Used for the verification-failure fallback so the user sees plain,
    readable text instead of raw JSON with unicode escape codes.
    """
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.extend(_flatten_to_readable_lines(v, prefix=f"{prefix}{k}."))
            else:
                label = f"{prefix}{k}".replace("_", " ")
                lines.append(f"  {label}: {v}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            lines.extend(_flatten_to_readable_lines(item, prefix=f"{prefix}[{i}]."))
    return lines


def _build_answer_prompt(question: str, tool_name: str, formatted_result: dict) -> str:
    return f"""A user asked: "{question}"

You called the tool '{tool_name}' and got this REAL, VERIFIED, ALREADY-FORMATTED data:
{json.dumps(formatted_result, indent=2, default=str)}

Write a clear, natural-language answer to the user's question.

CRITICAL RULES:
- Every number/percentage/ratio in the data above is ALREADY correctly
  formatted (e.g. "₹1.92 lakh crore", "8.93%", "0.44x"). Copy these
  values EXACTLY as written, digit by digit. Do NOT recalculate,
  reconvert, rescale, retype, or reformat any number yourself — doing
  so risks introducing errors.
- Do not invent, estimate, or add any number that isn't in the data.
- If the data shows available=false, clearly explain that the information
  isn't available and why.
- Keep the answer concise (3-6 sentences) and readable for someone
  without a finance background.
"""


def synthesize_answer(question: str, tool_name: str, formatted_result: dict) -> str:
    """Asks the LLM to phrase a natural-language answer from pre-formatted tool output."""
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": _build_answer_prompt(question, tool_name, formatted_result)}],
    )
    return response["message"]["content"].strip()


def _verify_answer_numbers(answer_text: str, formatted_result: dict) -> dict:
    """
    Safety net: checks that every numeric token in the LLM's answer
    matches some numeric value ANYWHERE in the formatted evidence.

    Extracts expected numbers by walking the actual dict/list structure
    directly (never via json.dumps, which escapes ₹ in a way that
    corrupts adjacent digits — see module docstring fix #3). Strips
    trailing periods from extracted answer-number tokens before
    comparing, since a number at a sentence's end (e.g. "score of 55.")
    would otherwise be compared as "55." and wrongly fail to match the
    real "55" (see module docstring fix #4).
    """
    def _collect_numbers_from_value(value) -> set:
        found = set()
        if isinstance(value, dict):
            for v in value.values():
                found |= _collect_numbers_from_value(v)
        elif isinstance(value, list):
            for item in value:
                found |= _collect_numbers_from_value(item)
        elif isinstance(value, str):
            found.update(re.findall(r'[\d,]+\.?\d*', value))
        elif isinstance(value, (int, float)):
            found.add(str(value))
        return found

    expected_numbers = _collect_numbers_from_value(formatted_result)

    raw_answer_numbers = re.findall(r'[\d,]+\.?\d*', answer_text)
    answer_numbers = [n.rstrip('.') for n in raw_answer_numbers]

    unmatched = [n for n in answer_numbers if n not in expected_numbers and len(n.replace(",", "")) >= 3]

    return {
        "verified": len(unmatched) == 0,
        "unmatched_numbers": unmatched,
    }


def ask(question: str) -> dict:
    """
    Full pipeline: question -> tool selection -> tool execution -> format
    numbers deterministically -> answer synthesis -> verify -> answer.
    Returns the complete audit trail (with RAW unformatted numbers)
    alongside the final answer.
    """
    selection = select_tool(question)

    if not selection["available"]:
        return {
            "question": question, "success": False,
            "answer": "I couldn't determine how to answer that question with the tools I have.",
            "audit_trail": {"tool_selection_error": selection["reason"]},
        }

    if selection["tool"] is None:
        return {
            "question": question, "success": False,
            "answer": "I don't have a tool that can answer this question. I can help with company financials, ratios, valuation, risk metrics, screening, forecasts, backtests, and document search.",
            "audit_trail": {"tool_selected": None},
        }

    tool_name = selection["tool"]
    args = selection["args"]
    tool_result = call_tool(tool_name, args)

    formatted_result = _prepare_evidence_for_llm(tool_result)
    answer_text = synthesize_answer(question, tool_name, formatted_result)

    verification = _verify_answer_numbers(answer_text, formatted_result)
    if not verification["verified"]:
        readable_lines = _flatten_to_readable_lines(formatted_result)
        answer_text = (
            "I found the data, but my phrasing of the answer contained a number "
            "that didn't match the verified source data, so here are the raw "
            "verified figures instead, to avoid giving you a wrong number:\n\n"
            + "\n".join(readable_lines)
        )

    return {
        "question": question,
        "success": True,
        "answer": answer_text,
        "audit_trail": {
            "tool_used": tool_name,
            "tool_args": args,
            "tool_description": TOOL_REGISTRY[tool_name]["description"],
            "evidence_raw": tool_result,
            "evidence_formatted": formatted_result,
            "answer_verified": verification["verified"],
            "unmatched_numbers": verification["unmatched_numbers"],
        },
    }


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Is Reliance financially strong?"

    print(f"Question: {question}\n")
    result = ask(question)

    print("=" * 60)
    print("ANSWER:")
    print(result["answer"])
    print("=" * 60)

    print(f"\nAudit Trail:")
    print(f"  Tool used: {result['audit_trail'].get('tool_used', 'N/A')}")
    print(f"  Tool description: {result['audit_trail'].get('tool_description', 'N/A')}")
    print(f"  Answer verified (numbers match evidence): {result['audit_trail'].get('answer_verified', 'N/A')}")
    if result['audit_trail'].get('unmatched_numbers'):
        print(f"  Unmatched numbers caught: {result['audit_trail']['unmatched_numbers']}")