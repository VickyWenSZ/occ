import ollama

_SYSTEM = (
    "You are a query router. Reply with ONLY the digit 0 or 1.\n\n"
    "Ask yourself one question: is the user making conversation (chitchat), "
    "or do they need specific documented knowledge retrieved from a knowledge base?\n\n"
    "0 = chitchat: greetings, opinions, philosophy, humor, emotions, personal questions, "
    "meta-questions about the assistant, anything where a conversational reply is enough.\n"
    "1 = knowledge retrieval: the user needs precise, detailed, factual information on a "
    "specific topic — regardless of domain. Something where consulting a knowledge base "
    "would produce a better answer than just replying from memory.\n\n"
    "Default to 0 when uncertain."
)

_EXAMPLES = (
    "Examples:\n"
    '"hello" → 0\n'
    '"what can you do" → 0\n'
    '"what day is it" → 0\n'
    '"how does docker work" → 1\n'
    '"what is mcp" → 1\n'
    '"write me a python function" → 1\n'
    '"explain kubernetes networking" → 1\n'
)


def classify(model: str, query: str) -> str:
    """Returns 'chat' or 'deliberate'. Fast binary classifier."""
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM + "\n\n" + _EXAMPLES},
            {"role": "user", "content": query},
        ],
        think=False,
        keep_alive=-1,
        options={"temperature": 0.0, "num_predict": 3},
        stream=False,
    )
    result = (response.message.content or "").strip()
    return "deliberate" if "1" in result else "chat"
