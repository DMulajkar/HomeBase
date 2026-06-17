import sqlite3
from datetime import date, datetime, timezone
from typing import Optional


# --- Layer 1: pure due-logic (no I/O, unit-tested) ---


def is_due(now: datetime, last_run_date: Optional[date], reminder_hour: int) -> bool:
    """Whether a once-daily job should run now (all times UTC).

    Due when the current hour has reached reminder_hour and the job has not
    already run today.
    """
    if now.hour < reminder_hour:
        return False
    return last_run_date is None or last_run_date < now.date()


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_state (
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            job_key TEXT NOT NULL,
            last_run_date TEXT,
            last_run_at TEXT,
            PRIMARY KEY (house_id, job_key)
        )
        """
    )
    conn.commit()


def get_last_run_date(conn: sqlite3.Connection, house_id: int, job_key: str) -> Optional[date]:
    row = conn.execute(
        "SELECT last_run_date FROM schedule_state WHERE house_id = ? AND job_key = ?",
        (house_id, job_key),
    ).fetchone()
    if row is None or row["last_run_date"] is None:
        return None
    return date.fromisoformat(row["last_run_date"])


def set_last_run(
    conn: sqlite3.Connection,
    house_id: int,
    job_key: str,
    run_date: date,
    run_at: Optional[datetime] = None,
) -> None:
    if run_at is None:
        run_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO schedule_state (house_id, job_key, last_run_date, last_run_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(house_id, job_key) DO UPDATE SET "
        "last_run_date = excluded.last_run_date, last_run_at = excluded.last_run_at",
        (house_id, job_key, run_date.isoformat(), run_at.isoformat()),
    )
    conn.commit()
