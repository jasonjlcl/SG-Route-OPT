import time

from sqlalchemy import create_engine, event, inspect, text
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
            # Allow readers/writers to coexist better under Cloud Run request concurrency.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def ensure_schema_compatibility() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)

    def has_column(table_name: str, column_name: str) -> bool:
        if not inspector.has_table(table_name):
            return False
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        return column_name in columns

    alter_statements: list[str] = []
    if not has_column("plans", "total_makespan_s"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN total_makespan_s FLOAT")
    if not has_column("plans", "updated_at"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN updated_at DATETIME")
    if not has_column("plans", "vehicle_capacity"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN vehicle_capacity INTEGER")
    if not has_column("plans", "workday_start"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN workday_start VARCHAR(5)")
    if not has_column("plans", "workday_end"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN workday_end VARCHAR(5)")
    if not has_column("plans", "eta_source"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN eta_source VARCHAR(32)")
    if not has_column("plans", "traffic_timestamp_iso"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN traffic_timestamp_iso VARCHAR(64)")
    if not has_column("plans", "live_traffic_requested"):
        alter_statements.append("ALTER TABLE plans ADD COLUMN live_traffic_requested BOOLEAN DEFAULT 0")
    if not has_column("stops", "phone"):
        alter_statements.append("ALTER TABLE stops ADD COLUMN phone VARCHAR(64)")
    if not has_column("stops", "contact_name"):
        alter_statements.append("ALTER TABLE stops ADD COLUMN contact_name VARCHAR(255)")
    if not has_column("jobs", "progress_pct"):
        alter_statements.append("ALTER TABLE jobs ADD COLUMN progress_pct INTEGER DEFAULT 0")
    if not has_column("jobs", "current_step"):
        alter_statements.append("ALTER TABLE jobs ADD COLUMN current_step VARCHAR(64)")
    if not has_column("jobs", "error_code"):
        alter_statements.append("ALTER TABLE jobs ADD COLUMN error_code VARCHAR(128)")
    if not has_column("jobs", "error_detail"):
        alter_statements.append("ALTER TABLE jobs ADD COLUMN error_detail TEXT")
    if not has_column("jobs", "steps_json"):
        alter_statements.append("ALTER TABLE jobs ADD COLUMN steps_json TEXT")
    if not has_column("models", "artifact_gcs_uri"):
        alter_statements.append("ALTER TABLE models ADD COLUMN artifact_gcs_uri TEXT")
    if not has_column("models", "vertex_model_resource"):
        alter_statements.append("ALTER TABLE models ADD COLUMN vertex_model_resource TEXT")

    if alter_statements:
        with engine.begin() as conn:
            for statement in alter_statements:
                conn.execute(text(statement))


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
