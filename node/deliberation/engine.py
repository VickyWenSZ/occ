from datetime import datetime
from .roles import ROLES


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
    return f"Running {fn_name}..."


def _tool_label(fn_name: str) -> str:
    return {
        "web_search": "WEB",
        "fetch_url":  "URL",
        "read_file":  "FILE",
        "write_file": "FILE",
        "list_files": "FILE",
        "run_code":   "CODE",
    }.get(fn_name, fn_name.upper())


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
        self.retrieval_chars = retrieval_chars

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
            f"You have tools available: web_search, fetch_url, read_file, write_file, "
            f"list_files, run_code. Workspace directory: {workspace_path}. "
            "Use these tools whenever they help answer the user's request. "
            "Only use web_search when the user explicitly asks to search the web or internet."
        )
        self._chat_system = " ".join(parts)
        self._history: list[dict] = []
        self._last_ctx_used: int = 0
        self._peak_ctx_used: int = 0
        self._ctx_limit: int = num_ctx_answer

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
            yield from self._deliberate_multiagent(query, context)
            return

        yield ("status", "Retrieving knowledge...")
        context = self._retrieve_from_server(query)

        if context is None:
            yield ("routing", "local_fallback")
            yield ("status", "Server unavailable — answering from base model only...")
            yield from self._deliberate_multiagent(query, "")
            return

        best_peer = self._select_best_peer(mode)
        if best_peer:
            yield ("routing", "distributed")
            yield from self._deliberate_with_peer(query, context or "", best_peer)
        else:
            if mode == "network":
                yield ("status", "No peers available — running locally...")
            yield ("routing", "local")
            yield from self._deliberate_multiagent(query, context or "")

    # ─── Retrieval ────────────────────────────────────────────────────────────

    def _llm_select_packs(self, query: str, available_packs: list[str]) -> list[str]:
        from node.provider import call as _provider_call

        pack_list = "\n".join(f"- {p}" for p in available_packs)
        prompt = (
            f"Available knowledge packs:\n{pack_list}\n\n"
            f"Question: {query}\n\n"
            "List the pack names relevant to answer this question. "
            "One pack name per line, exactly as written above. "
            "If none are relevant, reply with: none"
        )
        try:
            resp = _provider_call(
                messages=[{"role": "user", "content": prompt}],
                model_local=self.model,
                or_key="",
                or_model="",
                tools=None,
                temperature=0.0,
                num_ctx=4096,
            )
            raw = resp.content or ""
            selected = []
            for line in raw.splitlines():
                line = line.strip().lstrip("- ").strip()
                if line in available_packs:
                    selected.append(line)
            return selected if selected else []
        except Exception:
            return []

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
                if "/" not in line:
                    continue
                parts = line.split("/", 1)
                if len(parts) != 2:
                    continue
                pack, filepath = parts[0].strip(), parts[1].strip()
                if pack in valid_files and filepath in valid_files[pack]:
                    refs.append({"pack": pack, "file": filepath})
                elif pack not in valid_files:
                    for pname, files in valid_files.items():
                        if line in files:
                            refs.append({"pack": pname, "file": line})
                            break
            return refs[:6]
        except Exception:
            return []

    def _retrieve_from_server(self, query: str) -> str | None:
        import asyncio
        import concurrent.futures
        from node.retrieval.pack_cache import (
            get_cached_wiki_dirs, fetch_pages, download_all_indices,
        )

        # 1. Assicura che la cache degli indici sia disponibile
        wiki_dirs = get_cached_wiki_dirs()
        if not wiki_dirs:
            ok = download_all_indices()
            if not ok:
                return None
            wiki_dirs = get_cached_wiki_dirs()
            if not wiki_dirs:
                return None

        available_packs = [wd.parent.name for wd in wiki_dirs]

        # 2. Call 0a — LLM sceglie pack rilevanti
        selected_pack_names = self._llm_select_packs(query, available_packs)

        # Fallback a embedding se LLM non sceglie nulla
        if not selected_pack_names:
            from node.retrieval.search import get_relevant_page_refs, relevant_pack_dirs
            relevant_dirs = relevant_pack_dirs(wiki_dirs, query)
            if not relevant_dirs:
                return ""
            page_refs: list[dict] = []
            for wiki_dir in relevant_dirs:
                page_refs.extend(get_relevant_page_refs(wiki_dir, query, max_pages=6))
            if not page_refs:
                return ""
        else:
            selected_wiki_dirs = [wd for wd in wiki_dirs if wd.parent.name in selected_pack_names]

            # 3. Leggi indici dalla cache locale
            indices: dict[str, str] = {}
            for wd in selected_wiki_dirs:
                index_path = wd / "index.md"
                if index_path.exists():
                    try:
                        indices[wd.parent.name] = index_path.read_text(encoding="utf-8")
                    except Exception:
                        pass

            if not indices:
                return ""

            # 4. Call 0b — LLM sceglie pagine specifiche
            page_refs = self._llm_select_pages(query, indices)

            # Fallback a embedding se LLM non trova pagine
            if not page_refs:
                from node.retrieval.search import get_relevant_page_refs
                page_refs = []
                for wd in selected_wiki_dirs:
                    page_refs.extend(get_relevant_page_refs(wd, query, max_pages=6))

        if not page_refs:
            return ""

        # 5. Fetch pagine dal server
        try:
            pages = asyncio.run(fetch_pages(page_refs))
        except RuntimeError:
            # GUI runs on asyncio — asyncio.run() fails inside a running loop.
            # Use a fresh thread with its own event loop instead.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    pages = pool.submit(asyncio.run, fetch_pages(page_refs)).result(timeout=30)
                except Exception:
                    return None

        if pages is None:
            return None
        if not pages:
            return ""

        # 6. Assembla il contesto — pagine intere fino al cap retrieval_chars
        parts = []
        total = 0
        for filename, content in pages.items():
            remaining = self.retrieval_chars - total
            if remaining <= 0:
                break
            chunk = content[:remaining]
            parts.append(f"[{filename}]\n{chunk}")
            total += len(chunk)
        return "\n\n".join(parts)

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
            "Produce the best possible answer, weighing both perspectives. "
            "Cover all relevant aspects. Include details, examples, and commands where useful."
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

    def _deliberate_multiagent(self, query: str, context: str):
        """3-call sequential deliberation: Expert → Critic → Synthesis (streaming)."""
        from node.provider import call as _provider_call, stream as _provider_stream

        # Call 1 — Expert
        yield ("status", "Expert analyzing...")
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
        except Exception as e:
            expert_answer = ""
            yield ("peer_answers", {"mode": "local", "expert_draft": "", "critic_review": f"[Expert call failed: {e}]"})
            yield ("token", f"*(Deliberation failed at Expert step: {e})*")
            return

        # Call 2 — Critic (context capped to avoid overflow on local models)
        yield ("status", "Critic reviewing...")
        _ctx_cap = 4000  # chars — keeps Critic input well within num_ctx_answer
        critic_context = context[:_ctx_cap] if context else ""
        _expert_cap = 3000
        critic_expert = expert_answer[:_expert_cap]
        if critic_context:
            critic_prompt = (
                f"[Knowledge context]\n{critic_context}\n\n"
                f"[Proposed answer]\n{critic_expert}\n\n"
                "Review this answer critically."
            )
        else:
            critic_prompt = (
                f"[Proposed answer]\n{critic_expert}\n\n"
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

        # Always emit peer_answers so Sources panel always appears in deliberate mode
        yield ("peer_answers", {
            "mode": "local",
            "expert_draft": expert_answer,
            "critic_review": critique,
        })

        # Call 3 — Synthesis (streaming) — uses num_ctx_synth, capped inputs
        yield ("status", "Synthesizing...")
        _synth_expert_cap = 4000
        _synth_critique_cap = 2000
        synth_prompt = (
            f"Original question: {query}\n\n"
            f"Initial answer:\n{expert_answer[:_synth_expert_cap]}\n\n"
            f"Critical review:\n{critique[:_synth_critique_cap]}\n\n"
            "Produce the best possible answer, weighing both perspectives. "
            "Cover all relevant aspects. Include details, examples, and commands where useful."
        )
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
        except Exception as e:
            yield ("token", f"\n\n*(Synthesis failed: {e} — showing Expert answer)*\n\n{expert_answer}")

    # ─── Chat (tools) ─────────────────────────────────────────────────────────

    def _stream_with_tools(self, system: str, prompt: str, temperature: float = 0.7, images: list | None = None):
        from node.deliberation.tools import TOOL_SCHEMA, TOOL_FUNCTIONS
        from node.provider import call as _provider_call

        user_msg: dict = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = images
        messages = [
            {"role": "system", "content": system},
            *self._history,
            user_msg,
        ]

        while True:
            self._peak_ctx_used = self._measure_ctx(messages)
            resp = _provider_call(
                messages, self.model, self.or_key, self.or_model,
                TOOL_SCHEMA, temperature, self.num_ctx_answer,
            )
            self._update_ctx(resp.prompt_tokens, resp.completion_tokens)
            messages.append(resp.assistant_message())

            if not resp.tool_calls:
                yield ("token", resp.content)
                return

            for tc in resp.tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                fn = TOOL_FUNCTIONS.get(fn_name)
                if fn:
                    yield ("status", _tool_status(fn_name, fn_args))
                    yield ("tool_used", _tool_label(fn_name))
                    result = fn(**fn_args)
                else:
                    result = f"Unknown tool: {fn_name}"
                messages.append(resp.tool_result(tc, result))
