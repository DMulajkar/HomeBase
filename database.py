import sqlite3
from datetime import datetime, timezone
from typing import Optional


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS houses (
            house_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL UNIQUE,
            name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            discord_user_id TEXT NOT NULL,
            display_name TEXT,
            joined_at TEXT NOT NULL,
            UNIQUE(house_id, discord_user_id)
        )
        """
    )
    conn.commit()


def create_house(conn: sqlite3.Connection, guild_id: str, name: Optional[str]) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO houses (guild_id, name, created_at) VALUES (?, ?, ?)",
            (guild_id, name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A house already exists for guild {guild_id}")


def get_house(conn: sqlite3.Connection, guild_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM houses WHERE guild_id = ?", (guild_id,)).fetchone()


def list_houses(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM houses ORDER BY house_id").fetchall()


def add_member(conn: sqlite3.Connection, house_id: int, discord_user_id: str, display_name: Optional[str]) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO members (house_id, discord_user_id, display_name, joined_at) VALUES (?, ?, ?, ?)",
            (house_id, discord_user_id, display_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"Member {discord_user_id} already exists in house {house_id}")


def get_member(conn: sqlite3.Connection, house_id: int, discord_user_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM members WHERE house_id = ? AND discord_user_id = ?",
        (house_id, discord_user_id),
    ).fetchone()


def list_members(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM members WHERE house_id = ? ORDER BY member_id", (house_id,)
    ).fetchall()
