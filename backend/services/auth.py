"""Password hashing (stdlib scrypt) + JWT issue/verify + FastAPI dependency."""
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User

# MUST be set to a long random string in production
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_TTL = 60 * 60 * 24 * 7  # 7 days
_bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + h.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt_hex, h_hex = stored.split(":")
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(h.hex(), h_hex)


def make_token(user_id: int) -> str:
    return jwt.encode({"sub": str(user_id), "exp": int(time.time()) + JWT_TTL}, JWT_SECRET, "HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        uid = int(jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "User not found")
    return user


DEMO_USERNAME = "demo"


def forbid_demo(user: User = Depends(get_current_user)) -> None:
    """Block costly/destructive actions for the shared public demo account."""
    if user.username == DEMO_USERNAME:
        raise HTTPException(
            403, "The demo account is read-only (no uploads, generation or deletes). "
                 "Sign up for a free account to use this feature."
        )
