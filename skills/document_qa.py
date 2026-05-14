"""
document_qa — read every binary file the user has uploaded in this chat
session and assemble their content as grounded context for the user's
question.

Why this is a skill, not just letting Qwen call read_pdf/read_docx/...
individually: Qwen 9B sometimes reads only one file when several are
relevant, or asks the user "which file?" instead of just reading them all.
This skill removes that ambiguity — when invoked, it guarantees every
uploaded binary is read and presented to the model in one shot.
"""
from pathlib import Path

from node.deliberation.skills import Skill
from node.deliberation.tools import (
    list_upload_files,
    read_pdf,
    read_docx,
    read_xlsx,
    transcribe_audio,
)


_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def _read_one(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return read_pdf(filename)
    if ext == ".docx":
        return read_docx(filename)
    if ext == ".xlsx":
        return read_xlsx(filename)
    if ext in _AUDIO_EXTS:
        return transcribe_audio(filename)
    return f"(unsupported file type: {ext})"


class DocumentQASkill(Skill):
    name = "document_qa"
    description = (
        "Read ALL files the user has uploaded in this chat (PDFs, Word, "
        "Excel, audio) and gather their full content as grounded context "
        "for answering the user's question. Use when the user asks a "
        "question that may span multiple uploaded files, or when you want "
        "to guarantee that every relevant document is consulted before "
        "answering. Prefer this over calling read_pdf / read_docx / "
        "read_xlsx / transcribe_audio individually whenever the user is "
        "asking about their attached files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The user's question to answer using the uploaded files",
            },
        },
        "required": ["question"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        question = (args or {}).get("question", "").strip()
        if not question:
            yield ("result", "document_qa: missing 'question' argument.")
            return

        files = list_upload_files()
        if not files:
            yield ("result",
                "document_qa: no files in the upload folder. Tell the user "
                "they need to attach a file (PDF / Word / Excel / audio) "
                "before asking questions about it."
            )
            return

        sections = []
        skipped = []
        readable = [
            f for f in files
            if Path(f).suffix.lower() in {".pdf", ".docx", ".xlsx", *_AUDIO_EXTS}
        ]
        for i, fname in enumerate(files, 1):
            ext = Path(fname).suffix.lower()
            if ext not in {".pdf", ".docx", ".xlsx", *_AUDIO_EXTS}:
                skipped.append(fname)
                continue
            yield ("status", f"Reading {fname} ({len(sections) + 1} of {len(readable)})...")
            content = _read_one(fname)
            sections.append(f"=== {fname} ===\n{content.strip()}")

        if not sections:
            yield ("result",
                "document_qa: no readable files in upload folder "
                f"(skipped: {', '.join(skipped) or 'none'}). Tell the user "
                "to attach PDF, Word, Excel, or audio."
            )
            return

        skip_note = (
            f"\n\n(Skipped non-binary files: {', '.join(skipped)})"
            if skipped else ""
        )
        yield ("status", "Composing grounded answer...")
        yield ("result",
            f"Question: {question}\n\n"
            f"Contents of all {len(sections)} uploaded file(s):\n\n"
            + "\n\n".join(sections)
            + skip_note
            + "\n\nNow answer the user's question using ONLY the content "
            "above. Cite which file(s) each piece of your answer comes from. "
            "If the question can't be answered from these files, say so "
            "explicitly instead of inventing."
        )


SKILL = DocumentQASkill()
