---
title: asyncio and Asynchronous Programming
slug: asyncio-and-async-programming
source: python-programming-basics-long-fo
confidence: high
tags: [asyncio, asynchronous, concurrency, event loop, coroutines]
---

# asyncio and Asynchronous Programming

## Concept and scope
Asynchronous programming in modern Python (3.x) provides cooperative concurrency for I/O-bound workloads. The core language features are async def and await; the standard library framework is asyncio. Async enables many concurrent tasks to make progress while most are waiting on I/O (e.g., sockets, files, timers). It does not, by itself, speed up CPU-bound computation or provide parallel execution of Python bytecode.

Key terms:
- Coroutine: awaitable object returned by calling an async function; it runs only when awaited or scheduled.
- Event loop: scheduler that drives coroutines, callbacks, and I/O readiness.
- Task: a scheduled coroutine that runs concurrently with others on the same event loop.
- Await: suspend the current coroutine until an awaitable completes, yielding control back to the event loop.

## When to use async
Use async for:
- High-concurrency I/O (HTTP clients/servers, WebSockets, message brokers).
- Long-lived connections and event-driven systems.
- Async DB drivers and RPC where many calls wait on the network.

Do not use async to “speed up” CPU-bound work. CPU-heavy functions block the event loop; offload such work to threads, processes, or native extensions.

## Language primitives: async/await
- Defining a coroutine:
  ```python
  async def greet() -> str:
      return "hello"
  ```
  Calling greet() returns a coroutine object; it does not execute immediately.

- Running top-level async code:
  ```python
  import asyncio

  async def main() -> None:
      msg = await greet()
      print(msg)

  asyncio.run(main())
  ```
  Notes:
  - asyncio.run() creates, runs, and closes an event loop for the given top-level coroutine.
  - Do not call asyncio.run() from within a running event loop (e.g., inside other async functions).

- Await constraints:
  - await is valid only inside async functions (or supported async-aware shells/notebooks).
  - You must await or schedule every coroutine; otherwise, it never runs.

## Concurrency with asyncio
- Overlapping awaits:
  ```python
  import asyncio

  async def fetch(name: str, delay: float) -> str:
      await asyncio.sleep(delay)
      return name

  async def main():
      # Run both concurrently; completes in ~1s, not ~2s.
      results = await asyncio.gather(
          fetch("a", 1.0),
          fetch("b", 1.0),
      )
      print(results)

  asyncio.run(main())
  ```

- Tasks:
  ```python
  task = asyncio.create_task(fetch("x", 1.0))
  result = await task
  ```
  Creating a task schedules the coroutine immediately on the event loop.

- gather vs create_task:
  - asyncio.gather(awaitables...) waits for all and returns results in order. By default, if any awaitable fails, gather raises and (typically) cancels the rest.
  - asyncio.create_task(coro) gives you a Task that you can await, cancel, or supervise later.

## Avoid blocking the event loop
- Use asyncio.sleep() instead of time.sleep() in async code.
- Do not call blocking I/O (disk, network, CPU-heavy loops) directly from async functions.

Bridging to blocking code:
- Lightweight/blocking calls in a thread:
  ```python
  import asyncio

  def blocking() -> int:
      return sum(range(5_000_000))

  async def main():
      result = await asyncio.to_thread(blocking)
      print(result)

  asyncio.run(main())
  ```
- True CPU parallelism typically requires multiprocessing or native code; threads remain constrained by the traditional CPython GIL for Python bytecode.

## Cancellation and timeouts
Cancellation is a first-class concept:
- Cancelling a task:
  ```python
  import asyncio

  async def work():
      try:
          await asyncio.sleep(10)
      except asyncio.CancelledError:
          # Do cleanup if needed, then re-raise
          raise

  async def main():
      t = asyncio.create_task(work())
      await asyncio.sleep(0.1)
      t.cancel()
      try:
          await t
      except asyncio.CancelledError:
          print("cancelled")

  asyncio.run(main())
  ```

- Timeouts:
  ```python
  import asyncio

  async def main():
      try:
          await asyncio.wait_for(asyncio.sleep(10), timeout=1)
      except asyncio.TimeoutError:
          print("timed out")

  asyncio.run(main())
  ```
Guidance:
- Don’t swallow CancelledError unintentionally; re-raise after cleanup.
- Use timeouts to bound waits; tune defaults based on operational needs.

## Limiting concurrency and backpressure
- Semaphores to cap parallelism:
  ```python
  import asyncio
  sem = asyncio.Semaphore(10)

  async def limited_fetch(url: str):
      async with sem:
          return await fetch(url)
  ```
- Queues to decouple producers/consumers:
  ```python
  import asyncio

  async def producer(q: asyncio.Queue[str]):
      await q.put("item")

  async def consumer(q: asyncio.Queue[str]):
      item = await q.get()
      try:
          print(item)
      finally:
          q.task_done()
  ```

## Async context managers, iterators, and generators
- Async context manager:
  ```python
  class AsyncResource:
      async def __aenter__(self):
          print("open"); return self
      async def __aexit__(self, exc_type, exc, tb):
          print("close")

  async def main():
      async with AsyncResource():
          ...
  ```
- Async iterator:
  ```python
  class AsyncCounter:
      def __init__(self, limit: int):
          self.current = 0; self.limit = limit
      def __aiter__(self): return self
      async def __anext__(self):
          if self.current >= self.limit:
              raise StopAsyncIteration
          self.current += 1
          return self.current
  ```
- Async generator:
  ```python
  async def ticker(n: int):
      for i in range(n):
          await asyncio.sleep(1)
          yield i
  ```

## Structured concurrency with TaskGroup (3.11+)
Task groups scope child task lifetimes and error propagation:
```python
import asyncio

async def worker(name: str):
    await asyncio.sleep(1)
    return name

async def main():
    async with asyncio.TaskGroup() as tg:
        t1 = tg.create_task(worker("a"))
        t2 = tg.create_task(worker("b"))
    # On exit, all tasks are complete or cancelled on error.
    print(t1.result(), t2.result())

asyncio.run(main())
```
Benefits:
- Clear lifetime management for child tasks.
- Fail-fast behavior with structured cancellation and propagation.
- Prefer over ad hoc background tasks when targeting supported versions.

## Common pitfalls and misconceptions
- “Calling an async function runs it.” False: calling returns a coroutine; you must await or schedule it.
- “You can await anywhere.” False: await only inside async functions or supported interactive contexts.
- “Async makes code faster.” Not inherently; it increases throughput for I/O-bound concurrency, not CPU-bound speed.
- “Blocking calls are harmless in async.” False: time.sleep() and blocking I/O stall the event loop and all tasks.
- “Threads are obsolete if you have async.” False: threads remain practical for blocking I/O or legacy libraries; processes for CPU parallelism.

## Error handling patterns
- Wrap I/O with timeouts; add retries only for transient failures (use backoff, jitter).
- Keep cancellation cooperative: catch CancelledError to clean up, then re-raise.
- Aggregate multiple concurrent errors with gather or TaskGroup; understand exception behavior for your Python version.
- Log with context; avoid import-time side effects in async modules to preserve startup performance and testability.

## Version and ecosystem notes
- Python 3.10+: modern syntax (X | Y unions).
- Python 3.11: Exception groups, asyncio.TaskGroup, performance improvements, enhanced error diagnostics.
- Verify exact asyncio API behavior (timeouts, cancellation, gather semantics) against your target Python version’s official docs.
- For networking, always set timeouts; reuse sessions where applicable; validate data at boundaries.

## Minimal patterns
- Top-level runner:
  ```python
  import asyncio

  async def main() -> None:
      ...

  if __name__ == "__main__":
      asyncio.run(main())
  ```
- Parallel I/O with limits:
  ```python
  import asyncio

  sem = asyncio.Semaphore(20)

  async def fetch_one(url: str) -> bytes: ...
  async def fetch_all(urls: list[str]) -> list[bytes]:
      async def _wrapped(u: str):
          async with sem:
              return await fetch_one(u)
      return await asyncio.gather(*[ _wrapped(u) for u in urls ])
  ```

## Integration with other concurrency models
- Threads: Good for blocking I/O or libraries lacking async APIs; share memory; mind synchronization.
- Processes: Good for CPU parallelism; higher overhead; objects must be picklable.
- Subprocesses: Use asyncio’s async subprocess APIs if targeting async end-to-end; otherwise bound by blocking calls.

## Testing and operations (high-level)
- Test async code with event-loop-aware frameworks; isolate blocking collaborators (e.g., use to_thread or fakes).
- Instrument timeouts, cancellations, and retries; log at INFO/WARNING with identifiers for correlation.
- Fail fast on misconfiguration; prefer explicit timeouts everywhere external I/O occurs.

## Key Points
- asyncio provides cooperative concurrency for I/O-bound tasks; CPU-bound work must be offloaded to threads, processes, or native code.
- async def returns a coroutine; use await or schedule via asyncio.create_task; run top-level with asyncio.run.
- Avoid blocking the event loop; replace time.sleep with asyncio.sleep and use asyncio.to_thread for blocking calls.
- Use cancellation and timeouts deliberately; handle asyncio.CancelledError for cleanup and re-raise.
- Prefer structured concurrency (asyncio.TaskGroup, 3.11+) for predictable task lifetime and error propagation.