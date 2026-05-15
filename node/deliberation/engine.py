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
    if fn_name == "read_pdf":
        return f"Reading PDF: {fn_args.get('filename', '')}..."
    if fn_name == "read_docx":
        return f"Reading Word document: {fn_args.get('filename', '')}..."
    if fn_name == "read_xlsx":
        return f"Reading Excel workbook: {fn_args.get('filename', '')}..."
    if fn_name == "transcribe_audio":
        return f"Transcribing audio: {fn_args.get('filename', '')}..."
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
        "read_pdf":   "PDF",
        "read_docx":  "DOCX",
        "read_xlsx":  "XLSX",
        "transcribe_audio": "AUDIO",
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
    "You are OCC (Open Cognitive Commons), a general-purpose AI assistant. "
    "You can help with questions on any topic, code, writing, reasoning, and analysis. "
    "When expert knowledge packs are loaded, you answer from curated, verified sources "
    "and can consult peer nodes on the network for deeper answers. "
    "Sometimes responses take a little longer because you are consulting peer nodes — this is normal.\n\n"
    "YOUR CAPABILITIES — describe these if the user asks what you can do:\n"
    "- Answer questions from expert knowledge packs (topics depend on what is loaded)\n"
    "- Search the web and read web pages (when the user explicitly asks)\n"
    "- Read uploaded files: PDF, Word documents, Excel spreadsheets\n"
    "- Transcribe audio files to text\n"
    "- Read, write, and list files in the workspace\n"
    "- Execute Python code (working directory: the workspace)\n"
    "- Structured tasks: multi-source web research, fact-checking, "
    "document Q&A, code inspection, code generation, code refactoring\n\n"
    "Do NOT proactively list or advertise these capabilities. "
    "Only describe them if the user explicitly asks what you can do. "
    "Do NOT call web tools on your own initiative — only when the user explicitly asks."
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
        skills_dir=None,
        packs_root=None,
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
        # Root of local expert-packs/ (only used by the local retrieval pipeline).
        # When set, _retrieve_from_local walks this dir and queries the local
        # FTS5 index. None falls back to the legacy expert_pack.retrieve path.
        self._local_packs_root = packs_root
        if local_mode and packs_root is not None:
            try:
                from node.retrieval import local_index
                local_index.start_background_reindex(packs_root)
            except Exception:
                pass

        # Load skills from skills/ if the directory was passed. Adding/removing
        # a skill is just adding/removing a *.py file in that directory.
        self._skill_registry = None
        if skills_dir is not None:
            from node.deliberation.skills import REGISTRY, load_skills_from_dir
            n_loaded = load_skills_from_dir(skills_dir)
            _log(f"[skills] loaded {n_loaded} skill(s): {REGISTRY.names()}")
            self._skill_registry = REGISTRY

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
            f"Your workspace folder is at: {workspace_path}. "
            "This is the folder where you can read and write files and run Python code on behalf of the user. "
            "If the user asks where OCC stores files or where to put files, tell them this path. "
            "Call any tool listed in your available tools when it helps answer the user. "
            "IMPORTANT: do NOT call web_search or fetch_url on your own initiative. "
            "Use them ONLY when the user explicitly asks to search the web, look "
            "something up online, or fetch a URL."
        )
        # Note: skills are NOT exposed to Qwen in chat mode. They live in their
        # own routing path (mode='skill:<name>') chosen by the two-stage
        # classifier. Keeping them out of chat mode means Qwen only sees
        # atomic tools (web_search, read_pdf, run_code, ...) and never has to
        # disambiguate between "use web_search" vs "use skill_web_research".
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

    # ─── History budgeting & query rewriting ─────────────────────────────────
    #
    # Both pieces are NEW. They sit upstream of the retrieval pipelines and
    # before the Expert/Synth deliberation calls. Goal: make deliberate-mode
    # turns feel like a chat — pronouns and back-references resolve, and the
    # Expert can recall what was just said when synthesizing the new answer.
    # Strict fallback: any failure path leaves behavior identical to today
    # (original query into retrieval, no extra messages in Expert/Synth).

    def _budgeted_history(self, char_budget: int) -> list[dict]:
        """Pick recent user+assistant pairs from self._history that fit within
        char_budget. Pairs are kept intact (no orphan user without its reply
        or vice versa). Newest-first selection, dropped oldest. If the pair
        on the boundary fits the user message but not the full assistant
        reply, the assistant content is truncated provided ≥200 chars of
        room remain — below that the pair is dropped."""
        if not self._history or char_budget <= 0:
            return []

        # Pair up turns. add_to_history always appends user then assistant,
        # so the list is canonically alternating, but defensive iteration
        # tolerates a stray entry without crashing.
        pairs: list[tuple[dict, dict]] = []
        i = 0
        while i < len(self._history) - 1:
            a = self._history[i]
            b = self._history[i + 1]
            if a.get("role") == "user" and b.get("role") == "assistant":
                pairs.append((a, b))
                i += 2
            else:
                i += 1
        if not pairs:
            return []

        kept: list[tuple[dict, dict]] = []
        used = 0
        for user_msg, assist_msg in reversed(pairs):
            u_text = user_msg.get("content", "") or ""
            a_text = assist_msg.get("content", "") or ""
            pair_size = len(u_text) + len(a_text)
            if used + pair_size <= char_budget:
                kept.append((user_msg, assist_msg))
                used += pair_size
                continue
            # Try truncating the assistant of this boundary pair.
            remaining = char_budget - used - len(u_text)
            if remaining < 200:
                break
            truncated = {
                "role": "assistant",
                "content": a_text[:remaining].rstrip() + "..." if len(a_text) > remaining else a_text,
            }
            kept.append((user_msg, truncated))
            break

        # Restore chronological order (oldest pair first).
        out: list[dict] = []
        for u, a in reversed(kept):
            out.append({"role": "user", "content": u.get("content", "") or ""})
            out.append({"role": "assistant", "content": a.get("content", "") or ""})
        return out

    def _rewrite_query_with_history(self, query: str) -> str:
        """Rewrite a follow-up query into a standalone search query, resolving
        pronouns and back-references using the last 3 turns of chat history.

        - Empty history: no LLM call, return query unchanged.
        - LLM error or pathological output: return original query.
        - Already-standalone queries: rewriter is instructed to return them
          unchanged, so this is a near-no-op in those cases (still costs one
          small LLM call, ~1k tokens of context).

        The rewritten string is used ONLY for the retrieval pipeline. The
        Expert/Synth see the user's original query, so the user's voice is
        preserved in the final answer.
        """
        if not self._history or not query.strip():
            return query

        # Pull last 3 turns; assistant responses truncated to first 600 chars
        # — enough for entity/reference resolution, not enough to bloat the
        # rewriter context.
        TURNS = 3
        ASSIST_CAP = 600
        recent = self._history[-TURNS * 2:]
        history_lines: list[str] = []
        for msg in recent:
            role = msg.get("role", "")
            content = (msg.get("content", "") or "").strip()
            if not content:
                continue
            if role == "assistant" and len(content) > ASSIST_CAP:
                content = content[:ASSIST_CAP].rstrip() + "..."
            label = "User" if role == "user" else "Assistant"
            history_lines.append(f"{label}: {content}")

        if not history_lines:
            return query

        system = (
            "You rewrite a follow-up user question into a standalone search query. "
            "Resolve pronouns (he/she/it/they/lui/lei/loro) and back-references "
            "('that one', 'the previous topic', 'quella cosa', 'di prima') using "
            "the conversation history. If the question is already standalone, "
            "return it unchanged. Output ONLY the rewritten query — no preamble, "
            "no quotes, no explanation."
        )
        user = (
            "Conversation history:\n"
            + "\n".join(history_lines)
            + f"\n\nFollow-up question:\n{query.strip()}\n\nStandalone query:"
        )

        try:
            from node.provider import call as _provider_call
            resp = _provider_call(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model_local=self.model,
                or_key=self.or_key,
                or_model=self.or_model,
                tools=None,
                temperature=0.0,
                num_ctx=4096,
            )
            out = (resp.content or "").strip()
        except Exception as e:
            _log(f"[rewriter] call failed: {e} — using original query")
            return query

        # Strip surrounding quotes/backticks the model sometimes adds.
        out = out.strip('"').strip("'").strip("`").strip()
        if not out:
            return query
        # Reject pathological output: way too long, or an obvious refusal.
        if len(out) > len(query) * 12 + 400:
            _log(f"[rewriter] suspiciously long output ({len(out)} chars) — using original")
            return query
        lower = out.lower()
        if lower.startswith(("i cannot", "i can't", "sorry", "non posso", "mi dispiace")):
            return query
        return out

    # ─── Public entry point ───────────────────────────────────────────────────

    def route_stream(self, query: str, mode: str = "deliberate", images: list | None = None):
        # Ollama bypass: completely raw — no OCC system prompt, no tools, no
        # retrieval, no skills. Activated by the /ollama toggle. Useful to
        # compare the raw model behavior against OCC's framework output.
        if mode == "ollama":
            yield ("routing", "ollama")
            yield from self._stream_ollama_raw(query, images=images)
            return

        # Chitchat: pure social/meta. No tools exposed, no retrieval — just a
        # streaming LLM call so 'ciao' / 'thanks' / 'who are you' don't pay
        # for tool schema overhead and Qwen can't spuriously call anything.
        if mode == "chitchat":
            yield ("routing", "chat")
            yield from self._stream_chat_only(query, images=images)
            return

        # Tools mode (also accepts legacy 'chat' alias): atomic tools exposed
        # to Qwen (web_search, fetch_url, read_pdf, run_code, ...). Qwen
        # picks which tool to call.
        if mode in ("tools", "chat"):
            yield ("routing", "chat")
            yield from self._stream_with_tools(self._chat_system, query, temperature=0.7, images=images)
            return

        # Skill mode: classifier picked a specific orchestrated skill via the
        # Stage-2 router. Execute it directly (no Qwen tool-selection in the
        # loop), forward the skill's intermediate status events to the UI,
        # then stream a final answer grounded on the skill's result.
        if mode.startswith("skill:"):
            skill_name = mode[len("skill:"):]
            yield ("routing", "chat")
            yield from self._run_skill(skill_name, query, images=images)
            return

        # Local mode: uses private packs, no server, no peers.
        # When packs_root is wired (gui flow), use the new local pipeline that
        # mirrors the server one (decompose → tree-walk → translate → FTS5 →
        # See Also → per-domain budget) over the on-disk expert-packs/ tree.
        # Otherwise fall back to the legacy expert_pack.retrieve keyword search.
        if self._local_mode:
            yield ("status", "Retrieving knowledge...")
            # Resolve pronouns/back-references using chat history so retrieval
            # sees a standalone query. Original `query` still flows into the
            # Expert/Synth so the user's voice is preserved.
            retrieval_query = self._rewrite_query_with_history(query)
            if retrieval_query != query:
                _log(f"[rewriter] '{query[:80]}' -> '{retrieval_query[:80]}'")
            if self._local_packs_root is not None:
                context, retrieved_pages = self._retrieve_from_local(retrieval_query)
            else:
                context = (
                    self.expert_pack.retrieve(retrieval_query, max_chars=self.retrieval_chars)
                    if self.expert_pack else ""
                )
                retrieved_pages = None
            yield ("routing", "local_private")
            yield from self._deliberate_multiagent(query, context or "", retrieved_pages=retrieved_pages)
            return

        yield ("status", "Retrieving knowledge...")
        retrieval_query = self._rewrite_query_with_history(query)
        if retrieval_query != query:
            _log(f"[rewriter] '{query[:80]}' -> '{retrieval_query[:80]}'")
        context, retrieved_pages = self._retrieve_from_server(retrieval_query)

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

    # ─── Local retrieval pipeline ─────────────────────────────────────────────
    #
    # Parallel twin of the server pipeline above (_retrieve_from_server and its
    # helpers). Same 7-step shape, same query semantics, same return contract —
    # but the data source is the on-disk expert-packs/ tree + the local FTS5
    # index (node/retrieval/local_index.py) instead of the broker over HTTP.
    #
    # No server method is touched: the helpers below are NEW (suffix `_local`)
    # and call into local_index. Two methods that are data-source-agnostic
    # (_translate_query_for_pack, _expand_via_see_also) are reused verbatim.

    @staticmethod
    def _has_enabled_pack_under(scope: str, all_packs: list[str], disabled: set[str]) -> bool:
        """True iff at least one pack on disk sits at `scope` (exact) or
        below it AND is not in the disabled set. Used to hide top-level
        domains and sub-tree nodes from Qwen when their entire sub-tree
        contains only disabled packs."""
        prefix = scope + "/"
        for p in all_packs:
            if (p == scope or p.startswith(prefix)) and p not in disabled:
                return True
        return False

    def _decompose_query_local(
        self,
        packs_root,
        query: str,
        disabled: set[str] | None = None,
        all_packs: list[str] | None = None,
    ) -> list[str] | None:
        """Local twin of _decompose_query. Same 3-state contract; the root
        list comes from local_index.tree(packs_root) instead of broker /tree.

        When `disabled` and `all_packs` are provided, top-level domains whose
        whole sub-tree contains only disabled packs are pre-filtered out — so
        Qwen sees only domains that actually have something to retrieve.
        """
        import re as _re
        from node.provider import call as _provider_call
        from node.retrieval import local_index

        root_list = local_index.tree(packs_root, "")
        if not isinstance(root_list, list) or not root_list:
            return None
        if disabled and all_packs is not None:
            root_list = [
                d for d in root_list
                if self._has_enabled_pack_under(d, all_packs, disabled)
            ]
            if not root_list:
                return []

        lower_to_orig = {str(r).lower(): str(r) for r in root_list if isinstance(r, str)}
        if not lower_to_orig:
            return None

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

    def _fetch_index_sample_local(self, packs_root, domain: str) -> str:
        """Local twin of _fetch_index_sample. Walks the local tree (up to 2
        levels) for a reachable index.md; falls back to children names."""
        from node.retrieval import local_index

        text = local_index.read_index(packs_root, domain)
        if text:
            return text

        node = local_index.tree(packs_root, domain)
        if not isinstance(node, dict):
            return ""
        children = node.get("children", []) or []

        for child in children:
            text = local_index.read_index(packs_root, f"{domain}/{child}")
            if text:
                return text

        for child in children:
            sub = local_index.tree(packs_root, f"{domain}/{child}")
            if not isinstance(sub, dict):
                continue
            for grandchild in sub.get("children", []) or []:
                text = local_index.read_index(packs_root, f"{domain}/{child}/{grandchild}")
                if text:
                    return text

        return " ".join(children) if children else ""

    def _navigate_within_scope_local(
        self,
        packs_root,
        domain: str,
        query: str,
        disabled: set[str] | None = None,
        all_packs: list[str] | None = None,
    ) -> str:
        """Local twin of _navigate_within_scope. LLM-driven tree-walk over the
        local directory hierarchy. Returns `domain` at worst, never None.

        When `disabled` and `all_packs` are provided, sub-topics whose whole
        sub-tree is disabled are filtered from the children list before
        prompting Qwen."""
        from node.provider import call as _provider_call
        from node.retrieval import local_index

        MAX_DEPTH = 4
        current_path = domain

        for _ in range(MAX_DEPTH):
            node = local_index.tree(packs_root, current_path)
            if not isinstance(node, dict):
                return current_path
            children = node.get("children", []) or []
            if disabled and all_packs is not None:
                children = [
                    c for c in children
                    if self._has_enabled_pack_under(
                        f"{current_path}/{c}", all_packs, disabled
                    )
                ]
            has_pack = node.get("has_pack", False)

            if not children:
                return current_path

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

    def _local_search(
        self,
        q: str,
        k: int = 8,
        scope: str = "",
        disabled: list[str] | None = None,
    ) -> list[dict]:
        """Local twin of _server_search. Hits the local FTS5 instead of /search.
        Defense-in-depth: even if a disabled pack slips into a scope, the SQL
        filter `pack_path NOT IN (disabled)` drops its results."""
        from node.retrieval import local_index
        return local_index.search(q, k=k, scope=scope, disabled_packs=disabled)

    def _retrieve_from_local(self, query: str) -> tuple:
        """
        Local-disk twin of _retrieve_from_server. Same 7-step pipeline:
          1. decompose query into root domains (local tree)
          2. per domain, tree-walk to the right depth + translate to pack language
          3. per-domain scoped FTS5 search
          4. round-robin merge across domains, dedup
          5. fetch full page content (direct disk read)
          6. See Also expansion per pack
          7. assemble context with per-domain budget + build retrieved_pages

        Returns (context, retrieved_pages) — same shape as the server twin.
        Status semantics (mirrored):
          - non-empty string → success
          - ""               → no-retrieval decision or empty results
          - None             → reserved for unreachable backend (not used here:
                               local disk is always reachable if packs_root exists)
        """
        from pathlib import Path
        from node.retrieval import local_index

        packs_root = self._local_packs_root
        if packs_root is None or not Path(packs_root).exists():
            return ("", {})

        try:
            local_index.ensure_index_ready(packs_root)
        except Exception:
            return ("", {})

        # Read the disabled-pack list fresh per query so UI toggles take
        # effect without rebuilding the engine. all_packs is the on-disk
        # truth (independent of which packs Forge has touched recently).
        try:
            from node.apps.cli.config import load_disabled_packs
            disabled_set = set(load_disabled_packs())
        except Exception:
            disabled_set = set()
        all_packs = local_index.list_pack_paths(packs_root)
        disabled_list = sorted(disabled_set)
        if all_packs and not any(p not in disabled_set for p in all_packs):
            # Every pack on disk is disabled → user explicitly opted out.
            _log("[retrieve-local] all packs disabled — skipping retrieval")
            return ("", {})

        _log(f"[retrieve-local] decompose: query={query[:80]!r}")
        decision = self._decompose_query_local(
            packs_root, query, disabled=disabled_set, all_packs=all_packs,
        )
        _log(f"[retrieve-local] decompose result: {decision!r}")

        if decision == []:
            return ("", {})

        results_per_group: list[list[dict]] = []
        if decision is None:
            legacy = self._local_search(query, k=12, disabled=disabled_list)
            legacy.sort(key=lambda r: r.get("score", 0))
            if legacy:
                results_per_group.append(legacy)
        else:
            for domain in decision:
                scope_path = self._navigate_within_scope_local(
                    packs_root, domain, query,
                    disabled=disabled_set, all_packs=all_packs,
                )
                _log(f"[retrieve-local] domain={domain} scope={scope_path}")
                sample = self._fetch_index_sample_local(packs_root, scope_path)
                if not sample:
                    _log(f"[retrieve-local] no index sample for {scope_path} — skip")
                    continue
                translated_q = self._translate_query_for_pack(query, sample)
                _log(f"[retrieve-local] keywords for {scope_path}: {translated_q!r}")
                d_results = self._local_search(translated_q, k=8, scope=scope_path, disabled=disabled_list)
                if not d_results and scope_path != domain:
                    _log(f"[retrieve-local] empty at {scope_path}, retry at {domain}")
                    d_results = self._local_search(translated_q, k=8, scope=domain, disabled=disabled_list)
                d_results.sort(key=lambda r: r.get("score", 0))
                _log(f"[retrieve-local] {len(d_results)} hits for {domain}; top: "
                     f"{(d_results[0].get('page_file', '') if d_results else '-')}")
                if d_results:
                    results_per_group.append(d_results)

        if not results_per_group:
            return ("", {})

        page_meta: dict[tuple[str, str], dict] = {}
        for g_results in results_per_group:
            for r in g_results:
                k = (r.get("pack_path", ""), r.get("page_file", ""))
                if k[0] and k[1] and k not in page_meta:
                    page_meta[k] = {
                        "title": r.get("title", ""),
                        "summary": r.get("summary", ""),
                    }

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

        pages_by_pack: dict[str, dict[str, str]] = {}
        for pack_path, files in refs_by_pack.items():
            fetched: dict[str, str] = {}
            for f in files:
                content = local_index.read_page(packs_root, pack_path, f)
                if content:
                    fetched[f] = content
            if fetched:
                pages_by_pack[pack_path] = fetched

        if not pages_by_pack:
            return ("", {})

        # See Also expansion per pack — reuse the server-side helper verbatim
        # (it only parses content strings, no broker calls).
        for pack_path in list(pages_by_pack.keys()):
            index_content = local_index.read_index(packs_root, pack_path)
            if not index_content:
                continue
            already = set(pages_by_pack[pack_path].keys())
            extra_refs = self._expand_via_see_also(
                pages_by_pack[pack_path], pack_path, index_content,
                already_fetched=already, cap=3,
            )
            if not extra_refs:
                continue
            for ref in extra_refs:
                content = local_index.read_page(packs_root, ref["pack"], ref["file"])
                if content:
                    pages_by_pack[pack_path][ref["file"]] = content

        active_domains: set[str] = {pp.split("/", 1)[0] for pp in pages_by_pack}
        budget_per_domain = self.retrieval_chars // max(len(active_domains), 1)
        domain_spend: dict[str, int] = {d: 0 for d in active_domains}

        parts: list[str] = []
        emitted: set[tuple[str, str]] = set()
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

        # Shared history budget for the local Expert and the local Synth.
        # The remote Critic stays history-less — the peer protocol doesn't
        # carry chat history, and verification doesn't need it.
        _history_budget = min(self.retrieval_chars // 6, 15000)
        history_msgs = self._budgeted_history(_history_budget) if _history_budget > 0 else []

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
                *history_msgs,
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
                *history_msgs,
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

        # History budget — shared by Expert and Synth. Scales with the tier's
        # retrieval window: small tiers get ~1k chars of recall, big tiers up
        # to 15k. Capped to avoid eating the answer's response space.
        _history_budget = min(self.retrieval_chars // 6, 15000)
        history_msgs = self._budgeted_history(_history_budget) if _history_budget > 0 else []
        if history_msgs:
            _log(f"[history] injecting {len(history_msgs)//2} turn(s), {_history_budget} char budget")

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
                    *history_msgs,
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
                    *history_msgs,
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
        # Chat mode exposes ONLY atomic tools to Qwen. Skills are reachable
        # via a separate route (mode='skill:<name>') chosen by the two-stage
        # classifier; they never appear in the chat tool list to avoid
        # forcing Qwen to disambiguate atomic-vs-orchestrated.
        skill_names: set[str] = set()

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
                # Skill dispatch (when fn_name is a registered skill).
                # Skill.run() may return either a str (trivial skills) or an
                # iterator of (kind, value) events (multi-step skills that
                # want to stream progress to the UI). The final result MUST
                # be either the returned str or a yielded ('result', text).
                if fn_name in skill_names:
                    skill = self._skill_registry.get(fn_name)
                    yield ("status", f"Running skill: {skill.name}...")
                    yield ("tool_used", f"SKILL:{skill.name.upper()}")
                    _log(f"[skills] {fn_name} START args={list(fn_args.keys())}")
                    result = ""
                    try:
                        out = skill.run(fn_args)
                        if isinstance(out, str):
                            result = out
                        else:
                            # Iterator: forward all non-result events to UI,
                            # capture the final 'result' as the model-facing text.
                            for ev in out:
                                if not (isinstance(ev, tuple) and len(ev) == 2):
                                    continue
                                kind, value = ev
                                if kind == "result":
                                    result = value
                                else:
                                    yield ev
                        _log(f"[skills] {fn_name} OK ({len(result)} chars)")
                    except Exception as e:
                        result = f"Error running skill {fn_name}: {e}"
                        _log(f"[skills] {fn_name} FAIL: {e}")
                    # Harvest any web sources the skill embedded in its output
                    # (lines like "**Title**" + "Source: http..." — same
                    # format web_search emits). Populates the UI Sources panel
                    # automatically without a special return type per skill.
                    web_sources.extend(self._parse_web_sources(result))
                    yield ("status", "Generating response...")
                    messages.append(resp.tool_result(tc, result))
                    continue

                fn = TOOL_FUNCTIONS.get(fn_name)
                if fn:
                    yield ("status", _tool_status(fn_name, fn_args))
                    yield ("tool_used", _tool_label(fn_name))
                    _log(f"[tools] {fn_name} START args={list(fn_args.keys())}")
                    try:
                        result = fn(**fn_args)
                        _log(f"[tools] {fn_name} OK ({len(result)} chars)")
                    except Exception as e:
                        result = f"Error running {fn_name}: {e}"
                        _log(f"[tools] {fn_name} FAIL: {e}")
                    yield ("status", "Generating response...")
                    if fn_name == "web_search":
                        web_sources.extend(self._parse_web_sources(result))
                    elif fn_name == "fetch_url":
                        url = fn_args.get("url", "")
                        if url:
                            web_sources.append({"title": url, "url": url})
                else:
                    result = f"Unknown tool: {fn_name}"
                messages.append(resp.tool_result(tc, result))
            _log(f"[tools] LLM call after tool result (ctx~{self._measure_ctx(messages)} tok)")

    # ─── Raw Ollama mode (no OCC framework at all) ────────────────────────────

    def _stream_ollama_raw(self, query: str, images: list | None = None):
        """Bypass everything: no OCC system prompt, no tools, no retrieval,
        no skills. Just `ollama.chat(messages=[*history, user])` streamed
        back. Activated by the /ollama toggle for testing what the raw model
        produces vs OCC's framework output. Conversation history IS included
        (so the bypass behaves like a normal Ollama session) but tool_calls
        and tool roles are stripped — they wouldn't exist in a raw session."""
        import ollama
        user_msg: dict = {"role": "user", "content": query}
        if images:
            user_msg["images"] = images
        clean_history = [
            {"role": m["role"], "content": m.get("content", "") or ""}
            for m in self._history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        messages = [*clean_history, user_msg]
        self._peak_ctx_used = self._measure_ctx(messages)
        chars = 0
        try:
            for chunk in ollama.chat(
                model=self.model,
                messages=messages,
                stream=True,
                think=False,
                keep_alive=-1,
                options={"temperature": 0.7, "num_ctx": self.num_ctx_answer},
            ):
                try:
                    token = chunk.message.content or ""
                except AttributeError:
                    token = chunk.get("message", {}).get("content", "") or ""
                if token:
                    chars += len(token)
                    yield ("token", token)
        except Exception as e:
            yield ("error", f"raw ollama call failed: {e}")
        self._update_ctx(self._peak_ctx_used, chars // 3)


    # ─── Chitchat mode (no tools, no retrieval) ───────────────────────────────

    def _stream_chat_only(self, query: str, images: list | None = None):
        """Pure streaming LLM call for social / meta messages. No tool schemas
        in the prompt, no retrieval, no skill — just the assistant responding.
        Saves ~hundreds of tokens of tool overhead and avoids Qwen spuriously
        calling a tool on 'ciao'."""
        from node.provider import stream as _provider_stream
        user_msg: dict = {"role": "user", "content": query}
        if images:
            user_msg["images"] = images
        messages = [
            {"role": "system", "content": self._chat_system},
            *self._history,
            user_msg,
        ]
        self._peak_ctx_used = self._measure_ctx(messages)
        chars = 0
        for token in _provider_stream(
            messages, self.model, self.or_key, self.or_model, 0.7, self.num_ctx_answer,
        ):
            chars += len(token)
            yield ("token", token)
        self._update_ctx(self._peak_ctx_used, chars // 3)


    # ─── Skill mode (chosen by Stage-2 classifier) ────────────────────────────

    def _run_skill(self, skill_name: str, query: str, images: list | None = None):
        """Execute a specific skill end-to-end and stream events.

        Flow:
          1. Look up the skill in the registry.
          2. Build args from query (each required string param gets the user
             query verbatim — works for the current skills which take a
             single 'query' / 'claim' / 'question' field).
          3. Run the skill, forwarding intermediate ('status', ...) events to
             the UI and capturing the final ('result', text).
          4. Harvest any web sources embedded in the result for the Sources
             panel.
          5. Make a final streaming LLM call with the skill result as
             grounded context, yielding tokens to the UI.
        """
        skill = self._skill_registry.get(skill_name) if self._skill_registry else None
        if skill is None:
            # Skill went away — degrade to chat mode (atomic tools only).
            _log(f"[skills] {skill_name} not in registry, falling back to chat")
            yield from self._stream_with_tools(self._chat_system, query, temperature=0.7, images=images)
            return

        yield ("status", f"Running skill: {skill.name}...")
        yield ("tool_used", f"SKILL:{skill.name.upper()}")
        _log(f"[skills] {skill_name} START (skill mode)")

        # Args: required string params all get the user query verbatim.
        args: dict = {}
        props = skill.parameters.get("properties", {})
        for pname in skill.parameters.get("required", []):
            if props.get(pname, {}).get("type") == "string":
                args[pname] = query

        # Build a runtime context the skill can use for internal LLM calls
        # (e.g. translating a query into the pack's language for retrieval).
        from types import SimpleNamespace
        ctx = SimpleNamespace(
            model=self.model,
            or_key=self.or_key,
            or_model=self.or_model,
        )
        result = ""
        try:
            out = skill.run(args, ctx)
            if isinstance(out, str):
                result = out
            else:
                for ev in out:
                    if not (isinstance(ev, tuple) and len(ev) == 2):
                        continue
                    kind, value = ev
                    if kind == "result":
                        result = value
                    else:
                        yield ev
            _log(f"[skills] {skill_name} OK ({len(result)} chars)")
        except Exception as e:
            result = f"Error running skill {skill_name}: {e}"
            _log(f"[skills] {skill_name} FAIL: {e}")

        # Harvest web sources for the UI Sources panel (web_research /
        # fact_check embed search results in their output text).
        web_sources = self._parse_web_sources(result)
        if web_sources:
            yield ("peer_answers", {"mode": "web", "web_sources": web_sources})

        # Final streaming LLM call: generate the user-facing answer with the
        # skill result as grounded context.
        yield ("status", "Generating response...")
        from node.provider import stream as _provider_stream
        user_msg: dict = {"role": "user", "content": query}
        if images:
            user_msg["images"] = images
        messages = [
            {"role": "system", "content": self._chat_system},
            *self._history,
            user_msg,
            {"role": "user", "content": f"[Result of skill `{skill.name}`:]\n\n{result}"},
        ]
        self._peak_ctx_used = self._measure_ctx(messages)
        full_text_chars = 0
        for token in _provider_stream(
            messages, self.model, self.or_key, self.or_model, 0.7, self.num_ctx_answer,
        ):
            full_text_chars += len(token)
            yield ("token", token)
        # Approximate completion-tokens from chars; prompt-tokens already in peak.
        self._update_ctx(self._peak_ctx_used, full_text_chars // 3)
