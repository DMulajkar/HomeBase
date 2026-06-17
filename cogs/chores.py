import calendar
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import channels

CADENCES = ("daily", "weekly", "monthly")
RANKINGS_DAY = 1  # day of the month to post the previous month's chore rankings


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


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', 23 -> '23rd'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_completion_confirmation(member_name: object, chore_name: object, total_completions: int) -> str:
    """Public confirmation posted when a chore is completed.

    `total_completions` is the member's all-time chore count (including this one);
    it tacks on a small bit of recognition when known.
    """
    base = f"✅ **{member_name}** completed **{chore_name}** — nice work!"
    if total_completions > 0:
        return f"{base} That's their {_ordinal(total_completions)} chore done."
    return base


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    """The calendar month before (year, month)."""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def previous_month(today: date) -> tuple[int, int]:
    """The (year, month) of the month before today's — what rankings summarize."""
    return _prev_year_month(today.year, today.month)


def is_rankings_day(today: date, rankings_day: int) -> bool:
    """Whether today is the day of the month to post chore rankings."""
    return today.day == rankings_day


def rank_members(counts: list[tuple[int, Optional[str], int]]) -> list[tuple[int, Optional[str], int]]:
    """Rank members by completion count, dropping zeros.

    Input is `(member_id, name, count)` tuples (any order). Output is
    `(rank, name, count)` sorted by count desc, with standard competition
    ranking for ties (1, 2, 2, 4). Members with zero completions are excluded.
    """
    nonzero = sorted(
        ((name, cnt) for _id, name, cnt in counts if cnt > 0),
        key=lambda nc: -nc[1],
    )
    ranked: list[tuple[int, Optional[str], int]] = []
    prev_cnt: Optional[int] = None
    prev_rank = 0
    for i, (name, cnt) in enumerate(nonzero, start=1):
        if cnt == prev_cnt:
            rank = prev_rank
        else:
            rank = i
            prev_rank, prev_cnt = i, cnt
        ranked.append((rank, name, cnt))
    return ranked


def monthly_streak(month_keys: set[str], year: int, month: int) -> int:
    """Consecutive months (ending at the given year/month) present in `month_keys`.

    `month_keys` holds 'YYYY-MM' strings for months the member completed a chore.
    Returns 0 if the ending month itself isn't present.
    """
    streak = 0
    y, m = year, month
    while f"{y:04d}-{m:02d}" in month_keys:
        streak += 1
        y, m = _prev_year_month(y, m)
    return streak


def _medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def format_rankings(
    month_label: str,
    ranked: list[tuple[int, Optional[str], int]],
    streaks: list[tuple[Optional[str], int]],
) -> str:
    """The monthly chore-rankings post: a leaderboard plus any active streaks."""
    lines = [f"🏆 **{month_label} Rankings**"]
    for rank, name, cnt in ranked:
        lines.append(f"{_medal(rank)} {name} — {cnt}")
    if streaks:
        parts = [f"{name} ({n} month{'s' if n != 1 else ''})" for name, n in streaks]
        lines.append("🔥 **Streaks**: " + ", ".join(parts))
    return "\n".join(lines)


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


def member_completion_count(conn: sqlite3.Connection, house_id: int, member_id: int) -> int:
    """All-time count of chores this member has completed in the house."""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM chore_completions cc "
        "JOIN chores c ON cc.chore_id = c.chore_id "
        "WHERE c.house_id = ? AND cc.member_id = ?",
        (house_id, member_id),
    ).fetchone()
    return row["cnt"]


def completion_counts_for_month(
    conn: sqlite3.Connection, house_id: int, year: int, month: int
) -> list[tuple[int, Optional[str], int]]:
    """Per-member completion counts within a single calendar month."""
    month_key = f"{year:04d}-{month:02d}"
    rows = conn.execute(
        "SELECT m.member_id, m.display_name, COUNT(cc.completion_id) AS cnt "
        "FROM members m "
        "LEFT JOIN chore_completions cc "
        "  ON cc.member_id = m.member_id AND substr(cc.completed_at, 1, 7) = ? "
        "WHERE m.house_id = ? "
        "GROUP BY m.member_id ORDER BY cnt DESC, m.member_id",
        (month_key, house_id),
    ).fetchall()
    return [(r["member_id"], r["display_name"], r["cnt"]) for r in rows]


def completion_months(conn: sqlite3.Connection, house_id: int) -> dict[int, set[str]]:
    """Map each member to the set of 'YYYY-MM' months they completed any chore."""
    rows = conn.execute(
        "SELECT cc.member_id, substr(cc.completed_at, 1, 7) AS ym "
        "FROM chore_completions cc JOIN members m ON m.member_id = cc.member_id "
        "WHERE m.house_id = ? GROUP BY cc.member_id, ym",
        (house_id,),
    ).fetchall()
    result: dict[int, set[str]] = {}
    for r in rows:
        result.setdefault(r["member_id"], set()).add(r["ym"])
    return result


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


def render_rankings(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """Once-a-month chore leaderboard for the month that just ended. No side effects.

    Returns None except on RANKINGS_DAY, and None if nobody completed a chore in
    the summarized month (nothing to celebrate). Streaks count consecutive months
    ending at the summarized month.
    """
    if not is_rankings_day(today, RANKINGS_DAY):
        return None
    year, month = previous_month(today)
    counts = completion_counts_for_month(conn, house_id, year, month)
    ranked = rank_members(counts)
    if not ranked:
        return None

    months_by_member = completion_months(conn, house_id)
    streaks: list[tuple[Optional[str], int]] = []
    for member_id, name, _cnt in counts:
        n = monthly_streak(months_by_member.get(member_id, set()), year, month)
        if n >= 2:
            streaks.append((name, n))
    streaks.sort(key=lambda s: (-s[1], str(s[0])))

    month_label = f"{calendar.month_name[month]} {year}"
    return format_rankings(month_label, ranked, streaks)


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

        total = member_completion_count(self.bot.db, house["house_id"], member["member_id"])
        confirmation = format_completion_confirmation(interaction.user.display_name, name, total)

        # Announce to the house's #chores channel. If it exists and isn't where
        # the command was run, ack privately and post there; otherwise the public
        # interaction response is the confirmation (no duplicate message).
        channel = channels.resolve_house_channel(interaction.guild, "chores")
        if channel is not None and channel.id != interaction.channel_id:
            await interaction.response.send_message(
                f"Recorded — posted the confirmation in {channel.mention}.", ephemeral=True
            )
            try:
                await channel.send(confirmation)
            except discord.Forbidden:
                pass
        else:
            await interaction.response.send_message(confirmation)

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
