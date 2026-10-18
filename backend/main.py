import os
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import SessionLocal, engine, migrate
import models
from routers import upload, questions, exam, auth
from services.auth import get_current_user

# Create all tables on startup
models.Base.metadata.create_all(bind=engine)
migrate()
from services.demo import seed_demo  # noqa: E402

with SessionLocal() as _db:
    seed_demo(_db)

app = FastAPI(title="Quizloom API", version="1.0.0")

# ALLOWED_ORIGINS: comma-separated list, or "*" to allow all (useful behind Netlify proxy)
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
allow_origins = [o.strip() for o in _origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
_protected = [Depends(get_current_user)]
app.include_router(upload.router, dependencies=_protected)
app.include_router(questions.router, dependencies=_protected)
app.include_router(exam.router, dependencies=_protected)


@app.get("/health")
async def health():
    return {"status": "ok"}
