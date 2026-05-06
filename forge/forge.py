#!/usr/bin/env python3
"""
OCC Forge — Knowledge Preparation Tool

Ingests files and URLs into an expert pack wiki (Karpathy LLM Wiki pattern).
Calls GPT-5 via OpenAI Responses API. Never uses Chat Completions.

Usage:
    python forge/forge.py <pack> --files doc.pdf notes.md
    python forge/forge.py <pack> --urls https://docs.docker.com/get-started/
    python forge/forge.py <pack> --files a.pdf --urls https://... --model gpt-5
"""
import sys
import re
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.panel import Panel

import forge._llm as llm
import forge._sources as sources
import forge._wiki as wiki
import forge._manifest as manifest

console = Console()


def run(
    pack_name: str,
    file_paths: list[Path],
    urls: list[str],
    extract_model: str,
    write_model: str,
):
    pack_dir = ROOT / "expert-packs" / pack_name
    wiki_dir = pack_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold cyan]OCC Forge[/bold cyan]\n"
        f"Pack:    [yellow]{pack_name}[/yellow]\n"
        f"Extract: [green]{extract_model}[/green]  (concept identification)\n"
        f"Write:   [green]{write_model}[/green]  (wiki page authoring)",
        expand=False,
    ))

    mf = manifest.load_or_create(pack_dir, pack_name)
    wiki.ensure_schema(wiki_dir, pack_name)

    # Load existing pages so index stays complete across runs
    all_pages = wiki.scan_existing_pages(wiki_dir)
    existing_slugs = {p["slug"] for p in all_pages}

    raw_sources: list[tuple[str, str, str]] = []
    for fp in file_paths:
        raw_sources.append(sources.read_file(fp))
    for url in urls:
        console.print(f"[dim]Fetching {url}...[/dim]")
        raw_sources.append(sources.fetch_url(url))

    for text, source_name, source_url in raw_sources:
        console.print(f"\n[bold]▶ Source:[/bold] {source_name}  ({len(text):,} chars)")

        # Step 1: identify concepts
        console.print(f"  [dim]Extracting concepts ({extract_model})...[/dim]", end=" ")
        concepts = llm.extract_concepts(text, model=extract_model)
        if not concepts:
            console.print("[yellow]no concepts found, skipping.[/yellow]")
            continue
        console.print(f"[cyan]{len(concepts)} concepts[/cyan]")
        for c in concepts:
            console.print(f"    • {c.get('title', c.get('slug', '?'))}")

        # Step 2: write a wiki page for each concept
        written = 0
        new_pages: list[dict] = []
        for concept in concepts:
            slug = re.sub(r'[^a-z0-9-]', '-', concept.get("slug", "unknown")).strip('-')
            concept["slug"] = slug
            title = concept.get("title", slug)

            console.print(f"  → [dim]{title}[/dim]... ", end="")
            page_content = llm.write_wiki_page(concept, text, source_name, model=write_model)

            if page_content.strip():
                wiki.write_page(wiki_dir, slug, page_content)
                entry = {"slug": slug, "title": title, "summary": concept.get("summary", "")}
                new_pages.append(entry)
                if slug not in existing_slugs:
                    all_pages.append(entry)
                    existing_slugs.add(slug)
                else:
                    # Update existing entry summary in all_pages
                    for p in all_pages:
                        if p["slug"] == slug:
                            p.update(entry)
                            break
                written += 1
                console.print("[green]✓[/green]")
            else:
                console.print("[red]✗ empty response[/red]")

        # Update manifest and log for this source
        content_hash = sources.sha256(text)
        manifest.add_source(mf, source_url, content_hash)
        wiki.append_log(wiki_dir, source_name, written, source_url)
        console.print(f"  [dim]Logged: {written}/{len(concepts)} pages written[/dim]")

    # Rebuild index with all pages (existing + new)
    wiki.update_index(wiki_dir, all_pages)
    manifest.save(pack_dir, mf)

    console.print(Panel(
        f"[bold green]Done![/bold green]  "
        f"[cyan]expert-packs/{pack_name}/wiki/[/cyan]\n"
        f"Total pages in index: {len(all_pages)}",
        expand=False,
    ))


def main():
    parser = argparse.ArgumentParser(
        prog="forge",
        description="OCC Forge — build expert pack wiki from files and URLs",
    )
    parser.add_argument("pack", help="Pack name (e.g. docker, python, git)")
    parser.add_argument("--files", nargs="*", default=[], metavar="FILE",
                        help=".txt / .md / .pdf files to ingest")
    parser.add_argument("--urls", nargs="*", default=[], metavar="URL",
                        help="URLs to fetch and ingest")
    parser.add_argument("--model", default=None, metavar="MODEL",
                        help="Use this model for both extract and write steps")
    parser.add_argument("--extract-model", default=llm.DEFAULT_EXTRACT_MODEL,
                        metavar="MODEL")
    parser.add_argument("--write-model", default=llm.DEFAULT_WRITE_MODEL,
                        metavar="MODEL")
    args = parser.parse_args()

    if not args.files and not args.urls:
        parser.error("Provide at least one --files or --urls argument.")

    extract_model = args.model or args.extract_model
    write_model = args.model or args.write_model

    file_paths = [Path(f) for f in args.files]
    for fp in file_paths:
        if not fp.exists():
            console.print(f"[red]File not found: {fp}[/red]")
            sys.exit(1)

    run(args.pack, file_paths, args.urls, extract_model, write_model)


if __name__ == "__main__":
    main()
