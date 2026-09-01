"""
Shared LLM client — switches between Ollama (local, zero-cost) and Groq
(free-tier cloud, used for the public deployment) based on the
LLM_PROVIDER environment variable.
"""
import os

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")


def chat(messages: list[dict]) -> dict:
    if LLM_PROVIDER == "groq":
        return _chat_groq(messages)
    return _chat_ollama(messages)


def _chat_ollama(messages: list[dict]) -> dict:
    import ollama
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    return {"message": {"content": response["message"]["content"]}}


def _chat_groq(messages: list[dict]) -> dict:
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
            "Add GROQ_API_KEY to your .env or hosting platform's environment variables."
        )
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(model=GROQ_MODEL, messages=messages)
    return {"message": {"content": response.choices[0].message.content}}