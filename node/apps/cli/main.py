"""
OCC Node — Open Cognitive Commons
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.live import Live
from rich.text import Text
from rich.table import Table

import ollama

from node.deliberation.engine import DeliberationEngine
from node.deliberation.classifier import classify
from node.deliberation.tools import set_workspace
from node.expert_runtime.pack import load_pack, load_all_packs, MultiPackRetriever
from node.apps.cli.config import Config
from node.hardware import (
    is_ollama_installed, is_ollama_running, start_ollama,
    install_ollama_linux, is_model_installed, pull_model_stream,
    detect_vram_gb, select_tier, OLLAMA_DOWNLOAD_URL,
)

console = Console()


def setup_check() -> bool:
    """
    First-run setup: verify Ollama is present and the recommended model is installed.
    Returns False if setup cannot complete and the node should not start.
    """
    import platform
    import webbrowser

    console.print(Panel(
        "[bold cyan]OCC Node — Setup[/bold cyan]",
        border_style="cyan", padding=(0, 2)
    ))
    console.print()

    # --- Ollama check ---
    console.print("[dim]Checking requirements...[/dim]")

    if not is_ollama_installed():
        if platform.system() == "Linux":
            console.print("  Ollama : [red]NOT FOUND[/red]")
            console.print("\n  Installing Ollama...")
            ok = install_ollama_linux()
            if ok:
                console.print("  [green]OK Ollama installed.[/green]")
            else:
                console.print(f"  [red]Auto-install failed.[/red]")
                console.print(f"  Please install manually: [bold]{OLLAMA_DOWNLOAD_URL}[/bold]")
                return False
        else:
            console.print("  Ollama : [red]NOT FOUND[/red]")
            console.print(f"\n  OCC Node requires Ollama to run local models.")
            console.print(f"  Download it from: [bold]{OLLAMA_DOWNLOAD_URL}[/bold]")
            console.print("  Opening download page in your browser...")
            webbrowser.open(OLLAMA_DOWNLOAD_URL)
            console.print("\n  Once installed, run this setup again.")
            return False
    else:
        console.print("  Ollama : [green]OK[/green]")

    if not is_ollama_running():
        console.print("  Ollama service : [yellow]not running[/yellow] — starting...")
        ok = start_ollama()
        if ok:
            console.print("  Ollama service : [green]OK started[/green]")
        else:
            console.print("  [red]Could not start Ollama. Please run 'ollama serve' manually.[/red]")
            return False
    else:
        console.print("  Ollama service : [green]OK[/green]")

    # --- Hardware detection ---
    console.print()
    console.print("[dim]Detecting hardware...[/dim]")
    vram_gb = detect_vram_gb()
    tier = select_tier(vram_gb)

    if vram_gb > 0:
        console.print(f"  GPU  : [bold]{vram_gb:.0f}GB VRAM[/bold]")
    else:
        console.print(f"  GPU  : [dim]not detected — CPU mode[/dim]")

    console.print()
    console.print(f"  Assigned tier : [bold cyan]{tier['name']}[/bold cyan]")
    console.print(f"  Model         : [bold]{tier['model']}[/bold]")

    if tier.get("at_minimum"):
        console.print(
            f"  [yellow]!!  {vram_gb:.0f}GB VRAM is the minimum for this tier.[/yellow]\n"
            f"  [dim yellow]    Responses may be slower during long deliberations.[/dim yellow]"
        )
    if tier["name"] == "micro":
        console.print(
            "  [yellow]!!  CPU-only mode: expect slower response times (5-30s per reply).[/yellow]"
        )

    # --- Model check ---
    console.print()
    model = tier["model"]
    if is_model_installed(model):
        console.print(f"  [green]OK {model} already installed.[/green]")
    else:
        answer = Prompt.ask(
            f"  Model [bold]{model}[/bold] not found locally. Download now?",
            choices=["y", "n"], default="y"
        )
        if answer == "n":
            console.print("  [red]Cannot start without the model. Exiting.[/red]")
            return False

        console.print()
        _pull_with_progress(model)

    console.print()
    return True


def _pull_with_progress(model: str):
    from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn

    with Progress(
        "[bold cyan]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Downloading {model}...", total=None)
        for status, completed, total in pull_model_stream(model):
            if total:
                progress.update(task, total=total, completed=completed)
            else:
                progress.update(task, description=f"{model} — {status}")

    console.print(f"  [green]OK {model} downloaded.[/green]")


def warmup_model(model: str):
    with console.status(f"[dim yellow]Loading {model} into memory...[/dim yellow]"):
        try:
            list(ollama.chat(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                think=False,
                keep_alive=-1,
                options={"num_predict": 1},
                stream=True,
            ))
            console.print("[dim]Model ready.[/dim]\n")
        except Exception as e:
            console.print(f"[red]Warning: could not warm up model ({e})[/red]\n")


def print_banner(cfg: Config, retriever: MultiPackRetriever | None, workspace):
    vram_str = f"{cfg.detected_vram_gb}GB VRAM" if cfg.detected_vram_gb > 0 else "VRAM unknown"
    profile_str = f"[bold]{cfg.hardware_profile}[/bold] profile · {vram_str}"

    if retriever and retriever.packs:
        domains = ", ".join(retriever.domains[:8])
        pack_str = f"{len(retriever.packs)} pack(s) · {domains}"
    else:
        pack_str = "no packs loaded"

    console.print(
        Panel(
            "[bold cyan]OCC — Open Cognitive Commons[/bold cyan]\n"
            f"[dim]model: [bold]{cfg.model}[/bold] · {profile_str}[/dim]\n"
            f"[dim]knowledge: {pack_str}[/dim]\n"
            f"[dim]workspace: {workspace}[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()


def print_help(model: str, retriever):
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="dim")
    table.add_row("/?", "show this help")
    table.add_row("/clear", "clear conversation history and reset context")
    table.add_row("! <query>", "force knowledge retrieval (bypass classifier)")
    table.add_row("/model <name>", "switch model  (e.g. /model deepseek-r1:14b)")
    table.add_row("/pack <name>", "load a specific pack  (e.g. /pack docker)")
    table.add_row("/packs", "list all loaded packs and domains")
    table.add_row("/peers", "show configured peer nodes")
    table.add_row("/status", "show current config")
    table.add_row("/unload", "unload model from VRAM")
    table.add_row("/load", "reload model into VRAM")
    table.add_row("exit / quit / q", "quit")
    console.print(table)
    console.print()


def build_engine(cfg: Config, retriever, model: str, peers: list[str], workspace=None) -> DeliberationEngine:
    domains = retriever.domains if retriever else []
    return DeliberationEngine(
        model=model,
        expert_pack=retriever,
        peers=peers,
        num_ctx_answer=cfg.num_ctx_answer,
        num_ctx_synth=cfg.num_ctx_synth,
        retrieval_chars=cfg.retrieval_chars,
        domains=domains,
        workspace=workspace,
    )


def _start_broker_agent_background():
    import threading
    import asyncio
    from node.server.broker_agent import run as broker_run

    def _thread():
        asyncio.run(broker_run())

    t = threading.Thread(target=_thread, daemon=True)
    t.start()


def run():
    force_setup = "--setup" in sys.argv or "--detect" in sys.argv
    cfg = Config()

    if force_setup or not is_model_installed(cfg.model):
        ok = setup_check()
        if not ok:
            sys.exit(1)
        # Reload config after potential tier change
        cfg = Config()

    # Load packs: single if OCC_PACK set, otherwise all
    if cfg.pack_name:
        pack_path = cfg.packs_root / cfg.pack_name
        if pack_path.exists():
            retriever = MultiPackRetriever([load_pack(pack_path)])
        else:
            console.print(f"[red]Pack '{cfg.pack_name}' not found.[/red]\n")
            retriever = MultiPackRetriever([])
    else:
        retriever = load_all_packs(cfg.packs_root)

    workspace = ROOT / "workspace"
    workspace.mkdir(exist_ok=True)
    set_workspace(workspace)

    print_banner(cfg, retriever, workspace)

    model = cfg.model
    peers = cfg.peers

    _start_broker_agent_background()
    warmup_model(model)
    engine = build_engine(cfg, retriever, model, peers, workspace)

    if peers:
        console.print(f"[dim]Peers: {', '.join(peers)}[/dim]\n")
    console.print("[dim]Ask anything. Type /? for commands.[/dim]\n")

    while True:
        try:
            query = Prompt.ask("[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        query = query.strip()
        if not query:
            continue

        if query.lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if query in ("/?", "/help"):
            print_help(model, retriever)
            continue

        if query == "/status":
            domains = ", ".join(retriever.domains) if retriever and retriever.packs else "none"
            peer_info = f"   peers: [bold]{len(peers)}[/bold]" if peers else ""
            console.print(
                f"\n  model: [bold]{model}[/bold]   profile: [bold]{cfg.hardware_profile}[/bold]"
                f"   ctx: [bold]{cfg.num_ctx_answer}[/bold]   retrieval: [bold]{cfg.retrieval_chars}[/bold] chars"
                f"\n  domains: [bold]{domains}[/bold]{peer_info}\n"
            )
            continue

        if query == "/clear":
            engine._history.clear()
            engine._last_ctx_used = 0
            engine._peak_ctx_used = 0
            console.print("[dim]Conversation cleared.[/dim]\n")
            continue

        if query == "/packs":
            if retriever and retriever.packs:
                for p in retriever.packs:
                    console.print(f"  [bold cyan]{p.name}[/bold cyan]  {', '.join(p.domains)}")
            else:
                console.print("  No packs loaded.")
            console.print()
            continue

        if query.startswith("/model "):
            new_model = query[7:].strip()
            if not new_model:
                console.print("[red]Usage: /model <name>[/red]\n")
                continue
            model = new_model
            warmup_model(model)
            engine = build_engine(cfg, retriever, model, peers, workspace)
            console.print(f"[dim]Switched to [bold]{model}[/bold][/dim]\n")
            continue

        if query.startswith("/pack "):
            pack_name = query[6:].strip()
            pack_path = ROOT / "expert-packs" / pack_name
            if not pack_path.exists():
                console.print(f"[red]Pack '{pack_name}' not found in expert-packs/[/red]\n")
                continue
            retriever = MultiPackRetriever([load_pack(pack_path)])
            engine = build_engine(cfg, retriever, model, peers, workspace)
            console.print(f"[dim]Loaded pack [bold]{pack_name}[/bold][/dim]\n")
            continue

        if query == "/unload":
            try:
                ollama.chat(
                    model=model,
                    messages=[{"role": "user", "content": ""}],
                    keep_alive=0,
                    options={"num_predict": 0},
                )
                console.print(f"[dim]Model [bold]{model}[/bold] unloaded from VRAM.[/dim]\n")
            except Exception as e:
                console.print(f"[red]Unload failed: {e}[/red]\n")
            continue

        if query == "/load":
            warmup_model(model)
            continue

        if query == "/peers":
            if peers:
                console.print(f"\n  Broker: [bold]wss://broker.opencognitivecommons.org/ws[/bold]")
                from node.server.client import fetch_peer_manifests
                manifests = fetch_peer_manifests()
                if manifests:
                    for nid, info in manifests.items():
                        domains_str = ", ".join(info.get("domains", []))
                        console.print(f"  [bold cyan]{nid}[/bold cyan]  pack: {info.get('pack')}  domains: {domains_str}")
                else:
                    console.print("  [dim]No nodes currently registered.[/dim]")
            else:
                console.print("\n  No broker configured. Set OCC_PEERS=broker to enable.\n")
            console.print()
            continue

        if query.startswith("/"):
            console.print("[red]Unknown command. Type /? for help.[/red]\n")
            continue

        console.print()
        if query.startswith("!"):
            query = query[1:].strip()
            mode = "deliberate"
        else:
            mode = classify(model, query)
        answer = _stream_answer(engine, query, mode)
        if answer:
            engine.add_to_history(query, answer)
        console.print()


def _print_ctx_usage(engine):
    limit = engine._ctx_limit
    if not limit or not engine._peak_ctx_used:
        return
    pct = engine._peak_ctx_used / limit * 100
    bar_len = 20
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
    console.print(
        f"  [dim]ctx [{color}]{bar}[/{color}] {engine._peak_ctx_used:,} / {limit:,} tokens ({pct:.1f}%)[/dim]"
    )


_ROUTING_LABELS = {
    "chat":     "[dim cyan]chat[/dim cyan]",
    "local":    "[dim green]local[/dim green]",
    "delegate": "[dim magenta]distributed[/dim magenta]",
    "hybrid":   "[dim blue]hybrid[/dim blue]",
}


def _stream_answer(engine: DeliberationEngine, query: str, mode: str = "deliberate") -> str:
    tokens: list[str] = []
    peer_data: dict | None = None
    routing_mode: str = ""

    with Live(console=console, refresh_per_second=15, transient=True) as live:
        for kind, value in engine.route_stream(query, mode):
            if kind == "routing":
                routing_mode = value
                live.update(Text(f"  {value}", style="dim"))
            elif kind == "status":
                live.update(Text.assemble(("  ◈ ", "yellow"), (value, "dim yellow")))
            elif kind == "token":
                tokens.append(value)
                live.update(Text.assemble(("  ◈ ", "yellow"), ("writing...", "dim yellow")))
            elif kind == "peer_answers":
                peer_data = value

    answer = "".join(tokens).strip()
    if answer:
        subtitle = _ROUTING_LABELS.get(routing_mode) if routing_mode else None
        console.print(
            Panel(
                Markdown(answer),
                title="[bold green]OCC[/bold green]",
                subtitle=subtitle,
                border_style="green",
            )
        )
        if peer_data:
            _write_deliberation_log(query, peer_data, answer)
        _print_ctx_usage(engine)
    else:
        console.print("[red]No response generated. Check that Ollama is running.[/red]")
    return answer


def _write_deliberation_log(query: str, peer_data: dict, final_answer: str):
    from datetime import datetime
    log_path = ROOT / "deliberation_log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    routing_mode = peer_data.get("mode", "delegate")

    sections = [
        f"\n---\n\n",
        f"## [{timestamp}] — {routing_mode}\n\n",
        f"**Query:** {query}\n\n",
    ]

    if routing_mode == "hybrid":
        local_pack = peer_data.get("local_pack", "local")
        local_answer = peer_data.get("local_answer") or "_(no answer)_"
        sections.append(f"### Node A — Local [{local_pack}]\n\n{local_answer}\n\n")

    expert_peer = peer_data.get("expert_peer", "")
    expert_answer = peer_data.get("expert_answer") or "_(no answer)_"
    if expert_peer:
        sections.append(f"### Peer Expert ({expert_peer})\n\n{expert_answer}\n\n")

    contrarian_peer = peer_data.get("contrarian_peer", "")
    contrarian_answer = peer_data.get("contrarian_answer", "")
    if contrarian_peer and contrarian_answer:
        label = "Peer Expert 2" if routing_mode in ("delegate", "hybrid") else "Peer Contrarian"
        sections.append(f"### {label} ({contrarian_peer})\n\n{contrarian_answer}\n\n")

    sections.append(f"### Synthesized Answer\n\n{final_answer}\n")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("".join(sections))
    console.print("[dim]  Log saved → deliberation_log.md[/dim]\n")


if __name__ == "__main__":
    run()
