"""
POST /upload                       — ingest a PDF/DOCX, generate questions, store in DB.
POST /upload/generate-from-topic   — generate questions from model knowledge (no file).
GET  /upload/status/{label_name}   — poll question count for a label.
GET  /upload/providers             — list available providers and their suggested models.

Both generation endpoints accept a `provider` field: ollama | groq | gemini.
Cloud providers (groq, gemini) require an `api_key`.
"""

import logging
import os
import tempfile
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import Label, Question, User
from services.auth import forbid_demo, get_current_user
from services.ratelimit import user_limit
from services.pdf_parser import extract_paragraphs
from services.notion_client import check_page, collect_blocks, blocks_to_paragraphs
from services.ollama_client import (
    generate_questions,
    generate_questions_from_topic,
    describe_image,
    probe_provider,
    PROVIDER_CONFIGS,
)

router = APIRouter(prefix="/upload", tags=["upload"])

SUPPORTED = {".pdf", ".docx", ".txt"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def _get_or_create_label(db: Session, user_id: int, name: str) -> Label:
    label = db.query(Label).filter(Label.user_id == user_id, Label.name == name).first()
    if not label:
        label = Label(user_id=user_id, name=name)
        db.add(label)
        db.commit()
        db.refresh(label)
    return label


# ── Background ingest ──────────────────────────────────────────────────────────

log = logging.getLogger("upload")

# In-memory progress per (user_id, label) — resets on restart, fine for polling UX
JOBS: dict[tuple[int, str], dict] = {}


def _register_job(user_id: int, label_name: str):
    """Reset any previous job so polling can't pick up a stale 'finished' result."""
    JOBS[(user_id, label_name)] = {
        "total_chunks": 0, "done_chunks": 0, "failed_chunks": 0,
        "last_error": None, "finished": False, "max_questions": None,
        "phase": "starting",
    }


async def _run_job(
    user_id: int,
    label_name: str,
    source: str,
    paragraphs: list[str],
    provider: str,
    model: str,
    api_key: str | None,
    max_questions: int | None = None,
    extra: dict | None = None,
):
    """Generate questions chunk by chunk with its own DB session; record progress/errors."""
    job = JOBS[(user_id, label_name)] = {
        "total_chunks": len(paragraphs), "done_chunks": 0,
        "failed_chunks": 0, "last_error": None, "finished": False,
        "max_questions": max_questions,
        "phase": "generating",
        **(extra or {}),
    }
    generated = 0
    db = SessionLocal()
    try:
        label = _get_or_create_label(db, user_id, label_name)
        for para in paragraphs:
            n = min(3, max(1, len(para) // 500))
            if max_questions is not None:
                if generated >= max_questions:
                    break
                n = min(n, max_questions - generated)
            try:
                questions = await generate_questions(
                    para, n=n, model=model, provider=provider, api_key=api_key
                )
                if not questions:
                    raise ValueError("Model returned no valid questions for this chunk")
                for q in questions:
                    db.add(Question(
                        label_id=label.id,
                        question_text=q["question"],
                        options=q["options"],
                        answer=q["answer"],
                        explanation=q.get("explanation", ""),
                        source_file=source,
                    ))
                generated += len(questions)
                db.commit()
            except Exception as e:
                db.rollback()
                job["failed_chunks"] += 1
                job["last_error"] = f"{type(e).__name__}: {e}"[:300]
                log.warning("chunk failed (%s): %s", label_name, job["last_error"])
            job["done_chunks"] += 1
    except Exception as e:
        job["last_error"] = f"{type(e).__name__}: {e}"[:300]
        log.exception("ingest job crashed")
    finally:
        job["finished"] = True
        db.close()


async def _ingest(file_path, filename, label_name, user_id, provider, model, api_key, max_questions=None):
    try:
        paragraphs = extract_paragraphs(file_path)
    except Exception as e:  # unreadable/corrupt file: report instead of polling forever
        log.exception("file parse failed")
        JOBS[(user_id, label_name)] = {
            "total_chunks": 0, "done_chunks": 0, "failed_chunks": 0,
            "last_error": f"Could not read file: {type(e).__name__}: {e}"[:300],
            "finished": True, "max_questions": max_questions,
        }
        return
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass
    await _run_job(user_id, label_name, filename, paragraphs, provider, model, api_key, max_questions)


async def _notion_job(
    user_id, label_name, page_id, notion_key, source,
    provider, model, api_key, max_questions, read_images,
):
    """Fetch the Notion block tree (page-capped), optionally read images, then generate."""
    key = (user_id, label_name)
    job = JOBS[key]
    try:
        job["phase"] = "fetching Notion pages"
        blocks, stats = await collect_blocks(page_id, notion_key)
        job.update(stats)
        describe = None
        if read_images:
            job["phase"] = "reading images"

            async def describe(img, mime):
                return await describe_image(img, mime, model, api_key)
        paragraphs, istats = await blocks_to_paragraphs(blocks, describe)
        stats.update(istats)
        job.update(istats)
        if not paragraphs:
            from collections import Counter
            seen = ", ".join(f"{t}×{n}" for t, n in Counter(b.get("type") for b in blocks).most_common(6)) or "none"
            msg = f"No readable text found in the Notion page. Blocks seen: {seen}."
            if istats["images_found"]:
                msg += (f" Images: {istats['images_found']} found, {istats['images_read']} read, "
                        f"{istats['images_failed']} failed, {istats['images_empty']} had no readable content.")
                if istats["image_errors"]:
                    msg += " First image error: " + istats["image_errors"][0]
                elif not read_images:
                    msg += " Enable 'Read images' with Gemini."
            elif not blocks:
                msg += " The integration may not be shared with this page's content."
            else:
                msg += " No image blocks were found (images must be placed directly on the page)."
            raise ValueError(msg)
    except Exception as e:
        log.exception("notion fetch failed")
        job.update(finished=True, total_chunks=0, last_error=f"{type(e).__name__}: {e}"[:600])
        return
    await _run_job(user_id, label_name, source, paragraphs, provider, model, api_key, max_questions, stats)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/providers")
def list_providers():
    """Return available providers and their suggested models."""
    providers = {}
    # DISABLE_OLLAMA=true when deploying to cloud (no local Ollama available)
    if not os.getenv("DISABLE_OLLAMA", "").lower() in ("1", "true", "yes"):
        providers["ollama"] = {
            "description": "Local Ollama — no API key needed",
            "suggested_models": ["llama3", "gemma3:4b", "mistral"],
            "requires_api_key": False,
            "free": True,
        }
    providers["groq"] = {
        "description": "Groq cloud — free tier at console.groq.com",
        "suggested_models": PROVIDER_CONFIGS["groq"]["suggested_models"],
        "requires_api_key": True,
        "free": True,
        "get_key_url": "https://console.groq.com/keys",
    }
    providers["gemini"] = {
        "description": "Google Gemini — free tier at aistudio.google.com",
        "suggested_models": PROVIDER_CONFIGS["gemini"]["suggested_models"],
        "requires_api_key": True,
        "free": True,
        "get_key_url": "https://aistudio.google.com/app/apikey",
    }
    return providers


@router.post("", dependencies=[Depends(forbid_demo), Depends(user_limit("generate", 30, 3600))])
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    label: str = Form(...),
    provider: str = Form(default="ollama"),
    model: str = Form(default="llama3"),
    api_key: str = Form(default=""),
    max_questions: int | None = Form(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use PDF, DOCX or TXT.")

    key = api_key.strip() or None
    err = await probe_provider(provider, model, key)
    if err:
        raise HTTPException(503, err)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File too large. Maximum size is {MAX_UPLOAD_MB} MB.")
                tmp.write(chunk)
    except HTTPException:
        os.unlink(tmp_path)
        raise

    _register_job(user.id, label)
    background_tasks.add_task(_ingest, tmp_path, file.filename, label, user.id, provider, model, key, max_questions)

    return {
        "message": "File accepted. Question generation running in background.",
        "label": label,
        "filename": file.filename,
        "provider": provider,
    }


class TopicRequest(BaseModel):
    label: str
    topic: str
    num_questions: int = 5
    provider: str = "ollama"
    model: str = "llama3"
    api_key: str = ""


@router.post("/generate-from-topic", dependencies=[Depends(forbid_demo), Depends(user_limit("generate", 30, 3600))])
async def generate_from_topic(
    req: TopicRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if req.num_questions < 1 or req.num_questions > 100:
        raise HTTPException(400, "num_questions must be between 1 and 100")

    key = req.api_key.strip() or None
    err = await probe_provider(req.provider, req.model, key)
    if err:
        raise HTTPException(503, err)

    try:
        questions = await generate_questions_from_topic(
            req.topic, n=req.num_questions, model=req.model,
            provider=req.provider, api_key=key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"LLM call failed: {e}")

    if not questions:
        raise HTTPException(502, "Model returned no valid questions. Try a different topic or model.")

    label = _get_or_create_label(db, user.id, req.label)

    for q in questions:
        db.add(Question(
            label_id=label.id,
            question_text=q["question"],
            options=q["options"],
            answer=q["answer"],
            explanation=q.get("explanation", ""),
            source_file=f"[{req.provider}] {req.topic}",
        ))
    db.commit()

    return {
        "message": f"{len(questions)} questions generated from topic.",
        "label": req.label,
        "topic": req.topic,
        "provider": req.provider,
        "generated": len(questions),
    }


class NotionRequest(BaseModel):
    label: str
    page_url: str         # full Notion page URL
    notion_api_key: str   # Notion integration token
    provider: str = "ollama"
    model: str = "llama3"
    api_key: str = ""     # LLM provider API key (for groq/gemini)
    max_questions: int | None = Field(default=None, ge=1, le=500)  # None = auto
    read_images: bool = False  # transcribe images with Gemini vision (provider must be gemini)


@router.post("/from-notion", dependencies=[Depends(forbid_demo), Depends(user_limit("generate", 30, 3600))])
async def ingest_from_notion(
    background_tasks: BackgroundTasks,
    req: NotionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fetch a Notion page, extract text, and generate questions in the background."""
    llm_key = req.api_key.strip() or None
    err = await probe_provider(req.provider, req.model, llm_key)
    if err:
        raise HTTPException(503, err)

    if req.read_images and req.provider != "gemini":
        raise HTTPException(400, "Reading images requires the Gemini provider.")

    # Fast access check only; the slow block-tree walk happens in the background job
    try:
        page_id, page_title = await check_page(req.page_url, req.notion_api_key.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch Notion page: {e}")

    _register_job(user.id, req.label)
    background_tasks.add_task(
        _notion_job, user.id, req.label, page_id, req.notion_api_key.strip(),
        f"[notion] {page_title}", req.provider, req.model, llm_key,
        req.max_questions, req.read_images,
    )
    return {
        "message": f"Notion page '{page_title}' accepted. Fetching and generating in background.",
        "label": req.label, "page_title": page_title, "provider": req.provider,
        "read_images": req.read_images,
    }


@router.get("/status/{label_name}")
def label_status(label_name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    label = db.query(Label).filter(Label.user_id == user.id, Label.name == label_name).first()
    count = db.query(Question).filter(Question.label_id == label.id).count() if label else 0
    return {"label": label_name, "question_count": count, "job": JOBS.get((user.id, label_name))}
