from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.utils.settings import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session, expire_on_commit=False)


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
    if not has_column("stops", "phone"):
        alter_statements.append("ALTER TABLE stops ADD COLUMN phone VARCHAR(64)")
    if not has_column("stops", "contact_name"):
        alter_statements.append("ALTER TABLE stops ADD COLUMN contact_name VARCHAR(255)")

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
