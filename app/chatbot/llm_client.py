"""
Shared LLM client — switches between Ollama (local, zero-cost) and Groq
(free-tier cloud, used for the public deployment) based on the
LLM_PROVIDER environment variable.

Usage (drop-in replacement for the old `ollama.chat(...)` calls):

    from app.chatbot.llm_client import chat
    response = chat(messages=[...])
    content = response["message"]["content"]

This keeps the exact same response shape (`response["message"]["content"]`)
that agentic_planner.py, chat.py, and orchestrator.py already expect, so
those files only need their `import ollama` + `ollama.chat(...)` calls
swapped for `from app.chatbot.llm_client import chat` + `chat(...)`.

Provider is chosen via the LLM_PROVIDER env var:
    LLM_PROVIDER=ollama   -> uses local Ollama (default, for local dev)
    LLM_PROVIDER=groq     -> uses Groq's free-tier API (for deployment)

Model names differ per provider since Ollama and Groq don't host the same
models — set separately below rather than reusing a single MODEL_NAME.
"""
import os

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
# NOTE: Groq deprecated its Llama chat models (llama-3.1-8b-instant,
# llama-3.3-70b-versatile) — confirmed via a 404 model_not_found error in
# production. Their current recommendation for general-purpose/reasoning
# workloads is the open-weight GPT-OSS models. Using the smaller 20B
# variant here since our tasks (tool selection, JSON planning, answer
# phrasing) are lightweight — matches the role the old 8b-instant model
# played. Check https://console.groq.com/docs/models if this ever 404s
# again, since Groq updates its lineup fairly often.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


def chat(messages: list[dict]) -> dict:
    """
    Sends `messages` (list of {"role": ..., "content": ...} dicts) to
    whichever provider is configured, and returns a normalized dict:
        {"message": {"content": "<text>"}}
    so existing call sites don't need to change how they read the response.
    """
    if LLM_PROVIDER == "groq":
        return _chat_groq(messages)
    return _chat_ollama(messages)


def _chat_ollama(messages: list[dict]) -> dict:
    import ollama  # imported lazily so Groq-only deployments don't need it installed
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    return {"message": {"content": response["message"]["content"]}}


def _chat_groq(messages: list[dict]) -> dict:
    from groq import Groq  # imported lazily so local-only dev doesn't need it installed
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
            "Add GROQ_API_KEY to your .env (local) or your hosting platform's "
            "environment variables (production)."
        )
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(model=GROQ_MODEL, messages=messages)
    return {"message": {"content": response.choices[0].message.content}}