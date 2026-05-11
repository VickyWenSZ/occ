import re
import ollama

_SYSTEM = (
    "You are a query router. Reply with ONLY the digit 0 or 1, nothing else.\n\n"
    "0 = route to CHAT mode. Two cases:\n"
    "  (a) Social: greetings, thanks, jokes, meta-questions about the assistant.\n"
    "  (b) Tool request: the user explicitly asks to search the web, look up "
    "current/live information online, fetch a URL, write or read a file, "
    "run or execute code — in ANY language.\n\n"
    "1 = route to DELIBERATE mode: the user asks an informational question "
    "about any topic, person, place, event, concept, technology, science, "
    "history, or how-to. Answer benefits from deep knowledge retrieval.\n\n"
    "KEY DISTINCTION: asking about weather → 1. Asking to search the web "
    "for today's weather → 0. The word 'search', 'online', 'web', 'internet', "
    "'fetch', 'file', 'run code' — or their equivalents in ANY language — "
    "signals 0.\n\n"
    "DEFAULT TO 1 WHEN UNSURE."
)

_EXAMPLES = (
    "Examples (all languages):\n"
    '"hello" → 0\n'
    '"thanks" → 0\n'
    '"who are you" → 0\n'
    '"what can you do" → 0\n'
    '"search the web for the latest news on climate change" → 0\n'
    '"look up current stock prices online" → 0\n'
    '"fetch this url: https://example.com" → 0\n'
    '"write a file called report.txt with this content" → 0\n'
    '"run this python snippet" → 0\n'
    '"execute this code and show the output" → 0\n'
    '"what is the weather like in winter in Norway?" → 1\n'
    '"how does TCP/IP work?" → 1\n'
    '"who was Alexander the Great?" → 1\n'
    '"explain quantum entanglement" → 1\n'
    '"write me a sorting function in Python" → 1\n'
    '"what is the capital of Brazil?" → 1\n'
)


# Clearly-conversational openers that we always route to chat without an LLM call.
# Conservative: only the most unambiguous greetings/thanks/meta. Anything beyond
# this set is sent to the LLM classifier (which itself defaults to deliberate).
_CHAT_LITERALS = {
    # English
    "hi", "hello", "hey", "yo", "thanks", "thank you", "ty", "ok", "okay",
    "bye", "goodbye", "good morning", "good evening", "good night",
    # Italian
    "ciao", "salve", "grazie", "buongiorno", "buonasera", "buonanotte", "ok", "va bene",
    # French / Spanish / German basics
    "bonjour", "merci", "hola", "gracias", "hallo", "danke",
}


def _looks_like_pure_chitchat(q: str) -> bool:
    """Quick deterministic check for the most obvious chitchat — avoids spending
    an LLM call on greetings."""
    s = q.strip().lower().rstrip("!.?,;:")
    if not s:
        return True
    if s in _CHAT_LITERALS:
        return True
    # Very short greetings with punctuation/emoji
    if len(s) <= 3 and re.match(r"^[\w\s]+$", s):
        return True
    return False


def classify(model: str, query: str) -> str:
    """Returns 'chat' or 'deliberate'. Hybrid: literal chitchat → chat fast-path,
    everything else → LLM classifier biased toward deliberate."""
    if _looks_like_pure_chitchat(query):
        return "chat"
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
    # Bias toward deliberate: anything ambiguous (no clear "0" token) → deliberate.
    # Only an explicit "0" routes to chat.
    return "chat" if result.startswith("0") else "deliberate"
