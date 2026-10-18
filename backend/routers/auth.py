"""POST /auth/signup, POST /auth/login, GET /auth/me"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ExamSession, Label, User
import os

from services.auth import DEMO_USERNAME, get_current_user, hash_password, make_token, verify_password
from services.demo import DEMO_PASSWORD, demo_enabled
from services.ratelimit import ip_limit

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


@router.get("/config")
def config():
    """Public: lets the login page offer a one-click demo."""
    if not demo_enabled():
        return {"demo_enabled": False}
    return {"demo_enabled": True, "demo_username": DEMO_USERNAME, "demo_password": DEMO_PASSWORD}


@router.post("/signup", dependencies=[Depends(ip_limit("signup", 5, 3600))])
def signup(c: Credentials, db: Session = Depends(get_db)):
    username = c.username.strip().lower()
    if username == DEMO_USERNAME:
        raise HTTPException(409, "Username reserved")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Username already taken")
    first_user = db.query(User).count() == 0
    user = User(username=username, password_hash=hash_password(c.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    if first_user:  # adopt pre-auth data so it isn't orphaned
        db.query(Label).filter(Label.user_id.is_(None)).update({Label.user_id: user.id})
        db.query(ExamSession).filter(ExamSession.user_id.is_(None)).update({ExamSession.user_id: user.id})
        db.commit()
    return {"token": make_token(user.id), "username": user.username}


@router.post("/login", dependencies=[Depends(ip_limit("login", 10, 300))])
def login(c: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == c.username.strip().lower()).first()
    if not user or not verify_password(c.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"token": make_token(user.id), "username": user.username}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username}
