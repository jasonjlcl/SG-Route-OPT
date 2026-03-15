import time
import logging

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.utils.settings import get_settings

LOGGER = logging.getLogger(__name__)


settings = get_settings()
IS_SQLITE = settings.database_url.startswith("sqlite")
if IS_SQLITE:
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

SQLITE_COMPAT_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {
        "progress_pct": "INTEGER NOT NULL DEFAULT 0",
        "current_step": "VARCHAR(64)",
        "message": "VARCHAR(512)",
        "error_code": "VARCHAR(128)",
        "error_detail": "TEXT",
        "steps_json": "TEXT",
        "result_ref": "TEXT",
    },
    "plans": {
        "eta_source": "VARCHAR(32)",
        "traffic_timestamp_iso": "VARCHAR(64)",
        "live_traffic_requested": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


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
                LOGGER.warning(
                    "DB_LOCK_RETRY context=sqlalchemy_retry_session attempt=%s max_attempts=%s error=%s",
                    attempt,
                    max_attempts,
                    str(exc),
                )
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


def ensure_sqlite_schema_compatibility(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    with target_engine.begin() as conn:
        tables = {
            str(row[0])
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
            if row and row[0]
        }
        for table_name, expected_columns in SQLITE_COMPAT_COLUMNS.items():
            if table_name not in tables:
                continue

            existing_columns = {
                str(row["name"])
                for row in conn.exec_driver_sql(f'PRAGMA table_info("{table_name}")').mappings().all()
                if row.get("name")
            }
            for column_name, column_sql in expected_columns.items():
                if column_name in existing_columns:
                    continue
                LOGGER.warning("Adding missing SQLite compatibility column %s.%s", table_name, column_name)
                conn.exec_driver_sql(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_sql}')


ensure_sqlite_schema_compatibility(engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
