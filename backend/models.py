from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from datetime import datetime
from database import Base


class Label(Base):
    __tablename__ = "labels"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_label_user_name"),)

    questions = relationship("Question", back_populates="label", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    label_id = Column(Integer, ForeignKey("labels.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    # {"A": "...", "B": "...", "C": "...", "D": "..."}
    options = Column(JSON, nullable=False)
    answer = Column(String(1), nullable=False)   # A / B / C / D
    explanation = Column(Text, default="")
    source_file = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    label = relationship("Label", back_populates="questions")


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    user_id = Column(Integer, ForeignKey("users.id"), index=True)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="")
    label_ids = Column(JSON, nullable=False)        # [1, 2, ...]
    question_ids = Column(JSON, nullable=False)     # ordered list used in this session
    timer_seconds = Column(Integer, nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    score = Column(Integer)    # number correct, set on completion
    total = Column(Integer)    # total questions

    answers = relationship("ExamAnswer", back_populates="session", cascade="all, delete-orphan")


class ExamAnswer(Base):
    __tablename__ = "exam_answers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("exam_sessions.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    user_answer = Column(String(1))   # A/B/C/D or None if skipped/timed-out
    is_correct = Column(Boolean)

    session = relationship("ExamSession", back_populates="answers")
    question = relationship("Question")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
