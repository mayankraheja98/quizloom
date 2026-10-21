"""
Paragraph-level text extraction from PDF and DOCX files.

Strategy:
  - Extract paragraph-like units (PDF: split page text on blank lines; DOCX: each paragraph;
    TXT: blank-line separated), then pack consecutive units into ~TARGET_CHARS windows
    with a small sentence overlap. Short text is merged into neighbours, never dropped.
"""

import re
import pdfplumber
from pathlib import Path

MIN_CHARS = 60        # drop only pure noise (page numbers, stray headers)
TARGET_CHARS = 1800   # aim for windows about this size
MAX_CHARS = 2500      # soft cap on window size sent to the LLM
OVERLAP_CHARS = 250   # trailing context repeated at the start of the next window
_SENT = re.compile(r"(?<=[.!?])\s+")


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


def _tail(text: str) -> str:
    """Last sentence(s) of `text`, up to OVERLAP_CHARS, used as context for the next window."""
    out = ""
    for sent in reversed(_SENT.split(text)):
        if len(out) + len(sent) + 1 > OVERLAP_CHARS:
            break
        out = f"{sent} {out}".strip()
    return out


def _merge_and_filter(raw: list[str]) -> list[str]:
    """Pack paragraph units into ~TARGET_CHARS windows with overlap; merge short leftovers."""
    units: list[str] = []
    for p in raw:
        p = p.strip()
        if p:
            units.extend(_split_long(p))

    windows: list[str] = []
    seed = ""            # overlap carried over from the previous window
    new_parts: list[str] = []   # units added since the last emit

    def current() -> str:
        return " ".join(([seed] if seed else []) + new_parts).strip()

    for u in units:
        if new_parts and len(current()) + 1 + len(u) > MAX_CHARS:
            win = current()
            windows.append(win)
            seed, new_parts = _tail(win), []
        new_parts.append(u)
        if len(current()) >= TARGET_CHARS:
            win = current()
            windows.append(win)
            seed, new_parts = _tail(win), []

    if new_parts:
        new = " ".join(new_parts)
        if windows and len(new) < 400 and len(windows[-1]) + 1 + len(new) <= MAX_CHARS:
            windows[-1] += " " + new            # short tail: merge into previous window
        elif len(current()) >= MIN_CHARS:
            windows.append(current())
    return windows


def extract_paragraphs_from_pdf(
    file_path: str, page_from: int | None = None, page_to: int | None = None
) -> list[str]:
    """Extract paragraphs; optional 1-based inclusive page range. Pages are released one by one."""
    raw: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        n = len(pdf.pages)
        start = (page_from or 1) - 1
        end = min(page_to or n, n)
        if start >= n:
            raise ValueError(f"PDF has only {n} page(s); page range starts at {page_from}.")
        if end <= start:
            raise ValueError("Invalid page range: 'To page' must be >= 'From page'.")
        for i in range(start, end):
            page = pdf.pages[i]
            try:
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
            finally:
                page.flush_cache()  # keep memory flat on big books
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


def extract_paragraphs(
    file_path: str, page_from: int | None = None, page_to: int | None = None
) -> list[str]:
    """Dispatch based on file extension (page range applies to PDFs only)."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return extract_paragraphs_from_pdf(file_path, page_from, page_to)
    elif ext in (".docx", ".doc"):
        return extract_paragraphs_from_docx(file_path)
    elif ext == ".txt":
        return extract_paragraphs_from_txt(file_path)
    raise ValueError(f"Unsupported file type: {ext}")
