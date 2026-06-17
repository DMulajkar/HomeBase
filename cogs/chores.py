import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

import database

CADENCES = ("daily", "weekly", "monthly")


# --- Layer 1: pure rotation logic (no I/O, unit-tested) ---


def _add_months(d: date, months: int) -> date:
    """Return the first day of the month `months` after d's month."""
    total = (d.year * 12 + (d.month - 1)) + months
    return date(total // 12, total % 12 + 1, 1)


def current_period_index(cadence: str, start_date: date, today: date) -> int:
    """How many cadence periods have elapsed since start_date (0 for the first).

    Daily/weekly periods anchor to start_date; monthly periods rotate on
    calendar-month boundaries (not the start day-of-month). Never negative.
    """
    if cadence == "daily":
        return max(0, (today - start_date).days)
    if cadence == "weekly":
        return max(0, (today - start_date).days // 7)
    if cadence == "monthly":
        months = (today.year - start_date.year) * 12 + (today.month - start_date.month)
        return max(0, months)
    raise ValueError(f"Unknown cadence: {cadence}")


def assignee_for_period(member_ids_ordered: list[int], period_index: int) -> Optional[int]:
    """Round-robin assignee for a period, or None if there are no members."""
    if not member_ids_ordered:
        return None
    return member_ids_ordered[period_index % len(member_ids_ordered)]


def period_end_date(cadence: str, start_date: date, period_index: int) -> date:
    """The last date of the given period (its 'due by')."""
    if cadence == "daily":
        return start_date + timedelta(days=period_index)
    if cadence == "weekly":
        return start_date + timedelta(days=(period_index + 1) * 7 - 1)
    if cadence == "monthly":
        first_of_month = _add_months(date(start_date.year, start_date.month, 1), period_index)
        return _add_months(first_of_month, 1) - timedelta(days=1)
    raise ValueError(f"Unknown cadence: {cadence}")


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chores (
            chore_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            name TEXT NOT NULL,
            cadence TEXT NOT NULL,
            start_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(house_id, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chore_completions (
            completion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chore_id INTEGER NOT NULL REFERENCES chores(chore_id),
            period_index INTEGER NOT NULL,
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            completed_at TEXT NOT NULL,
            UNIQUE(chore_id, period_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chore_swaps (
            swap_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chore_id INTEGER NOT NULL REFERENCES chores(chore_id),
            period_index INTEGER NOT NULL,
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            created_at TEXT NOT NULL,
            UNIQUE(chore_id, period_index)
        )
        """
    )
    conn.commit()


def add_chore(conn: sqlite3.Connection, house_id: int, name: str, cadence: str, start_date: str) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO chores (house_id, name, cadence, start_date, created_at) VALUES (?, ?, ?, ?, ?)",
            (house_id, name, cadence, start_date, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A chore named '{name}' already exists in this house.")


def get_chore(conn: sqlite3.Connection, house_id: int, name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chores WHERE house_id = ? AND name = ?", (house_id, name)
    ).fetchone()


def list_chores(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chores WHERE house_id = ? ORDER BY chore_id", (house_id,)
    ).fetchall()


def record_completion(conn: sqlite3.Connection, chore_id: int, period_index: int, member_id: int) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO chore_completions (chore_id, period_index, member_id, completed_at) "
            "VALUES (?, ?, ?, ?)",
            (chore_id, period_index, member_id, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("This chore is already marked done for the current period.")


def get_completion(conn: sqlite3.Connection, chore_id: int, period_index: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chore_completions WHERE chore_id = ? AND period_index = ?",
        (chore_id, period_index),
    ).fetchone()


def record_swap(conn: sqlite3.Connection, chore_id: int, period_index: int, member_id: int) -> None:
    conn.execute(
        "INSERT INTO chore_swaps (chore_id, period_index, member_id, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chore_id, period_index) DO UPDATE SET "
        "member_id = excluded.member_id, created_at = excluded.created_at",
        (chore_id, period_index, member_id, _now_iso()),
    )
    conn.commit()


def get_override(conn: sqlite3.Connection, chore_id: int, period_index: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chore_swaps WHERE chore_id = ? AND period_index = ?",
        (chore_id, period_index),
    ).fetchone()


def completion_counts(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, Optional[str], int]]:
    rows = conn.execute(
        "SELECT m.member_id, m.display_name, COUNT(cc.completion_id) AS cnt "
        "FROM members m "
        "LEFT JOIN chore_completions cc ON cc.member_id = m.member_id "
        "WHERE m.house_id = ? "
        "GROUP BY m.member_id ORDER BY cnt DESC, m.member_id",
        (house_id,),
    ).fetchall()
    return [(r["member_id"], r["display_name"], r["cnt"]) for r in rows]


def current_assignee(
    conn: sqlite3.Connection, chore: sqlite3.Row, member_ids_ordered: list[int], today: date
) -> tuple[Optional[int], bool, bool, int]:
    """Resolve the live state of a chore for the current period.

    Returns (assignee_member_id, done, swapped, period_index). A per-period
    swap override takes precedence over the round-robin assignee.
    """
    start = date.fromisoformat(chore["start_date"])
    pidx = current_period_index(chore["cadence"], start, today)
    override = get_override(conn, chore["chore_id"], pidx)
    assignee_id = override["member_id"] if override else assignee_for_period(member_ids_ordered, pidx)
    done = get_completion(conn, chore["chore_id"], pidx) is not None
    return assignee_id, done, override is not None, pidx


def render_chores_reminder(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """Build the daily chore reminder message, or None if there are no chores."""
    house_chores = list_chores(conn, house_id)
    if not house_chores:
        return None
    members = database.list_members(conn, house_id)
    member_ids = [m["member_id"] for m in members]
    names = {m["member_id"]: m["display_name"] for m in members}

    lines = ["🧹 **Daily chore reminder**"]
    for c in house_chores:
        assignee_id, done, swapped, _ = current_assignee(conn, c, member_ids, today)
        assignee = names.get(assignee_id, "—")
        status = "✅ done" if done else "⏳ pending"
        sw = " (swapped)" if swapped else ""
        lines.append(f"- **{c['name']}** ({c['cadence']}) → {assignee}{sw} · {status}")
    return "\n".join(lines)


# --- Layer 3: Discord plumbing and guards ---


async def _get_house_and_member(bot: commands.Bot, interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return None
    house = database.get_house(bot.db, str(interaction.guild_id))
    if house is None:
        await interaction.response.send_message(
            "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
        )
        return None
    member = database.get_member(bot.db, house["house_id"], str(interaction.user.id))
    if member is None:
        await interaction.response.send_message(
            "You're not a member of this house yet. Run /join-house first.", ephemeral=True
        )
        return None
    return house, member


class Chores(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="chore-add", description="Add a recurring chore to the rotation")
    @app_commands.describe(name="Name of the chore", cadence="How often it rotates")
    async def chore_add(
        self,
        interaction: discord.Interaction,
        name: str,
        cadence: Literal["daily", "weekly", "monthly"],
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        start = datetime.now(timezone.utc).date().isoformat()
        try:
            add_chore(self.bot.db, house["house_id"], name, cadence, start)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Added {cadence} chore '{name}'. It rotates through house members."
        )

    @app_commands.command(name="chores", description="Show current chore assignments")
    async def chores(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        house_chores = list_chores(self.bot.db, house["house_id"])
        if not house_chores:
            await interaction.response.send_message("No chores yet. Add one with /chore-add.")
            return

        members = database.list_members(self.bot.db, house["house_id"])
        member_ids = [m["member_id"] for m in members]
        names = {m["member_id"]: m["display_name"] for m in members}
        today = datetime.now(timezone.utc).date()

        lines = ["**House chores**"]
        for c in house_chores:
            assignee_id, done, swapped, pidx = current_assignee(self.bot.db, c, member_ids, today)
            assignee = names.get(assignee_id, "—")
            status = "✅ done" if done else "⏳ pending"
            sw = " (swapped)" if swapped else ""
            due = period_end_date(c["cadence"], date.fromisoformat(c["start_date"]), pidx).isoformat()
            lines.append(f"**{c['name']}** ({c['cadence']}) → {assignee}{sw} · {status} · due {due}")

        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="complete", description="Mark a chore done for the current period")
    @app_commands.describe(name="Name of the chore you finished")
    async def complete(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        chore = get_chore(self.bot.db, house["house_id"], name)
        if chore is None:
            await interaction.response.send_message(f"No chore named '{name}'. See /chores.", ephemeral=True)
            return
        today = datetime.now(timezone.utc).date()
        pidx = current_period_index(chore["cadence"], date.fromisoformat(chore["start_date"]), today)
        try:
            record_completion(self.bot.db, chore["chore_id"], pidx, member["member_id"])
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Nice — {interaction.user.display_name} completed '{name}'. ✅"
        )

    @app_commands.command(name="swap", description="Hand off this period's chore to another member")
    @app_commands.describe(name="The chore to reassign", member="Who will do it this period")
    async def swap(self, interaction: discord.Interaction, name: str, member: discord.Member):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        chore = get_chore(self.bot.db, house["house_id"], name)
        if chore is None:
            await interaction.response.send_message(f"No chore named '{name}'. See /chores.", ephemeral=True)
            return
        target = database.get_member(self.bot.db, house["house_id"], str(member.id))
        if target is None:
            await interaction.response.send_message(
                f"{member.display_name} isn't a member of this house.", ephemeral=True
            )
            return
        today = datetime.now(timezone.utc).date()
        pidx = current_period_index(chore["cadence"], date.fromisoformat(chore["start_date"]), today)
        record_swap(self.bot.db, chore["chore_id"], pidx, target["member_id"])
        await interaction.response.send_message(
            f"'{name}' is now {member.display_name}'s for this period."
        )

    @app_commands.command(name="chore-history", description="Show chore completion counts per member")
    async def chore_history(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        counts = completion_counts(self.bot.db, house["house_id"])
        if not counts:
            await interaction.response.send_message("No members yet.")
            return
        lines = ["**Chore contributions**"]
        for _member_id, display_name, cnt in counts:
            lines.append(f"{display_name}: {cnt}")
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(Chores(bot))
