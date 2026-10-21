"""
Fetch and extract plain text from a Notion page via the Notion API.

Requirements:
  - A Notion internal integration token (notion.so/my-integrations)
  - The integration must be shared with the page (page → … → Connections)

Flow:
  1. check_page()          — fast access check + title (safe to run inside a request)
  2. collect_blocks()      — slow: walk the block tree, capped at MAX_PAGES (run in background)
  3. blocks_to_paragraphs() — turn blocks into paragraph-sized chunks; optionally
                              transcribe images through a vision model (`describe`).
"""

import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

import httpx

SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() not in ("0", "false", "no")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT = 30.0

# Block types whose `rich_text` carries readable text
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item",
    "quote", "callout", "toggle", "to_do",
    "code",
}

MIN_CHARS = 60      # drop only pure noise
TARGET_CHARS = 1500  # flush a chunk once it reaches this size
MAX_CHARS = 2500    # cap chunk size sent to LLM

MAX_PAGES = int(os.getenv("NOTION_MAX_PAGES", "50"))  # root page + sub-pages followed
MAX_IMAGES = 15                       # per page, to respect free-tier rate limits
MAX_IMAGE_BYTES = 4 * 1024 * 1024
_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _parse_page_id(url_or_id: str) -> str:
    """
    Extract a Notion page ID (32-char hex, optionally hyphenated) from a full URL,
    short URL, slug (Title-abc123...), bare UUID or bare hex ID.
    """
    url_or_id = url_or_id.split("?")[0].split("#")[0].strip()
    segment = url_or_id.rstrip("/").split("/")[-1]

    parts = segment.split("-")
    candidate = parts[-1] if len(parts) > 1 else segment
    for cand in (candidate, segment):
        hex_id = cand.replace("-", "")
        if re.fullmatch(r"[0-9a-fA-F]{32}", hex_id):
            return f"{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"

    raise ValueError(
        f"Could not extract a valid Notion page ID from: {url_or_id!r}. "
        "Make sure you paste the full Notion page URL."
    )


def _rich_text_to_str(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _block_text(block: dict) -> str:
    """Readable text of a block (images handled separately: caption only here)."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    if btype in _TEXT_BLOCK_TYPES:
        return _rich_text_to_str(content.get("rich_text", []))
    if btype == "table_row":
        return " | ".join(_rich_text_to_str(cell) for cell in content.get("cells", []))
    if btype == "equation":
        return content.get("expression", "")
    if btype == "child_page":
        return content.get("title", "")
    if btype == "image":
        return _rich_text_to_str(content.get("caption", []))
    return ""


def _image_url(block: dict) -> str | None:
    img = block.get("image", {})
    return img.get(img.get("type", ""), {}).get("url")


# ── Notion API ────────────────────────────────────────────────────────────────

async def _fetch_blocks(page_id: str, headers: dict, cursor: str | None = None) -> dict:
    params = {"page_size": 100}
    if cursor:
        params["start_cursor"] = cursor
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY) as client:
        for attempt in range(4):
            r = await client.get(
                f"{NOTION_API_BASE}/blocks/{page_id}/children", headers=headers, params=params
            )
            if r.status_code == 429 and attempt < 3:  # Notion rate limit (~3 req/s)
                await asyncio.sleep(min(float(r.headers.get("Retry-After", "1")), 10))
                continue
            r.raise_for_status()
            return r.json()


async def _collect_blocks(page_id: str, headers: dict, state: dict) -> list[dict]:
    """Recursively collect blocks under page_id (pagination handled); sub-pages capped."""
    blocks: list[dict] = []
    cursor = None
    while True:
        data = await _fetch_blocks(page_id, headers, cursor)
        for block in data.get("results", []):
            blocks.append(block)
            if block.get("has_children"):  # toggles, columns, sub-pages, ...
                if block.get("type") == "child_page":
                    if state["pages_read"] >= MAX_PAGES:
                        state["pages_skipped"] += 1
                        continue
                    state["pages_read"] += 1
                blocks.extend(await _collect_blocks(block["id"], headers, state))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return blocks


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def check_page(page_url: str, api_key: str) -> tuple[str, str]:
    """
    Fast access check. Returns (page_id, title). Raises ValueError for bad URL / auth /
    sharing problems, httpx.HTTPStatusError for other API errors.
    """
    page_id = _parse_page_id(page_url)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY) as client:
        r = await client.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(api_key))
        if r.status_code == 404:
            raise ValueError(
                "Notion page not found. Check the URL and make sure the integration "
                "is shared with this page (page → … → Connections)."
            )
        if r.status_code == 401:
            raise ValueError("Invalid Notion API key.")
        if r.status_code == 403:
            raise ValueError(
                "Access denied. Share the page with your Notion integration: "
                "open the page → … → Connections → add your integration."
            )
        r.raise_for_status()

    title = ""
    for prop in r.json().get("properties", {}).values():
        if prop.get("type") == "title":
            title = _rich_text_to_str(prop.get("title", []))
            break
    return page_id, title or page_id


async def collect_blocks(page_id: str, api_key: str) -> tuple[list[dict], dict]:
    """Slow part. Returns (blocks, {"pages_read", "pages_skipped"}); root page counts as 1."""
    state = {"pages_read": 1, "pages_skipped": 0}
    blocks = await _collect_blocks(page_id, _headers(api_key), state)
    return blocks, state


def count_images(blocks: list[dict]) -> int:
    return sum(1 for b in blocks if b.get("type") == "image" and _image_url(b))


# ── Image download (SSRF-guarded) ─────────────────────────────────────────────

def _is_public_https(url: str) -> bool:
    """Only https, and only hosts that resolve to public IPs (blocks internal targets)."""
    try:
        u = urlparse(url)
        if u.scheme != "https" or not u.hostname:
            return False
        for info in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False
        return True
    except Exception:
        return False


async def _download_image(url: str) -> tuple[bytes, str]:
    """Fetch image bytes. Raises ValueError with a human-readable reason on any problem."""
    ok = await asyncio.get_running_loop().run_in_executor(None, _is_public_https, url)
    if not ok:
        raise ValueError("image URL rejected (not https or not a public host)")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY) as client:
        r = await client.get(url)  # redirects not followed (httpx default)
    if r.status_code != 200:
        raise ValueError(f"image download returned HTTP {r.status_code}")
    if len(r.content) > MAX_IMAGE_BYTES:
        raise ValueError(f"image larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in _IMAGE_MIMES:
        raise ValueError(f"unsupported image type '{mime}'")
    return r.content, mime


# ── Blocks → paragraphs ───────────────────────────────────────────────────────

async def blocks_to_paragraphs(blocks: list[dict], describe=None) -> tuple[list[str], dict]:
    """
    Group consecutive text lines into chunks of about TARGET_CHARS. Headings flush the buffer.
    `describe(image_bytes, mime) -> str` (async) transcribes images; if None images contribute
    their caption only. Returns (paragraphs, stats).
    """
    stats = {"images_found": 0, "images_read": 0, "images_failed": 0, "images_empty": 0, "image_errors": []}
    paragraphs: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            combined = " ".join(buf).strip()
            if len(combined) >= MIN_CHARS:
                paragraphs.append(combined[:MAX_CHARS])
            buf.clear()

    for block in blocks:
        btype = block.get("type", "")
        text = _block_text(block).strip()

        if btype == "image":
            url = _image_url(block)
            if url:
                stats["images_found"] += 1
            if describe and url and stats["images_read"] + stats["images_failed"] + stats["images_empty"] < MAX_IMAGES:
                try:
                    desc = (await describe(*await _download_image(url))).strip()
                    if desc:
                        text = f"[Image] {text} {desc}".strip()
                        stats["images_read"] += 1
                    else:  # model judged it decorative / no informational content
                        stats["images_empty"] += 1
                except Exception as e:
                    stats["images_failed"] += 1
                    if len(stats["image_errors"]) < 3:
                        stats["image_errors"].append(f"{type(e).__name__}: {e}"[:250])
            if text:
                flush()
                buf.append(text)
                flush()
            continue

        if not text:
            continue
        if btype.startswith("heading_") or btype == "child_page":
            flush()
            buf.append(text)
        else:
            buf.append(text)
            if len(" ".join(buf)) >= TARGET_CHARS:
                flush()

    flush()
    return paragraphs, stats


async def extract_paragraphs_from_notion(page_url: str, api_key: str) -> tuple[str, list[str]]:
    """Text-only convenience wrapper (kept for backward compatibility)."""
    page_id, title = await check_page(page_url, api_key)
    blocks, _ = await collect_blocks(page_id, api_key)
    paragraphs, _ = await blocks_to_paragraphs(blocks)
    return title, paragraphs
