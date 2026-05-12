from datetime import datetime
from .roles import ROLES

# When OpenRouter is active, retrieval budget jumps to ~600k chars (~170k tokens),
# well within Qwen3.5's 262k native context. Local tier values stay untouched.
_OR_RETRIEVAL_CHARS = 600_000


def _log(msg: str) -> None:
    """Write to the GUI log bus when available; no-op otherwise (e.g. tests).
    Lets the user see deliberation progress in the Logs panel."""
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass


def _tool_status(fn_name: str, fn_args: dict) -> str:
    if fn_name == "web_search":
        return f"Searching the web: {fn_args.get('query', '')}..."
    if fn_name == "fetch_url":
        return f"Fetching page: {fn_args.get('url', '')}..."
    if fn_name == "read_file":
        return f"Reading file: {fn_args.get('filename', '')}..."
    if fn_name == "write_file":
        return f"Writing file: {fn_args.get('filename', '')}..."
    if fn_name == "list_files":
        return "Listing workspace files..."
    if fn_name == "run_code":
        return "Running code..."
    if fn_name == "fetch_full_page":
        return f"Critic verifying source: {fn_args.get('file', '')}..."
    return f"Running {fn_name}..."


def _tool_label(fn_name: str) -> str:
    return {
        "web_search": "WEB",
        "fetch_url":  "URL",
        "read_file":  "FILE",
        "write_file": "FILE",
        "list_files": "FILE",
        "run_code":   "CODE",
        "fetch_full_page": "VERIFY",
    }.get(fn_name, fn_name.upper())


def _serialize_sources(retrieved_pages: dict | None) -> list:
    """
    Flatten the engine's `retrieved_pages` into a UI-ready list:
    [{pack, file, title, summary, snippet}, ...].
    Snippet is the first substantive paragraph after frontmatter and headers.
    Returns [] when no retrieval (local mode without server).
    """
    if not retrieved_pages:
        return []
    out = []
    for (pack, file), meta in retrieved_pages.items():
        body = meta.get("content", "") or ""
        # Strip frontmatter so the snippet starts on real content
        if body.startswith("---\n"):
            end = body.find("\n---\n", 4)
            if end != -1:
                body = body[end + 5:]
        # Skip empty lines, markdown headers, and the leading abstract blockquote
        # marker — find the first substantive line of prose.
        snippet = ""
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):  # heading
                continue
            if s.startswith(">"):  # blockquote (abstract) — keep, often the best summary line
                snippet = s.lstrip("> ").strip()
                break
            snippet = s
            break
        if len(snippet) > 200:
            snippet = snippet[:200].rstrip() + "..."
        out.append({
            "pack": pack,
            "file": file,
            "title": meta.get("title", "") or file,
            "summary": meta.get("summary", "") or "",
            "snippet": snippet,
        })
    return out


def _parse_frontmatter_brief(text: str) -> tuple[str, str]:
    """Extract (title, summary) from YAML frontmatter. Returns ('', '') on miss."""
    if not text or not text.startswith("---\n"):
        return ("", "")
    end = text.find("\n---\n", 4)
    if end == -1:
        return ("", "")
    title = ""
    summary = ""
    for line in text[4:end].split("\n"):
        s = line.strip()
        if s.startswith("title:"):
            title = s[6:].strip().strip('"').strip("'")
        elif s.startswith("summary:"):
            summary = s[8:].strip().strip('"').strip("'")
    return (title, summary)


_OCC_IDENTITY = (
    "You are OCC (Open Cognitive Commons), a helpful and friendly AI assistant. "
    "You run locally on the user's machine as part of a distributed network of AI agents. "
    "You are a general-purpose assistant: you can answer questions on any topic, help with code, "
    "writing, analysis, reasoning, and more. "
    "Beyond your general knowledge, you have access to curated expert knowledge packs and can "
    "collaborate with peer nodes on the network for deeper, specialized answers. "
    "Sometimes responses take a little longer because you are consulting peer nodes — this is normal. "
    "Do NOT proactively advertise your domains or capabilities. "
    "Only mention what domains or packs you have loaded if the user explicitly asks."
)


class DeliberationEngine:
    def __init__(
        self,
        model: str,
        expert_pack=None,
        num_ctx_answer: int = 8192,
        num_ctx_synth: int = 12288,
        retrieval_chars: int = 8000,
        domains: list[str] | None = None,
        workspace=None,
        openrouter_key: str = "",
        openrouter_model: str = "",
        local_mode: bool = False,
        vram_used_mb: int = 0,
    ):
        self.model = model
        self.or_key = openrouter_key
        self.or_model = openrouter_model
        self.expert_pack = expert_pack
        self._local_mode = local_mode
        self.vram_used_mb = vram_used_mb
        self.num_ctx_answer = num_ctx_answer
        self.num_ctx_synth = num_ctx_synth
        self._retrieval_chars_local = retrieval_chars

        today = datetime.now().strftime("%B %d, %Y")
        parts = [_OCC_IDENTITY, f"Today's date is {today}."]
        if domains:
            domains_str = ", ".join(domains)
            parts.append(
                f"You have expert knowledge packs loaded for: {domains_str}. "
                "Mention this only if the user explicitly asks about your capabilities or domains."
            )
        workspace_path = str(workspace) if workspace else "the workspace folder"
        parts.append(
            f"Workspace directory: {workspace_path}. "
            "Call any tool listed in your available tools when it helps answer the user. "
            "IMPORTANT: do NOT call web_search or fetch_url on your own initiative. "
            "Use them ONLY when the user explicitly asks to search the web, look "
            "something up online, or fetch a URL."
        )
        self._chat_system = " ".join(parts)
        self._history: list[dict] = []
        self._last_ctx_used: int = 0
        self._peak_ctx_used: int = 0
        self._ctx_limit: int = num_ctx_answer

    @property
    def retrieval_chars(self) -> int:
        return _OR_RETRIEVAL_CHARS if self.or_key else self._retrieval_chars_local

    def _update_ctx(self, prompt_tokens: int, completion_tokens: int):
        self._last_ctx_used = prompt_tokens + completion_tokens
        self._peak_ctx_used += prompt_tokens + completion_tokens

    def _measure_ctx(self, messages: list) -> int:
        total_chars = sum(len(m.get("content", "") or "") for m in messages)
        return int(total_chars / 3.5)

    def add_to_history(self, user_msg: str, assistant_msg: str):
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": assistant_msg})
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

    # ─── Public entry point ───────────────────────────────────────────────────

    def route_stream(self, query: str, mode: str = "deliberate", images: list | None = None):
        if mode == "chat":
            yield ("routing", "chat")
            yield from self._stream_with_tools(self._chat_system, query, temperature=0.7, images=images)
            return

        # Local mode: uses private packs, no server, no peers
        if self._local_mode:
            context = (
                self.expert_pack.retrieve(query, max_chars=self.retrieval_chars)
                if self.expert_pack else ""
            )
            yield ("routing", "local_private")
            yield from self._deliberate_multiagent(query, context, retrieved_pages=None)
            return

        yield ("status", "Retrieving knowledge...")
        context, retrieved_pages = self._retrieve_from_server(query)

        if context is None:
            yield ("routing", "local_fallback")
            yield ("status", "Server unavailable — answering from base model only...")
            yield from self._deliberate_multiagent(query, "", retrieved_pages=None)
            return

        best_peer = self._select_best_peer(mode)
        if best_peer:
            yield ("routing", "distributed")
            yield from self._deliberate_with_peer(query, context or "", best_peer)
        else:
            if mode == "network":
                yield ("status", "No peers available — running locally...")
            yield ("routing", "local")
            yield from self._deliberate_multiagent(query, context or "", retrieved_pages=retrieved_pages)

    # ─── Retrieval ────────────────────────────────────────────────────────────

    def _navigate_pack_tree(self, query: str) -> str | None:
        """Walk the broker knowledge tree level by level using the LLM to pick the best path.
        Returns a pack path like "history/prehistory" or None if no relevant pack found.
        """
        import httpx
        from node.provider import call as _provider_call
        from node.retrieval.pack_cache import SERVER_URL

        current_path = ""
        MAX_DEPTH = 6

        for depth in range(MAX_DEPTH):
            url = f"{SERVER_URL}/tree" if not current_path else f"{SERVER_URL}/tree/{current_path}"
            try:
                resp = httpx.get(url, timeout=5.0)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception:
                break

            if depth == 0:
                children = data if isinstance(data, list) else []
                has_pack = False
            else:
                children = data.get("children", [])
                has_pack = data.get("has_pack", False)

            if not children:
                return current_path if has_pack else None

            children_str = ", ".join(children)
            if current_path:
                stop_hint = " Or reply 'stop' to use this location." if has_pack else " Or reply 'none' if nothing is relevant."
                prompt = (
                    f"You are navigating a knowledge tree to answer: \"{query}\"\n"
                    f"Current location: {current_path}\n"
                    f"Sub-topics: {children_str}\n"
                    + ("This location has a knowledge pack.\n" if has_pack else "")
                    + f"Which sub-topic is most relevant? Reply with exactly one name from the list.{stop_hint}"
                )
            else:
                prompt = (
                    f"You are navigating a knowledge tree to answer: \"{query}\"\n"
                    f"Top-level topics: {children_str}\n"
                    "Which topic is most relevant? Reply with exactly one topic name, or 'none' if nothing is relevant."
                )

            try:
                llm_resp = _provider_call(
                    messages=[{"role": "user", "content": prompt}],
                    model_local=self.model,
                    or_key="",
                    or_model="",
                    tools=None,
                    temperature=0.0,
                    num_ctx=2048,
                )
                choice = (llm_resp.content or "").strip().rstrip(".").lower()
            except Exception:
                break

            if choice in ("none", "stop", ""):
                return current_path if has_pack else None

            matched = next((c for c in children if c.lower() == choice), None)
            if not matched:
                matched = next((c for c in children if choice in c.lower() or c.lower() in choice), None)
            if not matched:
                return current_path if has_pack else None

            current_path = f"{current_path}/{matched}" if current_path else matched

        # Reached max depth — verify and return
        if current_path:
            try:
                resp = httpx.get(f"{SERVER_URL}/tree/{current_path}", timeout=5.0)
                if resp.status_code == 200 and resp.json().get("has_pack", False):
                    return current_path
            except Exception:
                pass
        return None

    def _llm_select_pages(self, query: str, indices: dict[str, str]) -> list[dict]:
        from node.provider import call as _provider_call

        index_text = ""
        for pack_name, content in indices.items():
            index_text += f"\n### Pack: {pack_name}\n{content}\n"

        prompt = (
            f"Question: {query}\n\n"
            f"Knowledge base index:\n{index_text}\n"
            "List the files to read to answer this question. "
            "Format: pack_name/filename — one per line, max 6 files. "
            "Use exact filenames from the index above."
        )
        try:
            resp = _provider_call(
                messages=[{"role": "user", "content": prompt}],
                model_local=self.model,
                or_key="",
                or_model="",
                tools=None,
                temperature=0.0,
                num_ctx=8192,
            )
            raw = resp.content or ""

            valid_files: dict[str, set[str]] = {}
            for pack_name, content in indices.items():
                valid_files[pack_name] = set()
                for line in content.splitlines():
                    line = line.strip()
                    if not line.startswith("|"):
                        continue
                    parts = [p.strip() for p in line.strip("|").split("|")]
                    if parts and parts[0] and not parts[0].startswith("-") and parts[0].lower() != "file":
                        valid_files[pack_name].add(parts[0])

            refs = []
            for line in raw.splitlines():
                line = line.strip().lstrip("- ").strip()
                if not line:
                    continue
                # Match by pack name prefix (handles nested paths like "history/prehistory/file.md")
                matched_pack = None
                matched_file = None
                for pack_name in valid_files:
                    prefix = pack_name + "/"
                    if line.startswith(prefix):
                        candidate = line[len(prefix):]
                        if candidate in valid_files[pack_name]:
                            matched_pack = pack_name
                            matched_file = candidate
                            break
                if matched_pack:
                    refs.append({"pack": matched_pack, "file": matched_file})
            return refs[:6]
        except Exception:
            return []

    def _retrieve_from_server(self, query: str) -> tuple:
        """
        Multi-domain retrieval via broker /search, with optional per-domain scoping.

        Flow:
          1. _decompose_query yields a 3-state decision:
               None       → legacy fallback (global BM25, no decomposition/translation)
               []         → no domain relevant; skip retrieval, return ("", {})
               [d1, ...]  → scoped flow: per-domain depth refinement + translation + scoped search
          2. For each chosen domain, walk the sub-tree via LLM
             (_navigate_within_scope) to pick the right depth — overview vs leaf —
             then translate the query into the pack's language and call /search
             with the refined scope. Falls back to the root domain scope if
             the deeper scope returns 0 results.
          3. Round-robin pick across groups (same logic as before; "group" replaces
             "sub_query" but the picking algorithm is identical).
          4. Multi-pack parallel fetch of the chosen pages.
          5. See Also expansion within each pack (capped per pack).
          6. Assemble context with PER-DOMAIN budget (retrieval_chars / N_active_domains),
             preserving round-robin emission order. Domain = pack_path top-level segment.
          7. Build retrieved_pages for the Critic's manifest+fetch tool.

        Returns `(context, retrieved_pages)`:
          - context: str | None | ""
          - retrieved_pages: dict | None | {}
        Status semantics for context:
          - non-empty string → success
          - "" → broker reachable but no relevant pages OR no-retrieval decision
          - None → broker unreachable
        """
        import asyncio
        import concurrent.futures
        import httpx as _httpx
        from node.retrieval.pack_cache import (
            fetch_pages, ensure_pack_cached, CACHE_DIR, SERVER_URL,
        )

        def _run_async(coro):
            try:
                return asyncio.run(coro)
            except RuntimeError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, coro).result(timeout=30)

        def _broker_reachable() -> bool:
            try:
                _httpx.get(f"{SERVER_URL}/tree", timeout=5).raise_for_status()
                return True
            except Exception:
                return False

        # 1. Discriminate the three states of _decompose_query
        _log(f"[retrieve] decompose: query={query[:80]!r}")
        decision = self._decompose_query(query)
        _log(f"[retrieve] decompose result: {decision!r}")

        if decision == []:
            # Qwen said "no domain relevant" → no retrieval (Expert from base model)
            return ("", {}) if _broker_reachable() else (None, None)

        results_per_group: list[list[dict]] = []
        if decision is None:
            # Legacy fallback: single global BM25 search, no decomposition/translation.
            # Acts as a safety net when /tree is down or the decomposer crashed.
            legacy = self._server_search(query, k=12)
            legacy.sort(key=lambda r: r.get("score", 0))
            if legacy:
                results_per_group.append(legacy)
        else:
            # Scoped flow: per-domain tree-walk to the right depth, then
            # translate + scoped /search at that depth.
            for domain in decision:
                # Depth refinement: navigate inside the domain's sub-tree.
                # Returns `domain` at worst, never None — safe to use as scope.
                scope_path = self._navigate_within_scope(domain, query)
                _log(f"[retrieve] domain={domain} scope={scope_path}")
                sample = self._fetch_index_sample(scope_path)
                if not sample:
                    _log(f"[retrieve] no index sample for {scope_path} — skip")
                    continue
                translated_q = self._translate_query_for_pack(query, sample)
                _log(f"[retrieve] keywords for {scope_path}: {translated_q!r}")
                d_results = self._server_search(translated_q, k=8, scope=scope_path)
                # Safety net: if a deep scope returns nothing (tree-walk picked
                # a wrong subtree, or content lives at the broader level),
                # retry with the root domain so we never miss material that
                # BM25 would have found at the wider scope.
                if not d_results and scope_path != domain:
                    _log(f"[retrieve] empty at {scope_path}, retry at {domain}")
                    d_results = self._server_search(translated_q, k=8, scope=domain)
                d_results.sort(key=lambda r: r.get("score", 0))
                _log(f"[retrieve] {len(d_results)} hits for {domain}; top: "
                     f"{(d_results[0].get('page_file', '') if d_results else '-')}")
                if d_results:
                    results_per_group.append(d_results)

        if not results_per_group:
            return ("", {}) if _broker_reachable() else (None, None)

        # 2. Build (pack, file) → {title, summary} from search results.
        # See Also pages fall back to frontmatter parsing later.
        page_meta: dict[tuple[str, str], dict] = {}
        for g_results in results_per_group:
            for r in g_results:
                k = (r.get("pack_path", ""), r.get("page_file", ""))
                if k[0] and k[1] and k not in page_meta:
                    page_meta[k] = {
                        "title": r.get("title", ""),
                        "summary": r.get("summary", ""),
                    }

        # 3. Round-robin across groups: each contributes its top-PER_GROUP before
        # any group gets a second pick. Dedup on (pack, file). Track the order so
        # context assembly stays fair across groups.
        PER_GROUP = 4
        MAX_PAGES_TOTAL = 12
        seen: set[tuple[str, str]] = set()
        refs_by_pack: dict[str, list[str]] = {}
        ordered_refs: list[tuple[str, str]] = []
        for round_idx in range(PER_GROUP):
            for g_results in results_per_group:
                if len(seen) >= MAX_PAGES_TOTAL:
                    break
                if round_idx >= len(g_results):
                    continue
                r = g_results[round_idx]
                pack_path = r.get("pack_path", "")
                page_file = r.get("page_file", "")
                if not pack_path or not page_file:
                    continue
                key = (pack_path, page_file)
                if key in seen:
                    continue
                seen.add(key)
                refs_by_pack.setdefault(pack_path, []).append(page_file)
                ordered_refs.append(key)
            if len(seen) >= MAX_PAGES_TOTAL:
                break

        if not refs_by_pack:
            return ("", {})

        # 4. Fetch initial pages, grouped by pack so we can expand per-pack
        pages_by_pack: dict[str, dict[str, str]] = {}
        for pack_path, files in refs_by_pack.items():
            refs = [{"pack": pack_path, "file": f} for f in files]
            try:
                fetched = _run_async(fetch_pages(refs))
                if fetched:
                    pages_by_pack[pack_path] = fetched
            except Exception:
                continue

        if not pages_by_pack:
            return (None, None)

        # 5. See Also expansion per pack — wikilinks are already pack-internal
        # (see _expand_via_see_also: targets must exist in the pack's index),
        # so the expansion is naturally scoped. Lower cap than the old global
        # mode to leave room for other domains' content.
        for pack_path in list(pages_by_pack.keys()):
            if not ensure_pack_cached(pack_path):
                continue
            index_path = CACHE_DIR / pack_path / "wiki" / "index.md"
            if not index_path.exists():
                continue
            try:
                index_content = index_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            already = set(pages_by_pack[pack_path].keys())
            extra_refs = self._expand_via_see_also(
                pages_by_pack[pack_path], pack_path, index_content,
                already_fetched=already, cap=3,
            )
            if not extra_refs:
                continue
            try:
                extra = _run_async(fetch_pages(extra_refs))
                if extra:
                    pages_by_pack[pack_path].update(extra)
            except Exception:
                pass

        # 6. Assemble context with per-domain budget so a single big pack does
        # not starve another domain's content. Domain = top-level pack_path segment
        # for both modes (scoped flow: equals the chosen domain; legacy fallback:
        # derived from each result's pack_path, giving multi-area fairness too).
        active_domains: set[str] = {pp.split("/", 1)[0] for pp in pages_by_pack}
        budget_per_domain = self.retrieval_chars // max(len(active_domains), 1)
        domain_spend: dict[str, int] = {d: 0 for d in active_domains}

        parts: list[str] = []
        emitted: set[tuple[str, str]] = set()
        # Pass 1: original round-robin picks
        for (pack_path, filename) in ordered_refs:
            content = pages_by_pack.get(pack_path, {}).get(filename)
            if content is None:
                continue
            domain = pack_path.split("/", 1)[0]
            remaining = budget_per_domain - domain_spend.get(domain, 0)
            if remaining <= 0:
                continue
            chunk = content[:remaining]
            parts.append(f"[{pack_path}/{filename}]\n{chunk}")
            domain_spend[domain] = domain_spend.get(domain, 0) + len(chunk)
            emitted.add((pack_path, filename))
        # Pass 2: See Also expansions appended at the tail of their pack's slot
        for pack_path, pages in pages_by_pack.items():
            domain = pack_path.split("/", 1)[0]
            for filename, content in pages.items():
                if (pack_path, filename) in emitted:
                    continue
                remaining = budget_per_domain - domain_spend.get(domain, 0)
                if remaining <= 0:
                    break
                chunk = content[:remaining]
                parts.append(f"[{pack_path}/{filename}]\n{chunk}")
                domain_spend[domain] = domain_spend.get(domain, 0) + len(chunk)

        # 7. Build retrieved_pages — flat (pack, file) → {title, summary, content}.
        # See Also pages weren't in the search results, so pull title/summary from
        # their frontmatter as fallback.
        retrieved_pages: dict[tuple[str, str], dict] = {}
        for pack_path, pages in pages_by_pack.items():
            for filename, content in pages.items():
                meta = page_meta.get((pack_path, filename), {})
                title = meta.get("title", "")
                summary = meta.get("summary", "")
                if not title or not summary:
                    fm_title, fm_summary = _parse_frontmatter_brief(content)
                    title = title or fm_title
                    summary = summary or fm_summary
                retrieved_pages[(pack_path, filename)] = {
                    "title": title,
                    "summary": summary,
                    "content": content,
                }

        return ("\n\n".join(parts), retrieved_pages)

    def _decompose_query(self, query: str) -> list[str] | None:
        """
        Identify which knowledge domains are needed to answer the question, constrained
        to the broker's real root list. Three-state contract:
          None       → /tree fetch or LLM call failed; caller falls back to global BM25
          []         → Qwen judged no domain relevant (chitchat / meta); caller skips retrieval
          [d1, ...]  → 1-4 valid root names (lowercase matched to broker's actual list)
        """
        import re as _re
        import httpx
        from node.provider import call as _provider_call
        from node.retrieval.pack_cache import SERVER_URL

        # 1. Fetch the real root list — constrained choice beats open-ended generation
        try:
            resp = httpx.get(f"{SERVER_URL}/tree", timeout=5.0)
            if resp.status_code != 200:
                return None
            root_list = resp.json()
            if not isinstance(root_list, list) or not root_list:
                return None
        except Exception:
            return None

        lower_to_orig = {str(r).lower(): str(r) for r in root_list if isinstance(r, str)}
        if not lower_to_orig:
            return None

        # 2. Constrained LLM choice
        system = (
            "You identify which knowledge domains are needed to answer a question. "
            "Reply only with names from the provided list, one per line. "
            "Reply 'none' if nothing is relevant. Maximum 4 domains."
        )
        user = (
            f"Question: {query}\n"
            f"Available domains: {', '.join(root_list)}\n"
            "Which domains are needed?"
        )
        try:
            resp = _provider_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model_local=self.model,
                or_key="",
                or_model="",
                tools=None,
                temperature=0.0,
                num_ctx=2048,
            )
            raw = (resp.content or "").strip()
        except Exception:
            return None

        # 3. Tokenize the response and keep only tokens that match a real root.
        # Tolerant to bullets, numbering, commas, and explanatory prose — relies
        # on the membership check against `lower_to_orig` to reject hallucinations.
        out: list[str] = []
        seen: set[str] = set()
        for token in _re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-_]*", raw):
            t = token.lower()
            if t == "none":
                continue
            if t in lower_to_orig and t not in seen:
                seen.add(t)
                out.append(lower_to_orig[t])
                if len(out) >= 4:
                    break
        return out

    def _fetch_index_sample(self, domain: str) -> str:
        """
        Fetch a text sample for `domain` to feed language detection.
        Walks the broker tree up to 2 levels deep looking for a pack's index.md;
        falls back to a list of children names when no index is reachable.
        Returns "" when the domain itself is absent from the tree (silent skip).
        """
        import httpx
        from node.retrieval.pack_cache import SERVER_URL

        def _try_index(path: str) -> str:
            try:
                r = httpx.get(f"{SERVER_URL}/packs/{path}/wiki/index.md", timeout=5.0)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
            return ""

        def _tree(path: str) -> dict | None:
            try:
                r = httpx.get(f"{SERVER_URL}/tree/{path}", timeout=5.0)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
            return None

        text = _try_index(domain)
        if text:
            return text

        tree = _tree(domain)
        if tree is None:
            return ""
        children = tree.get("children", []) or []

        for child in children:
            text = _try_index(f"{domain}/{child}")
            if text:
                return text

        for child in children:
            sub_tree = _tree(f"{domain}/{child}")
            if not sub_tree:
                continue
            for grandchild in sub_tree.get("children", []) or []:
                text = _try_index(f"{domain}/{child}/{grandchild}")
                if text:
                    return text

        return " ".join(children) if children else ""

    def _navigate_within_scope(self, domain: str, query: str) -> str:
        """
        Refine a root domain to the right depth via LLM tree-walk. Returns a
        path like "history/ancient-civilizations/ancient-rome" or just `domain`
        if Qwen stops at the overview level. Never returns None — falls back
        to the input `domain` on any failure, so the caller can rely on a
        usable scope value unconditionally.
        """
        import httpx
        from node.provider import call as _provider_call
        from node.retrieval.pack_cache import SERVER_URL

        MAX_DEPTH = 4
        current_path = domain

        for _ in range(MAX_DEPTH):
            try:
                resp = httpx.get(f"{SERVER_URL}/tree/{current_path}", timeout=5.0)
                if resp.status_code != 200:
                    return current_path
                data = resp.json()
            except Exception:
                return current_path

            children = data.get("children", []) or []
            has_pack = data.get("has_pack", False)

            if not children:
                return current_path

            # When the current level has its own overview pack, Qwen may stop
            # there. When not, it must descend (or admit no sub-topic fits).
            stop_hint = (
                " Or reply 'stop' to use this overview level."
                if has_pack
                else " Or reply 'none' if no sub-topic is relevant."
            )
            prompt = (
                f"You are navigating a knowledge tree to find the right level "
                f"for this question: \"{query}\"\n"
                f"Current location: {current_path}\n"
                + ("This location has its own overview pack.\n" if has_pack else "")
                + f"Sub-topics available: {', '.join(children)}\n"
                f"Which sub-topic is most relevant? Reply with exactly one name "
                f"from the list.{stop_hint}"
            )

            try:
                llm_resp = _provider_call(
                    messages=[{"role": "user", "content": prompt}],
                    model_local=self.model,
                    or_key="",
                    or_model="",
                    tools=None,
                    temperature=0.0,
                    num_ctx=2048,
                )
                choice = (llm_resp.content or "").strip().rstrip(".").lower()
            except Exception:
                return current_path

            if choice in ("none", "stop", ""):
                return current_path

            matched = next((c for c in children if c.lower() == choice), None)
            if not matched:
                matched = next(
                    (c for c in children if choice in c.lower() or c.lower() in choice),
                    None,
                )
            if not matched:
                return current_path

            current_path = f"{current_path}/{matched}"

        return current_path

    def _translate_query_for_pack(self, query: str, index_content: str) -> str:
        """
        Produce an FTS5-friendly keyword query in the pack's language. The LLM
        sees a sample of the pack's index, detects the language, and returns a
        short bag of 5-10 domain keywords (translations, synonyms, proper
        names) that cover the question's intent. BM25 then matches even when
        the user's phrasing doesn't share tokens with the page summaries — e.g.
        "morto" → "assassination Ides March killed Brutus Cassius senate".
        Falls back to the original query on any failure.
        """
        from node.provider import call as _provider_call

        if not index_content:
            return query

        system = (
            "You build a keyword query for a BM25 full-text search. "
            "Detect the language of the knowledge base from the index sample, "
            "then output 5-10 keywords in THAT language that best cover the user's "
            "question. Include synonyms, domain-specific terms, and proper names "
            "that are likely to appear in page titles or summaries. "
            "Reply with the keywords only, space-separated. No punctuation, no "
            "explanations, no quotes, no operators."
        )
        user = (
            f"Index sample (first 800 chars):\n{index_content[:800]}\n\n"
            f"User question: {query}\n"
            "Keywords:"
        )
        try:
            resp = _provider_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model_local=self.model,
                or_key="",
                or_model="",
                tools=None,
                temperature=0.0,
                num_ctx=1024,
            )
            out = (resp.content or "").strip()
            # Strip surrounding quotes/braces the model sometimes adds; collapse
            # to whitespace-separated tokens. Reject obviously pathological output.
            out = out.strip('"').strip("'").strip("`")
            if not out or len(out) > len(query) * 8 + 200:
                return query
            return out
        except Exception:
            return query

    def _server_search(self, q: str, k: int = 8, scope: str = "") -> list[dict]:
        """Call broker /search and return top-K results. Empty list on any failure."""
        import httpx
        from node.retrieval.pack_cache import SERVER_URL
        try:
            payload: dict = {"q": q, "k": k}
            if scope:
                payload["scope"] = scope
            resp = httpx.post(
                f"{SERVER_URL}/search",
                json=payload,
                timeout=8.0,
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("results", []) or []
        except Exception:
            return []

    def _expand_via_see_also(
        self,
        fetched_pages: dict[str, str],
        pack_path: str,
        index_content: str,
        already_fetched: set[str],
        cap: int = 6,
    ) -> list[dict]:
        """
        Parse [[slug|...]] wikilinks from already-fetched pages and return new
        page refs to fetch. Restricted to pages that exist in the pack index;
        deduplicated; capped at `cap` items.
        """
        import re

        # Build set of valid files from the index (first column, e.g. "concepts/x.md")
        valid_files: set[str] = set()
        for line in index_content.splitlines():
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if parts and parts[0] and not parts[0].startswith("-") and parts[0].lower() != "file":
                valid_files.add(parts[0])

        wikilink_re = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
        candidates: list[str] = []
        seen: set[str] = set(already_fetched)
        for content in fetched_pages.values():
            for slug in wikilink_re.findall(content):
                slug = slug.strip()
                if not slug:
                    continue
                file_path = f"concepts/{slug}.md"
                if file_path in valid_files and file_path not in seen:
                    seen.add(file_path)
                    candidates.append(file_path)
                    if len(candidates) >= cap:
                        break
            if len(candidates) >= cap:
                break
        return [{"pack": pack_path, "file": f} for f in candidates]

    # ─── Peer routing ─────────────────────────────────────────────────────────

    def _select_best_peer(self, mode: str):
        from node.server.client import fetch_peer_list
        peers = fetch_peer_list()
        if not peers:
            return None
        if mode == "network":
            return max(peers, key=lambda p: p.vram_used_mb)
        candidates = [p for p in peers if p.vram_used_mb > self.vram_used_mb]
        return max(candidates, key=lambda p: p.vram_used_mb) if candidates else None

    def _deliberate_with_peer(self, query: str, context: str, peer):
        """Expert (local) → Critic (remote peer, E2E encrypted) → Synthesis (local, streaming)."""
        from node.server.client import call_peer_critic
        from node.crypto import load_or_generate_keypair
        from node.provider import call as _provider_call, stream as _provider_stream

        _priv, _pub = load_or_generate_keypair()

        # Call 1 — Expert (local)
        yield ("status", "Expert analyzing...")
        if context:
            expert_prompt = (
                f"[Knowledge context]\n{context}\n\n"
                f"Question: {query}\n\n"
                "Answer using the knowledge above."
            )
        else:
            expert_prompt = f"Question: {query}\n\nAnswer helpfully."
        expert_resp = _provider_call(
            messages=[
                {"role": "system", "content": ROLES["expert"]["system"]},
                {"role": "user", "content": expert_prompt},
            ],
            model_local=self.model,
            or_key=self.or_key,
            or_model=self.or_model,
            tools=None,
            temperature=ROLES["expert"]["temperature"],
            num_ctx=self.num_ctx_answer,
        )
        expert_answer = expert_resp.content or ""

        # Call 2 — Critic (remote peer)
        yield ("status", f"Peer critic ({peer.tier_name})...")
        critique = call_peer_critic(context, expert_answer, peer, _priv)

        if critique is None:
            yield ("status", "Peer unavailable — Critic running locally...")
            if context:
                critic_prompt = (
                    f"[Knowledge context]\n{context}\n\n"
                    f"[Proposed answer]\n{expert_answer}\n\n"
                    "Review this answer critically."
                )
            else:
                critic_prompt = (
                    f"[Proposed answer]\n{expert_answer}\n\n"
                    "Review this answer critically."
                )
            try:
                critic_resp = _provider_call(
                    messages=[
                        {"role": "system", "content": ROLES["critic"]["system"]},
                        {"role": "user", "content": critic_prompt},
                    ],
                    model_local=self.model,
                    or_key=self.or_key,
                    or_model=self.or_model,
                    tools=None,
                    temperature=ROLES["critic"]["temperature"],
                    num_ctx=self.num_ctx_answer,
                )
                critique = critic_resp.content or ""
            except Exception:
                critique = ""

        yield ("peer_answers", {
            "mode": "network",
            "expert_draft": expert_answer,
            "critic_review": critique,
            "peer_tier": peer.tier_name,
        })

        # Call 3 — Synthesis (local, streaming)
        yield ("status", "Synthesizing...")
        synth_prompt = (
            f"Original question: {query}\n\n"
            f"Initial answer:\n{expert_answer}\n\n"
            f"Critical review:\n{critique}\n\n"
            "Write the best possible final answer. "
            "If the critical review identified gaps, errors, or missing points, incorporate them. "
            "Cover the topic fully, with the depth and detail the question deserves."
        )
        for token in _provider_stream(
            messages=[
                {"role": "system", "content": ROLES["synthesizer"]["system"]},
                {"role": "user", "content": synth_prompt},
            ],
            model_local=self.model,
            or_key=self.or_key,
            or_model=self.or_model,
            temperature=ROLES["synthesizer"]["temperature"],
            num_ctx=self.num_ctx_synth,
        ):
            yield ("token", token)

    # ─── Local multiagent ─────────────────────────────────────────────────────

    def _deliberate_multiagent(self, query: str, context: str, retrieved_pages: dict | None = None):
        """3-call sequential deliberation: Expert → Critic → Synthesis (streaming).

        `retrieved_pages` (optional): { (pack, file): {title, summary, content} }.
        When provided, the Critic gets a manifest of all retrieved pages and a
        `fetch_full_page` tool to verify specific claims against the full source
        text. Without it (local-only mode), the Critic falls back to the
        excerpt-only behavior.
        """
        from node.provider import call as _provider_call, stream as _provider_stream

        # Call 1 — Expert
        yield ("status", "Expert analyzing...")
        backend = "OR" if self.or_key else "ollama"
        _log(f"[expert] start ({backend}, ctx_chars={len(context)})")
        if context:
            expert_prompt = (
                f"[Knowledge context]\n{context}\n\n"
                f"Question: {query}\n\n"
                "Answer using the knowledge above."
            )
        else:
            expert_prompt = f"Question: {query}\n\nAnswer helpfully."
        try:
            expert_resp = _provider_call(
                messages=[
                    {"role": "system", "content": ROLES["expert"]["system"]},
                    {"role": "user", "content": expert_prompt},
                ],
                model_local=self.model,
                or_key=self.or_key,
                or_model=self.or_model,
                tools=None,
                temperature=ROLES["expert"]["temperature"],
                num_ctx=self.num_ctx_answer,
            )
            expert_answer = expert_resp.content or ""
            _log(f"[expert] done — {len(expert_answer)} chars")
        except Exception as e:
            expert_answer = ""
            _log(f"[expert] FAILED: {e}")
            yield ("peer_answers", {"mode": "local", "expert_draft": "", "critic_review": f"[Expert call failed: {e}]"})
            yield ("token", f"*(Deliberation failed at Expert step: {e})*")
            return

        # Call 2 — Critic (manifest + excerpt + optional fetch_full_page tool)
        yield ("status", "Critic reviewing...")
        # Caps scale with the tier's retrieval budget AND its model context window.
        # Excerpt: 40% of retrieval material, bounded by 30% of the answer-tier
        # num_ctx (chars assuming ~4 chars/token). Expert-draft cap: same shape,
        # 50% of retrieval to ensure the Critic verifies the WHOLE draft.
        _ctx_cap = min(
            int(self.retrieval_chars * 0.40),
            int(self.num_ctx_answer * 4 * 0.30),
        )
        critic_excerpt = context[:_ctx_cap] if context else ""
        _expert_cap = min(
            int(self.retrieval_chars * 0.50),
            int(self.num_ctx_answer * 4 * 0.30),
        )
        critic_expert = expert_answer[:_expert_cap]

        # Run the Critic with manifest+fetch tool when retrieved_pages is available;
        # otherwise fall back to the legacy excerpt-only flow.
        _log(f"[critic] start ({backend}, draft={len(critic_expert)} chars)")
        critique = ""
        try:
            for ev in self._run_critic(critic_excerpt, critic_expert, retrieved_pages):
                if ev[0] == "status":
                    yield ev
                elif ev[0] == "tool_used":
                    yield ev
                elif ev[0] == "critique":
                    critique = ev[1]
        except Exception as e:
            _log(f"[critic] FAILED: {e}")
            critique = ""
        _log(f"[critic] done — {len(critique)} chars")

        # Always emit peer_answers so Sources panel always appears in deliberate mode
        yield ("peer_answers", {
            "mode": "local",
            "expert_draft": expert_answer,
            "critic_review": critique,
            "sources": _serialize_sources(retrieved_pages),
        })

        # Call 3 — Synthesis (streaming) — caps scale with the tier's retrieval budget.
        # Expert can't write meaningfully beyond what it read, and the Critic
        # review is naturally a fraction of that. retrieval_chars is the right
        # anchor: it grows from 8k (micro/small) to 65k (server-l).
        yield ("status", "Synthesizing...")
        _synth_expert_cap = int(self.retrieval_chars * 0.70)
        _synth_critique_cap = int(self.retrieval_chars * 0.25)
        synth_prompt = (
            f"Original question: {query}\n\n"
            f"Initial answer (Expert draft):\n{expert_answer[:_synth_expert_cap]}\n\n"
            f"Critical review (Critic):\n{critique[:_synth_critique_cap]}\n\n"
            "Write the best possible final answer. Integrate the Expert's substance and the "
            "Critic's corrections. Match the length and depth to the question and the available "
            "material — when the topic is rich and well-supported, write a thorough, structured "
            "answer with the specifics (names, dates, quotes, examples). Do not compress to a "
            "short paragraph if the material supports more."
        )
        _log(f"[synth] start ({backend}, streaming)")
        try:
            for token in _provider_stream(
                messages=[
                    {"role": "system", "content": ROLES["synthesizer"]["system"]},
                    {"role": "user", "content": synth_prompt},
                ],
                model_local=self.model,
                or_key=self.or_key,
                or_model=self.or_model,
                temperature=ROLES["synthesizer"]["temperature"],
                num_ctx=self.num_ctx_synth,
            ):
                yield ("token", token)
            _log("[synth] done")
        except Exception as e:
            _log(f"[synth] FAILED: {e}")
            yield ("token", f"\n\n*(Synthesis failed: {e} — showing Expert answer)*\n\n{expert_answer}")

    # ─── Critic with manifest + fetch_full_page tool ──────────────────────────

    def _run_critic(
        self,
        excerpt: str,
        expert_draft: str,
        retrieved_pages: dict | None,
    ):
        """
        Run the Critic step. When `retrieved_pages` is available, expose a
        manifest of all retrieved pages plus a `fetch_full_page` tool that
        returns the FULL content of a page already in memory (zero network
        cost). The Critic uses it to verify specific claims (dates, citation
        numbers, exact names) against the verbatim source when the excerpt
        doesn't contain them.

        Yields:
          ('status', msg)   — UI status during the loop
          ('tool_used', 'VERIFY')  — when Critic fetches a page for verification
          ('critique', text)  — final critique (always emitted last)
        """
        from node.provider import call as _provider_call

        has_manifest = bool(retrieved_pages)

        if has_manifest:
            manifest_lines = [
                "[Sources manifest — pages retrieved for this question]",
            ]
            for (pack, file), meta in retrieved_pages.items():
                title = meta.get("title", "") or file
                summary = (meta.get("summary", "") or "").replace("\n", " ")
                if len(summary) > 200:
                    summary = summary[:200].rstrip() + "..."
                manifest_lines.append(f"- {pack}/{file}  →  \"{title}\"  →  {summary}")
            manifest_block = "\n".join(manifest_lines)
        else:
            manifest_block = ""

        if excerpt and has_manifest:
            critic_prompt = (
                f"{manifest_block}\n\n"
                f"[Knowledge context — excerpt only, first {len(excerpt)} chars]\n{excerpt}\n\n"
                f"[Proposed answer]\n{expert_draft}\n\n"
                "Review this answer critically using the rules in your role. "
                "Use `fetch_full_page` ONLY when the proposed answer makes a specific "
                "factual claim (date, citation number, exact name, percentage, quote) "
                "that you cannot verify from the excerpt above AND whose likely source "
                "page IS in the manifest. Do not fetch speculatively."
            )
        elif excerpt:
            critic_prompt = (
                f"[Knowledge context]\n{excerpt}\n\n"
                f"[Proposed answer]\n{expert_draft}\n\n"
                "Review this answer critically."
            )
        else:
            critic_prompt = (
                f"[Proposed answer]\n{expert_draft}\n\n"
                "Review this answer critically."
            )

        # Tool schema and dispatch — only when we have retrieved_pages
        tools_schema = None
        if has_manifest:
            tools_schema = [{
                "type": "function",
                "function": {
                    "name": "fetch_full_page",
                    "description": (
                        "Fetch the full content of a page already retrieved for this "
                        "question. Use to verify a specific factual claim against the "
                        "verbatim source text when the excerpt doesn't contain enough. "
                        "Use the exact pack and file values from the manifest."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pack": {"type": "string", "description": "Pack path from the manifest."},
                            "file": {"type": "string", "description": "Page file from the manifest (e.g. 'concepts/foo.md')."},
                        },
                        "required": ["pack", "file"],
                    },
                },
            }]

        messages = [
            {"role": "system", "content": ROLES["critic"]["system"]},
            {"role": "user", "content": critic_prompt},
        ]

        MAX_TOOL_ROUNDS = 3
        for _ in range(MAX_TOOL_ROUNDS + 1):
            resp = _provider_call(
                messages=messages,
                model_local=self.model,
                or_key=self.or_key,
                or_model=self.or_model,
                tools=tools_schema,
                temperature=ROLES["critic"]["temperature"],
                num_ctx=self.num_ctx_answer,
            )
            messages.append(resp.assistant_message())

            if not getattr(resp, "tool_calls", None):
                yield ("critique", resp.content or "")
                return

            # Dispatch tool calls (only fetch_full_page is allowed here)
            for tc in resp.tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                if fn_name != "fetch_full_page" or not has_manifest:
                    result = f"Tool '{fn_name}' is not available in this Critic loop."
                else:
                    pack = (fn_args.get("pack") or "").strip()
                    file = (fn_args.get("file") or "").strip()
                    page = retrieved_pages.get((pack, file))
                    if page is None:
                        result = (
                            f"No page found at pack='{pack}' file='{file}'. "
                            "Use exact values from the manifest."
                        )
                    else:
                        yield ("status", f"Critic verifying source: {file}...")
                        yield ("tool_used", _tool_label("fetch_full_page"))
                        result = (
                            f"[Full content of {pack}/{file}]\n"
                            f"{page.get('content', '')}"
                        )
                messages.append(resp.tool_result(tc, result))

        # Hit the round cap without a clean answer — return whatever the model
        # produced last (likely a tool call without explanation). Empty is OK.
        yield ("critique", "")

    # ─── Chat (tools) ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_web_sources(result: str) -> list[dict]:
        sources = []
        title = ""
        for line in result.splitlines():
            if line.startswith("**") and line.endswith("**"):
                title = line.strip("*").strip()
            elif line.startswith("Source: http"):
                url = line[8:].strip()
                sources.append({"title": title or url, "url": url})
                title = ""
        return sources

    def _stream_with_tools(self, system: str, prompt: str, temperature: float = 0.7, images: list | None = None):
        from node.deliberation.tools import TOOL_FUNCTIONS, get_allowed_tools
        from node.provider import call as _provider_call

        # Per-turn gate: web tools only if the user explicitly invokes the web
        # (URL in message, or words like "web", "online", "internet"). Other
        # tools are always available. The gate is the user's CURRENT message,
        # not history — explicit consent is per-turn.
        allowed_schema, allowed_fn_names = get_allowed_tools(prompt)

        user_msg: dict = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = images
        messages = [
            {"role": "system", "content": system},
            *self._history,
            user_msg,
        ]

        web_sources: list[dict] = []

        while True:
            self._peak_ctx_used = self._measure_ctx(messages)
            resp = _provider_call(
                messages, self.model, self.or_key, self.or_model,
                allowed_schema, temperature, self.num_ctx_answer,
            )
            self._update_ctx(resp.prompt_tokens, resp.completion_tokens)
            messages.append(resp.assistant_message())

            if not resp.tool_calls:
                if web_sources:
                    yield ("peer_answers", {"mode": "web", "web_sources": web_sources})
                yield ("token", resp.content)
                return

            for tc in resp.tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                if fn_name not in allowed_fn_names:
                    # Defense-in-depth: model tried a tool that wasn't exposed.
                    result = (
                        f"Tool '{fn_name}' is not available for this turn. "
                        "Web tools require the user to explicitly ask to search the web "
                        "or to provide a URL. Answer from the loaded knowledge packs instead."
                    )
                    messages.append(resp.tool_result(tc, result))
                    continue
                fn = TOOL_FUNCTIONS.get(fn_name)
                if fn:
                    yield ("status", _tool_status(fn_name, fn_args))
                    yield ("tool_used", _tool_label(fn_name))
                    result = fn(**fn_args)
                    if fn_name == "web_search":
                        web_sources.extend(self._parse_web_sources(result))
                    elif fn_name == "fetch_url":
                        url = fn_args.get("url", "")
                        if url:
                            web_sources.append({"title": url, "url": url})
                else:
                    result = f"Unknown tool: {fn_name}"
                messages.append(resp.tool_result(tc, result))
