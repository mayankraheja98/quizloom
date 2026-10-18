"""
Question bank management endpoints.

GET  /labels                  — list all labels with question counts
GET  /questions?label_id=&page=&size=  — paginated question list
DELETE /questions/{id}        — delete a single question
DELETE /labels/{id}           — delete a label and all its questions
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Label, Question, User
from services.auth import forbid_demo, get_current_user

router = APIRouter(tags=["questions"])


@router.get("/labels")
def list_labels(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(Label, func.count(Question.id).label("count"))
        .outerjoin(Question, Question.label_id == Label.id)
        .filter(Label.user_id == user.id)
        .group_by(Label.id)
        .all()
    )
    return [
        {"id": label.id, "name": label.name, "question_count": count, "created_at": label.created_at}
        for label, count in rows
    ]


@router.get("/questions")
def list_questions(
    label_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Question).join(Label, Label.id == Question.label_id).filter(Label.user_id == user.id)
    if label_id is not None:
        q = q.filter(Question.label_id == label_id)
    total = q.count()
    items = q.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": item.id,
                "label_id": item.label_id,
                "question_text": item.question_text,
                "options": item.options,
                "answer": item.answer,
                "explanation": item.explanation,
                "source_file": item.source_file,
                "created_at": item.created_at,
            }
            for item in items
        ],
    }


@router.delete("/questions/{question_id}", dependencies=[Depends(forbid_demo)])
def delete_question(question_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = (
        db.query(Question).join(Label, Label.id == Question.label_id)
        .filter(Question.id == question_id, Label.user_id == user.id).first()
    )
    if not q:
        raise HTTPException(404, "Question not found")
    db.delete(q)
    db.commit()
    return {"deleted": question_id}


@router.delete("/labels/{label_id}", dependencies=[Depends(forbid_demo)])
def delete_label(label_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    label = db.query(Label).filter(Label.id == label_id, Label.user_id == user.id).first()
    if not label:
        raise HTTPException(404, "Label not found")
    db.delete(label)   # cascade deletes questions
    db.commit()
    return {"deleted": label_id}
