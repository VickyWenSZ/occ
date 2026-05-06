#!/usr/bin/env python3
"""OCC Forge — Launch with: python forge/app.py"""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

import gradio as gr
import forge._llm as llm
import forge._sources as sources
import forge._wiki as wiki
import forge._manifest as manifest


def run_forge(pack_name, mode, files, urls_text, model_choice):
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        yield "❌ API key missing. Create OCC/.env with OPENAI_API_KEY=sk-..."
        return
    if not pack_name.strip():
        yield "❌ Enter a pack name (e.g. docker, python, git)."
        return

    pack_name = re.sub(r'[^a-z0-9-]', '-', pack_name.strip().lower()).strip('-')
    extract_model = "gpt-5-mini"
    write_model = "gpt-5" if model_choice == "gpt-5 (best quality)" else "gpt-5-mini"

    pack_dir = ROOT / "expert-packs" / pack_name
    wiki_dir = pack_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    rebuild = "Rebuild" in mode
    if rebuild:
        import shutil
        concepts_dir = wiki_dir / "concepts"
        if concepts_dir.exists():
            shutil.rmtree(concepts_dir)
            yield "🗑️ Concepts deleted — starting from scratch."
        log_path = wiki_dir / "log.md"
        if log_path.exists():
            log_path.unlink()
        mf = manifest.load_or_create(pack_dir, pack_name)
        mf["sources"] = []
    else:
        mf = manifest.load_or_create(pack_dir, pack_name)

    wiki.ensure_schema(wiki_dir, pack_name)
    all_pages = wiki.scan_existing_pages(wiki_dir)
    existing_slugs = {p["slug"] for p in all_pages}

    raw_sources = []

    if files:
        for f in files:
            yield f"📂 Reading file: {Path(f).name}..."
            text, name, url = sources.read_file(Path(f))
            raw_sources.append((text, name, url))

    if urls_text and urls_text.strip():
        for url in urls_text.strip().splitlines():
            url = url.strip()
            if not url:
                continue
            yield f"🌐 Fetching: {url}..."
            try:
                text, name, url = sources.fetch_url(url)
                raw_sources.append((text, name, url))
            except Exception as e:
                err = str(e)
                if "403" in err or "401" in err or "406" in err:
                    yield f"⚠️ {url}\n   → Blocked (error {err[:3]}). Try saving the page as a file and drag & drop it."
                else:
                    yield f"❌ Error fetching {url}: {e}"

    if not raw_sources:
        yield "❌ No sources found. Add files or URLs."
        return

    total_written = 0

    for text, source_name, source_url in raw_sources:
        yield f"\n━━━ Source: {source_name} ({len(text):,} chars) ━━━"

        yield f"🔍 Extracting concepts ({extract_model})..."
        concepts = None
        for attempt in range(3):
            try:
                concepts = llm.extract_concepts(text, model=extract_model)
                break
            except Exception as e:
                yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
        if not concepts:
            yield "❌ Concept extraction failed after 3 attempts, skipping source."
            continue

        yield f"💡 Found {len(concepts)} concepts: {', '.join(c.get('title', c.get('slug', '?')) for c in concepts)}"

        written = 0
        for concept in concepts:
            slug = re.sub(r'[^a-z0-9-]', '-', concept.get("slug", "unknown")).strip('-')
            concept["slug"] = slug
            title = concept.get("title", slug)

            existing_path = wiki_dir / "concepts" / f"{slug}.md"
            if existing_path.exists():
                yield f"✍️  Enriching: {title} (page already exists)..."
                existing_content = existing_path.read_text(encoding="utf-8")
                page_content = None
                for attempt in range(3):
                    try:
                        page_content = llm.update_wiki_page(concept, existing_content, text, source_name, model=write_model)
                        break
                    except Exception as e:
                        yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
            else:
                yield f"✍️  Writing: {title}..."
                page_content = None
                for attempt in range(3):
                    try:
                        page_content = llm.write_wiki_page(concept, text, source_name, model=write_model)
                        break
                    except Exception as e:
                        yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
            if not page_content:
                yield f"❌ '{title}' failed after 3 attempts, skipping."
                continue

            if page_content.strip():
                wiki.write_page(wiki_dir, slug, page_content)
                entry = {"slug": slug, "title": title, "summary": concept.get("summary", "")}
                if slug not in existing_slugs:
                    all_pages.append(entry)
                    existing_slugs.add(slug)
                else:
                    for p in all_pages:
                        if p["slug"] == slug:
                            p.update(entry)
                            break
                written += 1
                total_written += 1
                yield f"  ✅ {title} → concepts/{slug}.md"
            else:
                yield f"  ⚠️ {title}: empty response"

        manifest.add_source(mf, source_url, sources.sha256(text))
        wiki.append_log(wiki_dir, source_name, written, source_url)

    wiki.update_index(wiki_dir, all_pages)
    manifest.save(pack_dir, mf)

    yield f"\n🎉 Done! {total_written} pages written to expert-packs/{pack_name}/wiki/concepts/"
    yield f"📋 Index updated: {len(all_pages)} total pages in pack."


def load_existing_sources(pack_name: str) -> str:
    pack_name = re.sub(r'[^a-z0-9-]', '-', pack_name.strip().lower()).strip('-')
    if not pack_name:
        return ""
    manifest_path = ROOT / "expert-packs" / pack_name / "manifest.yaml"
    if not manifest_path.exists():
        return "_Pack does not exist yet — will be created on first run._"
    try:
        import yaml
        with open(manifest_path, encoding="utf-8") as f:
            mf = yaml.safe_load(f) or {}
        srcs = mf.get("sources", [])
        if not srcs:
            return "_No sources ingested yet._"
        lines = [f"**Pack `{pack_name}`** — {len(srcs)} source(s):\n"]
        for s in srcs:
            lines.append(f"- `{s.get('fetched', '?')}` — {s.get('url', '?')}")
        return "\n".join(lines)
    except Exception as e:
        return f"_Error reading manifest: {e}_"


def build_ui():
    with gr.Blocks(title="OCC Forge") as app:
        import os
        key = os.environ.get("OPENAI_API_KEY", "")
        key_status = f"✅ API key loaded (`{key[:12]}...`)" if key else "❌ API key not found — create `OCC/.env` with `OPENAI_API_KEY=sk-...` (no quotes)"
        gr.Markdown(f"# 🔨 OCC Forge\n{key_status}")

        with gr.Row():
            pack_name = gr.Textbox(
                label="Pack name",
                placeholder="e.g. docker, python, git",
                scale=1,
            )
            model_choice = gr.Radio(
                label="Writing model",
                choices=["gpt-5 (best quality)", "gpt-5-mini (faster)"],
                value="gpt-5 (best quality)",
                scale=2,
            )

        existing_sources = gr.Markdown(value="", label="Sources already in pack")

        pack_name.change(
            fn=load_existing_sources,
            inputs=pack_name,
            outputs=existing_sources,
        )

        mode = gr.Radio(
            label="Mode",
            choices=["➕ Add sources (merge)", "🔄 Rebuild from scratch"],
            value="➕ Add sources (merge)",
        )

        files = gr.File(
            label="Files to ingest (.txt, .md, .pdf) — drag & drop here",
            file_count="multiple",
            file_types=[".txt", ".md", ".pdf"],
        )

        urls = gr.Textbox(
            label="URLs to ingest (one per line)",
            placeholder="https://docs.docker.com/get-started/\nhttps://...",
            lines=4,
        )

        btn = gr.Button("🚀 Run Forge", variant="primary")

        output = gr.Textbox(
            label="Output",
            lines=20,
            interactive=False,
        )

        def collect_and_run(pack_name, mode, files, urls, model_choice):
            result = ""
            for line in run_forge(pack_name, mode, files, urls, model_choice):
                result += line + "\n"
                yield result, load_existing_sources(pack_name)

        btn.click(
            fn=collect_and_run,
            inputs=[pack_name, mode, files, urls, model_choice],
            outputs=[output, existing_sources],
        )

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(inbrowser=True, theme=gr.themes.Soft())
