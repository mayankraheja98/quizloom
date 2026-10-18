"""Seed a read-only public demo account with a pre-built question bank."""
import os
import random

from sqlalchemy.orm import Session

from models import Label, Question, User
from seed.demo_questions import DEMO_BANK
from services.auth import DEMO_USERNAME, hash_password

DEMO_PASSWORD = "demo-password"  # public by design; the account is read-only


def _shuffled(q: dict) -> tuple[dict, str]:
    """Deterministically shuffle option order so correct answers aren't clustered on one letter."""
    rng = random.Random(q["question"])
    texts = list(q["options"].values())
    correct = q["options"][q["answer"]]
    rng.shuffle(texts)
    return dict(zip("ABCD", texts)), "ABCD"[texts.index(correct)]


def demo_enabled() -> bool:
    return os.getenv("DEMO_ENABLED", "true").lower() not in ("0", "false", "no")


def seed_demo(db: Session) -> None:
    if not demo_enabled() or db.query(User).filter(User.username == DEMO_USERNAME).first():
        return
    user = User(username=DEMO_USERNAME, password_hash=hash_password(DEMO_PASSWORD))
    db.add(user)
    db.commit()
    db.refresh(user)
    for label_name, questions in DEMO_BANK.items():
        label = Label(user_id=user.id, name=label_name)
        db.add(label)
        db.commit()
        db.refresh(label)
        for q in questions:
            options, answer = _shuffled(q)
            db.add(Question(label_id=label.id, question_text=q["question"], options=options,
                            answer=answer, explanation=q["explanation"], source_file="demo"))
    db.commit()
