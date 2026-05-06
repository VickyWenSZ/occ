---
title: Concurrency and Parallelism (Threads, Processes, Async)
slug: concurrency-and-parallelism
source: python-programming-basics-long-fo
confidence: high
tags: [concurrency, threads, processes, asyncio, gil]
---

# Concurrency and Parallelism (Threads, Processes, Async)

## Overview and definitions
- Concurrency: multiple tasks whose lifetimes overlap (interleaving or overlapping I/O).
- Parallelism: tasks executing simultaneously, typically on multiple CPU cores.

Python supports multiple concurrency models:
- Threads: shared-address-space concurrency, good for I/O-bound workloads.
- Processes: separate interpreters and memory, good for CPU-bound parallelism.
- Async I/O (`asyncio`): cooperative concurrency for high I/O concurrency.
- Subprocesses: spawn external programs (separate from Python’s interpreter-level processes).

CPython’s Global Interpreter Lock (GIL) traditionally allows only one thread to execute Python bytecode at a time in a process. Consequences:
- I/O-bound threading can scale well; CPU-bound Python code typically cannot run in parallel via threads.
- True CPU parallelism in CPython commonly uses multiprocessing or native extensions that release the GIL.
- GIL behavior is CPython-specific and evolving; check target-version/build documentation.

Choose based on workload:
- I/O-bound high-concurrency: asyncio or threads.
- CPU-bound: processes (e.g., `ProcessPoolExecutor`), native extensions, or distributed systems.
- External tools: `subprocess` with secure argument passing.

## Threads
Threads overlap operations within a single process and share memory.

When to use
- I/O-bound tasks (network, disk), background blocking I/O in GUIs, integrating with blocking libraries lacking async APIs.

APIs
- High-level pool:
```python
from concurrent.futures import ThreadPoolExecutor

def fetch(url):
    ...

with ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(fetch, urls))
```
- Synchronization:
  - Use `threading.Lock()` to protect shared mutable state.
```python
import threading

counter = 0
lock = threading.Lock()

def increment():
    global counter
    with lock:
        counter += 1
```
- Communication:
  - Prefer queues to share data safely between threads.
```python
from queue import Queue
```

Constraints and pitfalls
- CPU-bound work is limited by the traditional GIL in CPython.
- Races and deadlocks if shared state is not synchronized.
- Prefer immutability and message passing (queues) to minimize locking.

## Processes (multiprocessing / process pools)
Processes run code in separate interpreters with separate memory; they can run in parallel on multiple cores and are not limited by the traditional GIL.

When to use
- CPU-bound workloads (numerical loops in pure Python), isolation for resilience.

APIs
- High-level pool:
```python
from concurrent.futures import ProcessPoolExecutor

def square(x):
    return x * x

with ProcessPoolExecutor() as executor:
    results = list(executor.map(square, range(10)))
```

Tradeoffs
- Overhead: process startup, inter-process communication (IPC), pickling/serialization costs, higher memory usage.
- Constraints: arguments and results generally must be picklable.
- Not a fit for low-latency micro-tasks due to overhead.

## Async I/O (`asyncio`)
Async uses cooperative scheduling of coroutines for massive I/O concurrency.

Core constructs
- Define coroutines with `async def`, await awaitables with `await`.
```python
import asyncio

async def greet():
    await asyncio.sleep(1)
    return "hello"

async def main():
    msg = await greet()
    print(msg)

asyncio.run(main())
```
- Concurrency with tasks:
```python
import asyncio

async def worker(name, delay):
    await asyncio.sleep(delay)
    return name

async def main():
    results = await asyncio.gather(
        worker("a", 1),
        worker("b", 1),
    )
    print(results)

asyncio.run(main())
```
- Do not call blocking functions in async code; they block the event loop. Use async equivalents or offload:
  - Sleep: `await asyncio.sleep(...)` instead of `time.sleep`.
  - Offload blocking or light CPU work to a thread: `await asyncio.to_thread(func, *args)`.
- Timeouts and cancellation:
```python
import asyncio

async def work():
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        print("cancelled")
        raise

async def main():
    task = asyncio.create_task(work())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("task cancellation observed")

asyncio.run(main())
```
- Timeout control:
```python
import asyncio

async def main():
    try:
        await asyncio.wait_for(asyncio.sleep(10), timeout=1)
    except asyncio.TimeoutError:
        print("timed out")

asyncio.run(main())
```
- Limiting concurrency:
```python
import asyncio

sem = asyncio.Semaphore(10)

async def limited_fetch(url):
    async with sem:
        return await fetch(url)
```
- Async queues:
```python
import asyncio

async def producer(q):
    await q.put("item")

async def consumer(q):
    item = await q.get()
    try:
        print(item)
    finally:
        q.task_done()
```
- Async context managers and iterators:
```python
class AsyncResource:
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): return False

class AsyncCounter:
    def __aiter__(self): return self
    async def __anext__(self): ...
```
- Structured concurrency (Python 3.11+): `asyncio.TaskGroup` scopes task lifetimes and error propagation.
```python
import asyncio

async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(worker("a"))
        tg.create_task(worker("b"))
```

Behavioral notes
- Calling an async function creates a coroutine; it runs only when awaited or scheduled.
- Do not call `asyncio.run()` inside an already-running event loop.
- Always await or supervise created tasks to surface errors promptly.
- `asyncio.gather` exception behavior and cancellation semantics can vary by parameters; verify target-version docs.

## Subprocesses (external commands)
Use `subprocess` to execute external programs (separate from Python multiprocessing).

- Safe invocation without shell:
```python
import subprocess

result = subprocess.run(
    ["python", "--version"],
    capture_output=True, text=True, check=True,
)
print(result.stdout)
```
- Security: avoid `shell=True` with untrusted input; prefer argument lists. Handle timeouts, exit codes, and errors explicitly.

## Error handling in concurrent code
- Always handle and propagate exceptions from worker threads/processes/tasks.
- Preserve context with exception chaining:
```python
try:
    value = int(text)
except ValueError as exc:
    raise ValueError(f"Invalid count: {text!r}") from exc
```
- Python 3.11+ supports exception groups and `except*` for handling multiple concurrent errors:
```python
try:
    raise ExceptionGroup("multiple failures", [ValueError("bad"), TypeError("bad")])
except* ValueError as group:
    print("value errors:", group)
```
- In async, do not swallow `asyncio.CancelledError`; cleanup and re-raise to honor cancellation.

## Choosing and combining models
- I/O-bound:
  - Many concurrent sockets/connections: asyncio or threads.
  - Simpler blocking libraries: threads (or wrap in `to_thread` within async).
- CPU-bound:
  - Use processes (`ProcessPoolExecutor`) for parallelism; avoid threads for pure-Python CPU hot paths under the traditional GIL.
  - Consider native extensions or optimized libraries for heavy numerics.
- Mixed workloads:
  - Async for orchestration + `to_thread` for occasional blocking calls.
  - Async for orchestration + process pool for CPU-heavy tasks.
- Resource control:
  - Use semaphores to cap concurrent operations.
  - Use queues to decouple producers/consumers.

## Testing and reliability
- Flakiness sources: timing assumptions, network, shared globals, concurrency races, order dependence.
- Add timeouts, deterministic seeds, and explicit synchronization.
- Separate unit vs integration tests; mock or isolate external services thoughtfully.
- Use logging to surface task lifecycle, cancellations, and exceptions.

## CPython-specific internals
- Traditional GIL: only one thread executes Python bytecode at a time per process; threads can still overlap I/O and C extensions may release the GIL during long C calls.
- Multiprocessing bypasses the traditional GIL for Python-level CPU parallelism (separate interpreters and memory).
- GIL behavior and free-threading work are evolving; consult version-specific docs for current status.

## Common misconceptions (and corrections)
- “Async makes code faster.” Async improves throughput for I/O-bound concurrency; it does not accelerate CPU computation by itself.
- “Calling an async function runs it.” It returns a coroutine; it must be awaited or scheduled.
- “Blocking calls are fine in async.” They block the event loop; use async equivalents or offload.
- “GIL prevents all concurrency.” It limits parallel CPU bytecode execution in threads; concurrency is still effective via I/O multiplexing, processes, native extensions, and distributed systems.

## Key Points
- Use threads for I/O-bound concurrency; protect shared state with locks or, better, use queues and immutability.
- Use processes for CPU-bound parallelism; account for pickling overhead, startup cost, and higher memory use.
- Use asyncio for high connection counts and event-driven I/O; never block the event loop, and handle cancellation/timeouts explicitly.
- The traditional CPython GIL constrains CPU-bound threading but not I/O overlap; true CPU parallelism generally requires processes or native code.
- Supervise tasks, propagate exceptions (including exception groups), and apply structured concurrency (`TaskGroup`) to make concurrent code safer and more maintainable.