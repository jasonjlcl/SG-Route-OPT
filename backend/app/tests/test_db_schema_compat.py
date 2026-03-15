from sqlalchemy import create_engine

from app.utils.db import ensure_sqlite_schema_compatibility


def test_ensure_sqlite_schema_compatibility_adds_missing_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE jobs (
                id VARCHAR(64) PRIMARY KEY,
                type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                progress INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE plans (
                id INTEGER PRIMARY KEY,
                dataset_id INTEGER NOT NULL,
                depot_lat FLOAT NOT NULL,
                depot_lon FLOAT NOT NULL,
                num_vehicles INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                status VARCHAR(32) NOT NULL,
                objective_value NUMERIC(12, 2),
                total_makespan_s FLOAT,
                vehicle_capacity INTEGER,
                workday_start VARCHAR(5),
                workday_end VARCHAR(5),
                infeasibility_reason TEXT
            )
            """
        )

    ensure_sqlite_schema_compatibility(engine)
    ensure_sqlite_schema_compatibility(engine)

    with engine.connect() as conn:
        job_columns = {row["name"] for row in conn.exec_driver_sql('PRAGMA table_info("jobs")').mappings().all()}
        plan_columns = {row["name"] for row in conn.exec_driver_sql('PRAGMA table_info("plans")').mappings().all()}

    assert {"progress_pct", "current_step", "message", "error_code", "error_detail", "steps_json", "result_ref"} <= job_columns
    assert {"eta_source", "traffic_timestamp_iso", "live_traffic_requested"} <= plan_columns
