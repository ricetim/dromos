from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session, select
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record):
    """Apply SQLite performance settings on every new connection."""
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")       # concurrent reads during writes
    cur.execute("PRAGMA cache_size=-32000")       # 32 MB page cache
    cur.execute("PRAGMA synchronous=NORMAL")      # safe durability with WAL
    cur.execute("PRAGMA temp_store=MEMORY")       # temp tables in RAM
    cur.close()


def _add_column(conn, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it does not already exist."""
    try:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass  # column already exists


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    # Incremental column migrations for existing databases
    with engine.connect() as conn:
        _add_column(conn, "datapoint", "vertical_oscillation_mm", "REAL")
        _add_column(conn, "datapoint", "stride_length_m", "REAL")
        _add_column(conn, "datapoint", "vertical_ratio", "REAL")
        _add_column(conn, "datapoint", "stance_time_ms", "REAL")
        _add_column(conn, "activity", "rpe", "INTEGER")
        _add_column(conn, "activity", "name", "TEXT")
        _add_column(conn, "activity", "elevation_loss_m", "REAL")
        _add_column(conn, "shoe", "strava_gear_id", "TEXT")
        _add_column(conn, "activity", "weather_temp_c", "REAL")
        _add_column(conn, "activity", "weather_feels_like_c", "REAL")
        _add_column(conn, "activity", "weather_precip_mm", "REAL")
        _add_column(conn, "activity", "weather_cloud_pct", "INTEGER")
        _add_column(conn, "activity", "weather_wind_kph", "REAL")
        _add_column(conn, "activity", "weather_condition", "TEXT")
        _add_column(conn, "activity", "weather_is_daytime", "INTEGER")

        # Back-fill avg_pace_s_per_km using correct formula: duration_s / (distance_m / 1000)
        # The old formula (mean of 1000/speed per datapoint) over-weighted slow segments.
        conn.exec_driver_sql(
            "UPDATE activity SET avg_pace_s_per_km = "
            "CAST(duration_s AS REAL) / (distance_m / 1000.0) "
            "WHERE distance_m > 0"
        )

        # Performance indexes — safe to run repeatedly (IF NOT EXISTS)
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_dp_activity_ts "
            "ON datapoint(activity_id, timestamp)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_activity_started_at "
            "ON activity(started_at DESC)"
        )

        # Dedupe ActivityShoe rows (keep newest link per activity), then
        # enforce one-link-per-activity at the DB layer. Must dedupe BEFORE
        # creating the unique index or the CREATE will fail.
        conn.exec_driver_sql(
            "DELETE FROM activityshoe WHERE id NOT IN "
            "(SELECT MAX(id) FROM activityshoe GROUP BY activity_id)"
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_activityshoe_activity_id_unique "
            "ON activityshoe(activity_id)"
        )
        conn.commit()
    # Seed singleton UserProfile if not present
    from app.models import UserProfile
    with Session(engine) as session:
        if not session.get(UserProfile, 1):
            session.add(UserProfile(id=1))
            session.commit()


def get_session():
    with Session(engine) as session:
        yield session
