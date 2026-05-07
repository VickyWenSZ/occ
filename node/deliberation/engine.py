import re
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

_LOCAL_RELEVANCE_THRESHOLD = 300


class DeliberationEngine:
    def __init__(
        self,
        model: str,
        expert_pack=None,
        peers: list[str] | None = None,
        num_ctx_answer: int = 8192,
        num_ctx_synth: int = 12288,
        retrieval_chars: int = 8000,
        domains: list[str] | None = None,
        workspace=None,
        openrouter_key: str = "",
        openrouter_model: str = "",
    ):
        self.model = model
        self.or_key = openrouter_key
        self.or_model = openrouter_model
        self.expert_pack = expert_pack
        self.peers = peers or []
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
        """Estimate total tokens from the actual messages array being sent to Ollama.
        More accurate than accumulation — measures exactly what enters the context window.
        ~3.5 chars per token for technical mixed-language content.
        """
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

        # DELIBERATE — retrieval + knowledge answer
        context = (
            self.expert_pack.retrieve(query, max_chars=self.retrieval_chars)
            if self.expert_pack
            else ""
        )
        local_relevant = len(context) >= _LOCAL_RELEVANCE_THRESHOLD

        yield from self._route_with_peers(query, context, local_relevant, images=images)

    # ─── Routing logic ────────────────────────────────────────────────────────

    def _route_with_peers(self, query: str, context: str, local_relevant: bool, images: list | None = None):
        from node.server.client import fetch_peer_manifests

        yield ("status", "Checking peer capabilities...")
        manifests = fetch_peer_manifests()
        if not manifests:
            yield ("routing", "local")
            yield ("status", "No peers available — answering locally...")
            yield from self._deliberate_local(query, context, images=images)
            return
        node_ids = list(manifests.keys())
        peer_assignments, additive = _assign_roles(query, node_ids, manifests)
        peer_domain_match = _has_domain_match(query, node_ids, manifests)

        if local_relevant and peer_domain_match:
            yield ("routing", "hybrid")
            roles_desc = ", ".join(r for u, r in peer_assignments)
            yield ("status", f"Hybrid — {roles_desc}...")
            yield from self._deliberate_hybrid(query, context, peer_assignments, additive, images=images)

        elif peer_domain_match:
            yield ("routing", "delegate")
            roles_desc = ", ".join(r for u, r in peer_assignments)
            yield ("status", f"Delegating to peers: {roles_desc}...")
            yield from self._deliberate_distributed(query, peer_assignments, additive)

        else:
            yield ("routing", "local")
            yield ("status", "Answering from local knowledge...")
            yield from self._deliberate_local(query, context, images=images)

    # ─── Mode: LOCAL ──────────────────────────────────────────────────────────

    def _deliberate_local(self, query: str, context: str | None = None, images: list | None = None):
        if context is None:
            context = (
                self.expert_pack.retrieve(query, max_chars=self.retrieval_chars)
                if self.expert_pack
                else ""
            )
        if context:
            prompt = (
                f"[Knowledge base context]\n{context}\n\n"
                f"Question: {query}\n\n"
                "Answer using the knowledge base context above. "
                "Be proportional: a precise question deserves a precise answer, "
                "a broad question can have a broader answer. No padding, no repetition."
            )
        else:
            prompt = f"Question: {query}\n\nAnswer helpfully and concisely."
        yield ("status", "Thinking...")
        yield from self._stream_with_tools(
            ROLES["answerer"]["system"], prompt,
            temperature=ROLES["answerer"]["temperature"],
            images=images,
        )

    # ─── Mode: DELEGATE ───────────────────────────────────────────────────────

    def _deliberate_distributed(self, query: str, peer_assignments: list, additive: bool):
        from node.server.client import call_peers_parallel

        responses = call_peers_parallel(peer_assignments, query)
        perspective_a, perspective_b = _collect_perspectives(responses, additive)

        failed = [r for r in responses if r.error]
        if failed:
            names = ", ".join(r.role for r in failed)
            yield ("status", f"Peer(s) failed ({names}), synthesizing with available...")

        if not perspective_a and not perspective_b:
            yield ("status", "All peers unavailable — falling back to local...")
            yield from self._deliberate_local(query)
            return

        peer_a_url = peer_assignments[0][0] if peer_assignments else ""
        peer_b_url = peer_assignments[1][0] if len(peer_assignments) > 1 else ""
        yield ("peer_answers", {
            "mode": "delegate",
            "local_pack": "",
            "local_answer": "",
            "expert_peer": peer_a_url,
            "contrarian_peer": peer_b_url,
            "expert_answer": perspective_a,
            "contrarian_answer": perspective_b,
        })

        yield ("status", "Synthesizing...")
        prompt = _build_synthesis_prompt(query, perspective_a, perspective_b, additive=additive)
        for token in self._stream_synthesis(prompt):
            yield ("token", token)

    # ─── Mode: HYBRID ─────────────────────────────────────────────────────────

    def _deliberate_hybrid(self, query: str, context: str, peer_assignments: list, additive: bool, images: list | None = None):
        from node.server.client import call_peers_parallel

        yield ("status", "Calling peers...")
        responses = call_peers_parallel(peer_assignments, query)

        yield ("status", "Generating local perspective...")
        local_prompt = (
            f"[Knowledge base context]\n{context}\n\n"
            f"Question: {query}\n\n"
            "Answer using the knowledge base context above. "
            "Be proportional: a precise question deserves a precise answer, "
            "a broad question can have a broader answer. No padding, no repetition."
        )
        local_answer = self._generate_answer(local_prompt)

        perspective_a, perspective_b = _collect_perspectives(responses, additive)

        failed = [r for r in responses if r.error]
        if failed:
            names = ", ".join(r.role for r in failed)
            yield ("status", f"Peer(s) failed ({names}), synthesizing with available...")

        pack_name = self.expert_pack.name if self.expert_pack else "local"
        peer_a_url = peer_assignments[0][0] if peer_assignments else ""
        peer_b_url = peer_assignments[1][0] if len(peer_assignments) > 1 else ""
        yield ("peer_answers", {
            "mode": "hybrid",
            "local_pack": pack_name,
            "local_answer": local_answer,
            "expert_peer": peer_a_url,
            "contrarian_peer": peer_b_url,
            "expert_answer": perspective_a,
            "contrarian_answer": perspective_b,
        })

        yield ("status", "Synthesizing local + peer knowledge...")
        peer_answers = [a for a in [perspective_a, perspective_b] if a]
        prompt = _build_hybrid_synthesis_prompt(query, local_answer, peer_answers)
        for token in self._stream_synthesis(prompt):
            yield ("token", token)

    # ─── Core LLM call — tools always available ───────────────────────────────

    def _stream_with_tools(self, system: str, prompt: str, temperature: float = 0.7, images: list | None = None):
        from node.deliberation.tools import TOOL_SCHEMA, TOOL_FUNCTIONS
        from node.provider import call as _provider_call, stream_with_tools as _stream_tools

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

            if self.or_key:
                # OpenRouter: non-streaming (streaming+tools format differs)
                resp = _provider_call(
                    messages, self.model, self.or_key, self.or_model,
                    TOOL_SCHEMA, temperature, self.num_ctx_answer,
                )
                self._update_ctx(resp.prompt_tokens, resp.completion_tokens)
                messages.append(resp.assistant_message())
                if not resp.tool_calls:
                    yield ("token", resp.content)
                    return
                tool_calls = resp.tool_calls
                def _tool_result(tc, result):
                    return resp.tool_result(tc, result)
            else:
                # Ollama: real streaming, tool calls arrive in final chunk
                done = None
                for event, val in _stream_tools(messages, self.model, TOOL_SCHEMA, temperature, self.num_ctx_answer):
                    if event == "token":
                        yield ("token", val)
                    elif event == "done":
                        done = val
                content = done["content"] if done else ""
                tool_calls = done["tool_calls"] if done else None
                messages.append({"role": "assistant", "content": content, "tool_calls": done["raw_tcs"] if done else None})
                if not tool_calls:
                    return
                def _tool_result(tc, result):
                    return {"role": "tool", "content": result}

            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments or {}
                fn = TOOL_FUNCTIONS.get(fn_name)
                if fn:
                    yield ("status", _tool_status(fn_name, fn_args))
                    result = fn(**fn_args)
                else:
                    result = f"Unknown tool: {fn_name}"
                messages.append(_tool_result(tc, result))

    # ─── Non-streaming helpers (hybrid/synthesis) ─────────────────────────────

    def _generate_answer(self, prompt: str) -> str:
        from node.provider import call as _provider_call
        cfg = ROLES["answerer"]
        resp = _provider_call(
            messages=[
                {"role": "system", "content": cfg["system"]},
                *self._history,
                {"role": "user", "content": prompt},
            ],
            model_local=self.model,
            or_key=self.or_key,
            or_model=self.or_model,
            tools=None,
            temperature=cfg["temperature"],
            num_ctx=self.num_ctx_answer,
        )
        return resp.content

    def _stream_synthesis(self, prompt: str):
        from node.provider import stream as _provider_stream
        cfg = ROLES["synthesizer"]
        yield from _provider_stream(
            messages=[
                {"role": "system", "content": cfg["system"]},
                {"role": "user", "content": prompt},
            ],
            model_local=self.model,
            or_key=self.or_key,
            or_model=self.or_model,
            temperature=cfg["temperature"],
            num_ctx=self.num_ctx_synth,
        )

    # ─── Backward compat ──────────────────────────────────────────────────────

    def deliberate_stream(self, query: str):
        yield from self._deliberate_local(query)

    def deliberate_stream_distributed(self, query: str):
        yield from self._route_with_peers(query)


# ─── Module-level helpers ─────────────────────────────────────────────────────

def _collect_perspectives(responses, additive: bool) -> tuple[str, str]:
    expert_responses = [r for r in responses if r.role == "expert" and not r.error]
    contrarian_responses = [r for r in responses if r.role == "contrarian" and not r.error]
    perspective_a = expert_responses[0].answer if expert_responses else ""
    if additive and len(expert_responses) > 1:
        perspective_b = expert_responses[1].answer
    else:
        perspective_b = contrarian_responses[0].answer if contrarian_responses else ""
    return perspective_a, perspective_b


def _has_domain_match(query: str, peers: list[str], manifests: dict[str, dict]) -> bool:
    query_words = set(re.findall(r'[a-z]+', query.lower()))
    for url in peers:
        domains = manifests.get(url, {}).get("domains", [])
        domain_words = set(w for d in domains for w in re.findall(r'[a-z]+', d.lower()))
        if query_words & domain_words:
            return True
    return False


def _assign_roles(query: str, peers: list[str], manifests: dict[str, dict]) -> tuple[list[tuple[str, str]], bool]:
    query_words = set(re.findall(r'[a-z]+', query.lower()))
    relevant, irrelevant = [], []
    for url in peers:
        domains = manifests.get(url, {}).get("domains", [])
        domain_words = set(w for d in domains for w in re.findall(r'[a-z]+', d.lower()))
        if query_words & domain_words:
            relevant.append((url, domains))
        else:
            irrelevant.append((url, domains))

    if not relevant:
        return [(url, "expert") for url in peers], True
    if len(relevant) == 1:
        return [(relevant[0][0], "expert")], True

    domains_a = set(re.findall(r'[a-z]+', " ".join(relevant[0][1]).lower()))
    domains_b = set(re.findall(r'[a-z]+', " ".join(relevant[1][1]).lower()))
    same_domain = bool(domains_a & domains_b)

    if same_domain:
        return [(relevant[0][0], "expert"), (relevant[1][0], "contrarian")], False
    else:
        return [(url, "expert") for url, _ in relevant[:2]], True


def _build_synthesis_prompt(query: str, perspective_a: str, perspective_b: str, additive: bool = False) -> str:
    parts = ["", f"Original question: {query}\n\n"]
    if additive:
        if perspective_a:
            parts.append(f"[Expert perspective 1]\n{perspective_a}\n\n")
        if perspective_b:
            parts.append(f"[Expert perspective 2]\n{perspective_b}\n\n")
        parts.append(
            "Integrate both expert perspectives into a single, complete, well-organized answer. "
            "Each perspective covers a different domain — combine them coherently."
        )
    else:
        if perspective_a:
            parts.append(f"[Expert analysis]\n{perspective_a}\n\n")
        if perspective_b:
            parts.append(f"[Critical review]\n{perspective_b}\n\n")
        parts.append(
            "Synthesize the above into a single, complete, well-organized answer. "
            "Resolve disagreements and keep the strongest points."
        )
    return "".join(parts)


def _build_hybrid_synthesis_prompt(query: str, local_answer: str, peer_answers: list[str]) -> str:
    parts = ["", f"Original question: {query}\n\n"]
    if local_answer:
        parts.append(f"[Local node knowledge]\n{local_answer}\n\n")
    for i, ans in enumerate(peer_answers, 1):
        if ans:
            parts.append(f"[Peer node {i} knowledge]\n{ans}\n\n")
    parts.append(
        "Synthesize all knowledge sources into a single, well-organized answer. "
        "Combine coherently, eliminate repetition. Be proportional to the original question."
    )
    return "".join(parts)


