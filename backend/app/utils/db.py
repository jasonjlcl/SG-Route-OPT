import time

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.utils.settings import get_settings


settings = get_settings()
IS_SQLITE = settings.database_url.startswith("sqlite")
if IS_SQLITE:
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)


class RetrySession(Session):
    def commit(self) -> None:  # noqa: D401
        """Commit with a short retry window for transient SQLite writer locks."""
        if not IS_SQLITE:
            return super().commit()

        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                return super().commit()
            except OperationalError as exc:
                # SQLite single-writer contention can be transient under request/task overlap.
                if "database is locked" not in str(exc).lower() or attempt >= max_attempts:
                    raise
                super().rollback()
                time.sleep(0.15 * attempt)


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=RetrySession, expire_on_commit=False)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        try:
            # Improve local SQLite concurrency during tests/development.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
