import re
import ollama

_SYSTEM = (
    "You are a query router. Reply with ONLY the digit 0 or 1, nothing else.\n\n"
    "1 = the user is asking about ANY specific topic, person, place, event, "
    "concept, technology, technique, science, history, art, or how-to — in ANY "
    "language. Anything where the answer benefits from real information rather "
    "than a casual reply.\n\n"
    "0 = pure social chitchat ONLY: greetings, thanks, jokes you initiate, or "
    "meta-questions directly about the assistant itself (its name, what it can "
    "do, who built it). Nothing else qualifies for 0.\n\n"
    "DEFAULT TO 1 WHEN UNSURE. Asking about a person, period, technology, or "
    "any factual question — even briefly, even controversially — is always 1."
)

_EXAMPLES = (
    "Examples (all languages):\n"
    '"hello" → 0\n'
    '"ciao" → 0\n'
    '"thanks" → 0\n'
    '"who are you" → 0\n'
    '"what can you do" → 0\n'
    '"what is mcp" → 1\n'
    '"how does docker work" → 1\n'
    '"explain kubernetes networking" → 1\n'
    '"Cesare era gay?" → 1\n'
    '"come containerizzo un mcp in docker?" → 1\n'
    '"chi era Napoleone" → 1\n'
    '"compare Roman emperors with Neanderthals" → 1\n'
    '"write me a python function" → 1\n'
    '"what day is it" → 1\n'
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
