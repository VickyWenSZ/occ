---
title: Performance Engineering and Profiling
slug: performance-and-profiling
source: python-programming-basics-long-fo
confidence: high
tags: [performance, profiling, optimization, cprofile, big-o]
---

# Performance Engineering and Profiling

## Executive overview
Performance engineering in Python starts with algorithmic complexity and data-structure choices, then proceeds to measurement, profiling, and targeted optimization. Modern Python 3 emphasizes:
- Big-O awareness to avoid pathological scaling.
- Evidence-driven optimization: time, profile, change one thing, measure again.
- Tooling: perf_counter, timeit, cProfile, pstats.
- Choosing appropriate concurrency models (async I/O, threads, processes) and optimized native libraries for hot loops.
- Memory-conscious patterns (streaming, generators, bounded caches, fewer objects, __slots__) and I/O batching.
- Startup-time discipline (avoid heavy imports; lazy-load where appropriate).

Python is productive but CPU-bound pure-Python loops are slow relative to native code; favor algorithmic fixes, vectorization, and library calls implemented in optimized C. CPython-specific constraints (reference counting, cyclic GC, and the traditional GIL) shape what scales with threads versus processes.

## Performance model and priorities
- Algorithm > data structure > avoid work > batch I/O > optimized libs > concurrency > native extensions.
- Define an objective (throughput/latency/memory/startup time), measure a baseline, locate bottlenecks, apply minimal change, remeasure, and keep only evidence-backed improvements.
- Maintain correctness: keep a test suite and regression checks active during optimization.

## Algorithmic complexity (Big-O)
- O(1): list indexing; average-case dict/set lookup.
- O(n): linear scans (e.g., membership in lists).
- O(n log n): sorting.
- O(n²): nested loops over same input; often fine for small n, disastrous for large n.
- Example trap:
  - List membership in large collections: use a set when order is irrelevant.
  - Build only the data you need; avoid quadratic accumulation.

## Timing and benchmarking
- Coarse timing:
  ```python
  from time import perf_counter
  start = perf_counter()
  # code under test
  elapsed = perf_counter() - start
  print(elapsed)
  ```
- Microbenchmarks:
  ```bash
  python -m timeit "sum(range(1000))"
  ```
- Guidance:
  - Warm up code paths when necessary (imports, caches).
  - Isolate system noise; use representative datasets.
  - Prefer macro/realistic benchmarks for end-to-end impact; use microbenchmarks to compare tight alternatives in isolation.

## Profiling (CPU time hotspots)
- Whole-program profiling:
  ```bash
  python -m cProfile script.py
  ```
- Save and inspect profile:
  ```bash
  python -m cProfile -o profile.out script.py
  ```
  ```python
  import pstats
  stats = pstats.Stats("profile.out")
  stats.sort_stats("cumulative").print_stats(20)
  ```
  - Sort by cumulative time to find high-level bottlenecks; internal (per-function) time highlights function bodies exclusive of callees.
- Workflow:
  - Profile typical workloads; avoid profiling-only code paths.
  - Optimize the top bottleneck; reprofile after each change.

## Common performance traps and fixes
- Repeated string concatenation in loops:
  ```python
  # slow
  s = ""
  for part in parts:
      s += part
  # better
  s = "".join(parts)
  ```
- List membership for large datasets:
  ```python
  # slow for large data
  if item in big_list: ...
  # better if order not needed
  big_set = set(big_list)
  if item in big_set: ...
  ```
- Loading whole large files:
  ```python
  # memory-heavy
  text = file.read()
  # better: streaming
  for line in file: process(line)
  ```
- Pure-Python numeric loops vs native/vectorized code: prefer optimized libraries (e.g., NumPy) for large numeric arrays and linear algebra.
- Micro-optimizations (binding attributes to locals) are rarely impactful compared to algorithm/data changes; only apply in proven hot loops.

## Memory engineering
- Typical sources of excess memory:
  - Retaining references longer than needed.
  - Large intermediate lists; favor generators/iterators for pipelines.
  - Unbounded caches.
  - Millions of small Python objects; consider using __slots__ or array-based representations where appropriate.
- Streaming patterns:
  ```python
  def non_empty_lines(path):
      with open(path, encoding="utf-8") as f:
          for line in f:
              s = line.strip()
              if s:
                  yield s
  ```
- Caching trade-offs: faster repeated access vs higher memory; bound caches to control growth.
  ```python
  from functools import lru_cache

  @lru_cache(maxsize=1024)
  def expensive_lookup(key):
      ...
  ```
- CPython memory facts affecting performance:
  - Reference counting plus cyclic GC; cycles need GC to reclaim.
  - Many tiny Python objects incur overhead; prefer contiguous/native buffers for large numeric data.

## I/O performance practices
- Batch operations to reduce syscall/network overhead.
- Reuse HTTP sessions; set timeouts; avoid unnecessary serialize/deserialize cycles.
- Stream big files and outputs; avoid readlines() on huge inputs.
- Separate network latency from CPU costs in measurements.

## Concurrency and parallelism for performance
- CPython GIL and choices:
  - I/O-bound: threads or async I/O can improve throughput (threads overlap waiting; async uses cooperative scheduling).
  - CPU-bound: use processes (multiprocessing/ProcessPoolExecutor) or native extensions; threads won’t speed CPU-bound Python bytecode in traditional GIL builds.
- Async pitfalls:
  - Do not block the event loop; replace time.sleep with await asyncio.sleep; offload blocking work via asyncio.to_thread for light blocking, or processes for CPU-bound work.
  - Use semaphores to bound concurrency; apply timeouts; handle cancellation.
- Process costs:
  - Serialization/pickling overhead, process startup time, higher memory footprint; batch workloads to amortize costs.

## Startup-time optimization
- Import-time work runs on module import; keep it minimal.
- Avoid heavy I/O, network calls, or large computations at import.
- Lazy-load optional heavy dependencies.
- Measure startup separately from steady-state.

## Optimization workflow (evidence-driven)
1. Define the performance goal (e.g., 95th percentile latency, QPS, memory cap, cold-start time).
2. Measure current behavior (timing and profiling).
3. Identify bottlenecks (cumulative CPU, blocking I/O, allocations).
4. Change one thing (algorithm, data structure, batching, caching, concurrency).
5. Remeasure under the same conditions.
6. Keep or revert based on evidence; protect with tests.

## CPython-specific considerations
- Bytecode VM with internal compilation to bytecode; optimize Python-level structure, not bytecode.
- Reference counting yields prompt reclamation for non-cyclic objects; watch for cycles and objects with finalizers.
- Traditional GIL limits parallel CPU-bound threads; processes sidestep this at IPC/memory cost.
- Alternative runtimes (e.g., PyPy) can speed long-running pure-Python workloads; extension/module compatibility varies.

## Example snippets and commands
- Fast membership:
  ```python
  s = set(items)
  if x in s: ...
  ```
- Join over concat:
  ```python
  result = "".join(chunks)
  ```
- Streaming file processing:
  ```python
  with open("data.txt", encoding="utf-8") as f:
      for line in f: process(line)
  ```
- Microbenchmark:
  ```bash
  python -m timeit -s "data=list(range(10000))" "sum(data)"
  ```
- CPU profile, inspect top functions:
  ```bash
  python -m cProfile -o prof.out app.py
  ```
  ```python
  import pstats
  pstats.Stats("prof.out").sort_stats("cumulative").print_stats(30)
  ```

## When to use libraries and native code
- Prefer library calls (often in C) over Python loops for:
  - Numeric operations, aggregations, linear algebra (vectorization).
  - Parsing and encoding where robust libraries exist.
- Consider moving only proven hot paths to native extensions; weigh build, portability, and maintenance costs.

## Key Points
- Start with algorithm/data-structure fixes; measure with perf_counter/timeit and profile with cProfile/pstats; optimize only bottlenecks.
- Replace quadratic patterns and Python loops over large numeric data with linear or vectorized operations; batch I/O and reuse sessions.
- Use sets/dicts for O(1) membership/lookups; join strings once; stream large files to control memory.
- Threads/async improve I/O-bound throughput; processes or native code are needed for CPU-bound parallelism under the traditional GIL.
- Control memory via streaming, bounded caches, fewer objects (__slots__), and by avoiding large intermediates; keep import-time work minimal to improve startup.