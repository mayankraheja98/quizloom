import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Railway: set DATABASE_URL=sqlite:////data/examprep.db and mount a volume at /data
# Local: defaults to ./examprep.db
SQLITE_URL = os.getenv("DATABASE_URL", "sqlite:///./examprep.db")
# Some hosts (Neon, Heroku) hand out postgres:// which SQLAlchemy rejects
if SQLITE_URL.startswith("postgres://"):
    SQLITE_URL = SQLITE_URL.replace("postgres://", "postgresql://", 1)

if SQLITE_URL.startswith("sqlite"):
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLITE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate():
    """Lightweight in-place upgrade for DBs created before per-user data."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in ("labels", "exam_sessions"):
            cols = {c["name"] for c in insp.get_columns(table)}
            if "user_id" not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
        # old schema had a globally-unique label name; replace with per-user uniqueness
        conn.execute(text("DROP INDEX IF EXISTS ix_labels_name"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_labels_name ON labels (name)"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_label_user_name ON labels (user_id, name)"
        ))
