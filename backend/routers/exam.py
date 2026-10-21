"""
Exam lifecycle endpoints.

POST /exam/create             — create session from question bank
GET  /exam/{id}               — get session metadata + questions (no answers)
POST /exam/{id}/submit        — submit all answers → score
GET  /exam/{id}/results       — full results with correct answers + explanations
GET  /exams                   — list all past sessions
"""

import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ExamSession, ExamAnswer, Question, Label, User
from services.auth import get_current_user

router = APIRouter(prefix="/exam", tags=["exam"])


# ── Request / Response schemas ────────────────────────────────────────────────

class CreateExamRequest(BaseModel):
    name: str = ""
    label_ids: list[int]          # draw questions from these labels
    num_questions: int             # how many to pick
    timer_seconds: int             # total quiz timer


class SubmitAnswerItem(BaseModel):
    question_id: int
    user_answer: str | None        # A/B/C/D or null for skipped


class SubmitExamRequest(BaseModel):
    answers: list[SubmitAnswerItem]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create")
def create_exam(req: CreateExamRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if req.num_questions < 1:
        raise HTTPException(400, "num_questions must be >= 1")
    if req.timer_seconds < 30:
        raise HTTPException(400, "timer_seconds must be >= 30")

    # Validate labels exist
    labels = db.query(Label).filter(Label.id.in_(req.label_ids), Label.user_id == user.id).all()
    if len(labels) != len(req.label_ids):
        raise HTTPException(404, "One or more label IDs not found")

    # Pull questions from the selected labels
    pool = (
        db.query(Question)
        .filter(Question.label_id.in_(req.label_ids))
        .all()
    )
    # The same question can be stored under several labels: keep one copy per text
    unique: dict[str, Question] = {}
    for item in pool:
        unique.setdefault(" ".join(item.question_text.lower().split()), item)
    pool = list(unique.values())
    if not pool:
        raise HTTPException(422, "No questions found for the selected label(s). Upload documents first.")
    if len(pool) < req.num_questions:
        raise HTTPException(
            422,
            f"Only {len(pool)} questions available; requested {req.num_questions}."
        )

    selected = random.sample(pool, req.num_questions)
    question_ids = [q.id for q in selected]

    session = ExamSession(
        user_id=user.id,
        name=req.name or f"Exam {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        label_ids=req.label_ids,
        question_ids=question_ids,
        timer_seconds=req.timer_seconds,
        total=req.num_questions,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {"session_id": session.id, "total": session.total}


@router.get("/{session_id}")
def get_exam(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = db.query(ExamSession).filter(ExamSession.id == session_id, ExamSession.user_id == user.id).first()
    if not session:
        raise HTTPException(404, "Exam session not found")

    questions = (
        db.query(Question)
        .filter(Question.id.in_(session.question_ids))
        .all()
    )
    # Return in the order they were selected
    q_map = {q.id: q for q in questions}
    ordered = [q_map[qid] for qid in session.question_ids if qid in q_map]

    return {
        "session_id": session.id,
        "name": session.name,
        "timer_seconds": session.timer_seconds,
        "total": session.total,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "options": q.options,
                # answer and explanation intentionally omitted
            }
            for q in ordered
        ],
    }


@router.post("/{session_id}/start")
def start_exam(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Mark the exam as started (records start time for reference)."""
    session = db.query(ExamSession).filter(ExamSession.id == session_id, ExamSession.user_id == user.id).first()
    if not session:
        raise HTTPException(404, "Exam session not found")
    if not session.started_at:
        session.started_at = datetime.utcnow()
        db.commit()
    return {"started_at": session.started_at}


@router.post("/{session_id}/submit")
def submit_exam(session_id: int, req: SubmitExamRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = db.query(ExamSession).filter(ExamSession.id == session_id, ExamSession.user_id == user.id).first()
    if not session:
        raise HTTPException(404, "Exam session not found")
    if session.completed_at:
        raise HTTPException(409, "Exam already submitted")

    # Fetch correct answers
    questions = db.query(Question).filter(Question.id.in_(session.question_ids)).all()
    answer_key = {q.id: q.answer for q in questions}

    score = 0
    for item in req.answers:
        ua = (item.user_answer or "").upper() or None
        correct = answer_key.get(item.question_id)
        is_correct = ua is not None and ua == correct
        if is_correct:
            score += 1
        db.add(ExamAnswer(
            session_id=session_id,
            question_id=item.question_id,
            user_answer=ua,
            is_correct=is_correct,
        ))

    session.score = score
    session.completed_at = datetime.utcnow()
    db.commit()

    return {
        "score": score,
        "total": session.total,
        "percentage": round(score / session.total * 100, 1),
    }


@router.get("/{session_id}/results")
def get_results(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = db.query(ExamSession).filter(ExamSession.id == session_id, ExamSession.user_id == user.id).first()
    if not session:
        raise HTTPException(404, "Exam session not found")
    if not session.completed_at:
        raise HTTPException(422, "Exam not yet submitted")

    answers = {a.question_id: a for a in session.answers}
    questions = db.query(Question).filter(Question.id.in_(session.question_ids)).all()
    q_map = {q.id: q for q in questions}

    items = []
    for qid in session.question_ids:
        q = q_map.get(qid)
        a = answers.get(qid)
        if not q:
            continue
        items.append({
            "question_id": qid,
            "question_text": q.question_text,
            "options": q.options,
            "correct_answer": q.answer,
            "explanation": q.explanation,
            "user_answer": a.user_answer if a else None,
            "is_correct": a.is_correct if a else False,
        })

    return {
        "session_id": session_id,
        "name": session.name,
        "score": session.score,
        "total": session.total,
        "percentage": round(session.score / session.total * 100, 1),
        "completed_at": session.completed_at,
        "items": items,
    }


@router.get("")
def list_exams(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sessions = (
        db.query(ExamSession)
        .filter(ExamSession.user_id == user.id)
        .order_by(ExamSession.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "total": s.total,
            "score": s.score,
            "percentage": round(s.score / s.total * 100, 1) if s.score is not None else None,
            "completed_at": s.completed_at,
        }
        for s in sessions
    ]
