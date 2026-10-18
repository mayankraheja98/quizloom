"""
Paragraph-level text extraction from PDF and DOCX files.

Strategy:
  - PDF: extract per-page text, split on blank lines, merge fragments
    shorter than MIN_CHARS into adjacent paragraphs, cap at MAX_CHARS.
  - DOCX: group non-empty paragraph runs separated by blank paragraphs.
"""

import re
import pdfplumber
from pathlib import Path

MIN_CHARS = 150   # discard very short fragments
MAX_CHARS = 2500  # cap chunk size sent to LLM


def _split_long(text: str) -> list[str]:
    """Split text > MAX_CHARS at sentence boundaries instead of truncating it."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sent) + 1 > MAX_CHARS:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return [p[:MAX_CHARS] for p in parts]


def _merge_and_filter(raw: list[str]) -> list[str]:
    """Merge short fragments into neighbours; drop tiny leftovers."""
    merged: list[str] = []
    buf = ""
    for p in raw:
        p = p.strip()
        if not p:
            continue
        if buf:
            buf += " " + p
        else:
            buf = p
        if len(buf) >= MIN_CHARS:
            merged.extend(_split_long(buf))
            buf = ""
    if buf and len(buf) >= MIN_CHARS:
        merged.extend(_split_long(buf))
    return merged


def extract_paragraphs_from_pdf(file_path: str) -> list[str]:
    raw: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if not text:
                continue
            # split on one or more blank lines
            chunks = re.split(r"\n[ \t]*\n+", text)
            for chunk in chunks:
                # normalise internal newlines (soft wraps) → spaces
                chunk = re.sub(r"\n", " ", chunk).strip()
                chunk = re.sub(r"\s{2,}", " ", chunk)
                if chunk:
                    raw.append(chunk)
    return _merge_and_filter(raw)


def extract_paragraphs_from_docx(file_path: str) -> list[str]:
    from docx import Document  # lazy import — optional dependency

    doc = Document(file_path)
    raw = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    return _merge_and_filter(raw)


def extract_paragraphs_from_txt(file_path: str) -> list[str]:
    """
    Split plain-text notes into paragraphs.
    Blank lines are paragraph separators; indented / bullet lines are kept inline.
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    # normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # split on one or more blank lines
    chunks = re.split(r"\n[ \t]*\n+", text)
    raw: list[str] = []
    for chunk in chunks:
        # collapse internal newlines (soft-wrapped lines) into spaces
        chunk = re.sub(r"\n", " ", chunk).strip()
        chunk = re.sub(r"\s{2,}", " ", chunk)
        if chunk:
            raw.append(chunk)
    return _merge_and_filter(raw)


def extract_paragraphs(file_path: str) -> list[str]:
    """Dispatch based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_paragraphs_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return extract_paragraphs_from_docx(file_path)
    elif ext == ".txt":
        return extract_paragraphs_from_txt(file_path)
    raise ValueError(f"Unsupported file type: {ext}")
