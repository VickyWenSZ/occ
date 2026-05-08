"""
Thread-safe log bus: broker_agent writes here, GUI SSE endpoint streams from here.
"""
import asyncio
from collections import deque
from datetime import datetime

_MAX = 2000
_lines: deque = deque(maxlen=_MAX)
_listeners: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def write(msg: str):
    """Append a log line. Call from any thread."""
    ts = datetime.now().strftime("%H:%M:%S")
    msg = f"[{ts}] {msg}"
    _lines.append(msg)
    if _loop and not _loop.is_closed():
        for q in _listeners:
            _loop.call_soon_threadsafe(q.put_nowait, msg)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _listeners.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    try:
        _listeners.remove(q)
    except ValueError:
        pass


def history() -> list[str]:
    return list(_lines)
