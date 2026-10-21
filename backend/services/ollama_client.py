"""
Unified LLM client supporting:
  - ollama   (local, free)
  - groq     (cloud, free tier — console.groq.com)
  - gemini   (cloud, free tier — aistudio.google.com)

Groq and Gemini both expose an OpenAI-compatible /chat/completions endpoint,
so a single _call_openai_compat() function handles both.
"""

import asyncio
import json
import os
import re
import httpx

# ── Config ─────────────────────────────────────────────────────────────────────

# Behind a TLS-intercepting corporate proxy, set SSL_VERIFY=false (quick, insecure)
# or mount the corporate root CA and set SSL_CERT_FILE=/path/ca.pem (proper fix).
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() not in ("0", "false", "no")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = "llama3"
OLLAMA_TIMEOUT = 600.0   # CPU inference is slow

PROVIDER_CONFIGS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "timeout": 120.0,
        "suggested_models": [
            "llama-3.1-8b-instant",     # fastest, free
            "llama-3.3-70b-versatile",  # best quality, free
            "gemma2-9b-it",             # Google model via Groq
            "mixtral-8x7b-32768",       # long context
        ],
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "timeout": 120.0,
        "suggested_models": [
            "gemini-3.8-flash",         # suggested by Google's API after 2.0 was retired
            # Model names churn; if one 404s, copy a current name from aistudio.google.com
        ],
    },
}

# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an expert exam question writer for professional certifications "
    "such as CISSP, CIPP/E, CISA, and similar. "
    "You write clear, unambiguous multiple-choice questions that test "
    "conceptual understanding, not mere memorisation."
)

_STYLES = {
    "conceptual": "Write DIRECT conceptual questions: definitions, principles, rules, requirements, "
                  "processes and distinctions between related concepts.",
    "scenario": "Write SCENARIO-BASED questions: a short, realistic situation (2-4 sentences) followed by a "
                "question asking which principle, rule or action applies. Invent fresh scenarios; do not "
                "copy the text's own example.",
    "mixed": "Mix the two styles: roughly half direct conceptual questions (definitions, rules, "
             "distinctions) and half short scenario-based questions that apply a concept to a NEW situation.",
}

_USER_TEMPLATE = """\
Write {n} multiple-choice question(s) that test UNDERSTANDING of the concepts in the study material below.
{style}
{focus_block}
WHAT TO TEST:
- The underlying concept, principle, rule, definition, process or distinction the material teaches.
- Illustrations, case studies, anecdotes, named people/companies and sample figures in the material exist \
only to explain a concept. Do NOT ask what happened in an example, and do NOT ask for incidental details \
(names, places, amounts, dates, statistics) unless that detail is itself a rule or requirement the learner \
must know (for example a legal deadline or threshold).
- If the material gives an example, you may reuse its idea as a scenario that asks the learner to APPLY the \
concept to a similar but different situation.

QUALITY RULES:
1. Each question must make sense on its own: never write "according to the text/passage/example".
2. Exactly 4 options labelled A, B, C, D, exactly one correct. Wrong options must be plausible \
misconceptions, not obviously absurd.
3. Cover DISTINCT concepts; never repeat a question.
4. Include a brief explanation of why the correct answer is right (and, if useful, why a tempting option is wrong).
5. If the material contains NO testable concept (only an anecdote, introduction, agenda or administrative \
text), return an empty array [].
6. Return ONLY JSON: an array (or an object wrapping the array) — no prose, no markdown, no code fences.

MATERIAL:
{text}

JSON schema (array of objects):
[
  {{
    "question": "<question text>",
    "options": {{"A": "<text>", "B": "<text>", "C": "<text>", "D": "<text>"}},
    "answer": "<A|B|C|D>",
    "explanation": "<why the answer is correct>"
  }}
]"""

_TOPIC_TEMPLATE = """\
Using your knowledge of the following topic, generate exactly {n} multiple-choice \
questions suitable for a professional certification exam (e.g. CISSP, CIPP/E, CISA).

TOPIC: {topic}

Rules:
1. Each question must have exactly 4 options labelled A, B, C, D.
2. Exactly one option is correct.
3. Questions should test conceptual understanding and applied judgment, not trivia.
4. Vary difficulty: include some straightforward and some scenario-based questions.
5. Include a brief explanation for the correct answer.
6. Return ONLY a JSON array — no prose, no markdown, no code fences.

JSON schema (array of objects):
[
  {{
    "question": "<question text>",
    "options": {{"A": "<text>", "B": "<text>", "C": "<text>", "D": "<text>"}},
    "answer": "<A|B|C|D>",
    "explanation": "<why the answer is correct>"
  }}
]"""

# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse_response(raw: str, strict: bool = False) -> list[dict]:
    """strict=True raises ValueError on unparsable output (so '[]' can mean 'nothing to ask')."""
    bad = (lambda: (_ for _ in ()).throw(ValueError("Model output was not valid JSON"))) if strict else (lambda: [])
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return bad()
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return bad()
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for val in parsed.values():
            if isinstance(val, list):
                return val
    return bad()


def _validate(q: dict) -> bool:
    required = {"question", "options", "answer", "explanation"}
    if not required.issubset(q.keys()):
        return False
    if not isinstance(q["options"], dict):
        return False
    if set(q["options"].keys()) != {"A", "B", "C", "D"}:
        return False
    if q["answer"] not in {"A", "B", "C", "D"}:
        return False
    return bool(q["question"].strip())

# ── Low-level callers ──────────────────────────────────────────────────────────

async def _call_ollama(prompt: str, model: str) -> str:
    full_prompt = f"{_SYSTEM_PROMPT}\n\n{prompt}"
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": full_prompt, "stream": False, "format": "json"},
        )
        r.raise_for_status()
    return r.json().get("response", "")


async def _call_openai_compat(
    prompt: str, model: str, base_url: str, api_key: str, timeout: float
) -> str:
    """Handles Groq, Gemini, and any other OpenAI-compatible endpoint (retries on 429)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        # JSON mode — supported by Groq and Gemini
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout, verify=SSL_VERIFY) as client:
        for attempt in range(3):
            r = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            if r.status_code == 429 and attempt < 2:  # free-tier rate limit: wait, then retry
                try:
                    delay = float(r.headers.get("Retry-After", "")) 
                except ValueError:
                    delay = 10.0 * (attempt + 1)
                await asyncio.sleep(min(delay, 30.0))
                continue
            r.raise_for_status()
            break
    return r.json()["choices"][0]["message"]["content"]


async def _call_llm(
    prompt: str,
    provider: str,
    model: str,
    api_key: str | None = None,
) -> str:
    if provider == "ollama":
        return await _call_ollama(prompt, model)
    cfg = PROVIDER_CONFIGS.get(provider)
    if not cfg:
        raise ValueError(f"Unknown provider '{provider}'. Choose: ollama, groq, gemini")
    if not api_key:
        raise ValueError(f"API key required for provider '{provider}'")
    return await _call_openai_compat(prompt, model, cfg["base_url"], api_key, cfg["timeout"])

# ── Public API ─────────────────────────────────────────────────────────────────

async def generate_questions(
    text: str,
    n: int = 2,
    model: str = DEFAULT_MODEL,
    provider: str = "ollama",
    api_key: str | None = None,
    style: str = "mixed",
    focus: str = "",
) -> list[dict]:
    """[] means the model found nothing testable; raises ValueError on malformed output."""
    focus = " ".join(focus.split())[:500]
    focus_block = (
        "\nLEARNER'S CONTEXT (from the person who uploaded this material):\n"
        f"<<<{focus}>>>\n"
        "Use it IN ADDITION to your own analysis of the material: still identify the key concepts the "
        "material teaches, and also make sure concepts related to the learner's topics are covered and "
        "given priority. Use the context to interpret terminology and decide what matters. Concepts in the "
        "material that are not covered by the learner's topics are still fair game. Base every question on "
        "the material itself (never invent facts it does not support).\n"
        if focus else ""
    )
    prompt = _USER_TEMPLATE.format(
        n=n, text=text, style=_STYLES.get(style, _STYLES["mixed"]), focus_block=focus_block
    )
    raw = await _call_llm(prompt, provider, model, api_key)
    parsed = _parse_response(raw, strict=True)
    valid = [q for q in parsed if _validate(q)]
    if parsed and not valid:
        raise ValueError("Model returned malformed questions")
    return valid


async def generate_questions_from_topic(
    topic: str,
    n: int = 5,
    model: str = DEFAULT_MODEL,
    provider: str = "ollama",
    api_key: str | None = None,
) -> list[dict]:
    raw = await _call_llm(_TOPIC_TEMPLATE.format(n=n, topic=topic), provider, model, api_key)
    return [q for q in _parse_response(raw) if _validate(q)]


_VISION_PROMPT = (
    "This image is from study notes for a professional certification exam. Transcribe all "
    "text in it and describe any diagram, chart, table or figure factually and in enough "
    "detail that exam questions could be written from your description alone. "
    "If the image has no informational content (logo, decoration, plain photo), reply with "
    "exactly: NONE"
)


async def describe_image(image: bytes, mime: str, model: str, api_key: str) -> str:
    """Transcribe/describe an image via Gemini's OpenAI-compatible endpoint. '' if no content."""
    import base64
    cfg = PROVIDER_CONFIGS["gemini"]
    data_uri = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    payload = {
        "model": model,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]}],
    }
    async with httpx.AsyncClient(timeout=cfg["timeout"], verify=SSL_VERIFY) as client:
        for attempt in range(3):
            r = await client.post(
                f"{cfg['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if r.status_code == 429 and attempt < 2:
                # Per-minute limits clear quickly; honour the suggested delay if it is short
                m = re.search(r"retry in ([\d.]+)s|\"retryDelay\":\s*\"([\d.]+)s\"", r.text)
                delay = float(m.group(1) or m.group(2)) if m else 15.0
                if delay > 45:
                    break  # daily/zero quota: waiting won't help
                await asyncio.sleep(delay + 1)
                continue
            break
    if r.status_code == 429:
        raise RuntimeError(
            "Gemini quota exceeded for this model/key (429). Try another model, wait for the quota "
            "to reset, or check usage at aistudio.google.com. Details: " + r.text[:150]
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini vision returned {r.status_code}: {r.text[:200]}")
    out = (r.json()["choices"][0]["message"].get("content") or "").strip()
    return "" if out.upper().startswith("NONE") else out


async def probe_provider(
    provider: str,
    model: str,
    api_key: str | None = None,
) -> str | None:
    """Return None if the provider+model works, else a human-readable reason."""
    if provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                r.raise_for_status()
                full_names = {t.get("name", "") for t in r.json().get("models", [])}
                prefix_names = {n.split(":")[0] for n in full_names}
                if model in full_names or model.split(":")[0] in prefix_names:
                    return None
                return f"Ollama model '{model}' not found. Run: ollama pull {model}"
        except Exception as e:
            return f"Cannot reach Ollama at {OLLAMA_BASE_URL}: {type(e).__name__}"

    cfg = PROVIDER_CONFIGS.get(provider)
    if not cfg:
        return f"Unknown provider '{provider}'"
    if not api_key:
        return f"API key required for {provider}"
    if not model:
        return "Model name is required"
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=SSL_VERIFY) as client:
            r = await client.post(
                f"{cfg['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            )
    except Exception as e:
        return f"Could not reach {provider} API: {type(e).__name__}: {e}"
    if r.status_code < 400 or r.status_code == 429:  # 429 = key valid, just rate-limited
        return None
    try:
        detail = r.json()
        detail = detail.get("error", detail) if isinstance(detail, dict) else detail
        detail = detail.get("message", detail) if isinstance(detail, dict) else detail
    except Exception:
        detail = r.text[:200]
    return f"{provider} returned {r.status_code}: {detail}"


async def check_provider(provider: str, model: str, api_key: str | None = None) -> bool:
    return await probe_provider(provider, model, api_key) is None


# Backward-compat alias used in upload.py
check_ollama = lambda model=DEFAULT_MODEL: check_provider("ollama", model)
