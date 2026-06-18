import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def is_on_vacation(start_date: str, end_date: Optional[str], today: date) -> bool:
    """True if `today` falls within [start_date, end_date] (inclusive).

    An open-ended vacation (end_date=None) is active until explicitly ended.
    """
    start = date.fromisoformat(start_date)
    if today < start:
        return False
    if end_date is None:
        return True
    return today <= date.fromisoformat(end_date)


def _fmt_date(d: date) -> str:
    import calendar
    return f"{calendar.month_name[d.month]} {d.day}"


def format_vacation_list(entries: list[tuple[str, str, Optional[str]]]) -> str:
    """Render the list of current vacationers.

    entries: list of (display_name, start_date_iso, end_date_iso_or_None)
    """
    if not entries:
        return "No one is on vacation right now."
    lines = [f"**Members on vacation** ({len(entries)} total)", ""]
    for name, start, end in entries:
        since = _fmt_date(date.fromisoformat(start))
        if end:
            back = _fmt_date(date.fromisoformat(end))
            lines.append(f"{name} — since {since}, returns {back}")
        else:
            lines.append(f"{name} — since {since} (no return date set)")
    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vacations (
            vacation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            start_date TEXT NOT NULL,
            end_date TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_active_vacation(
    conn: sqlite3.Connection, member_id: int, today: date
) -> Optional[sqlite3.Row]:
    """Return the current open vacation row for a member, or None."""
    rows = conn.execute(
        "SELECT * FROM vacations WHERE member_id = ? ORDER BY vacation_id DESC",
        (member_id,),
    ).fetchall()
    for row in rows:
        if is_on_vacation(row["start_date"], row["end_date"], today):
            return row
    return None


def start_vacation(
    conn: sqlite3.Connection,
    house_id: int,
    member_id: int,
    start: date,
    end: Optional[date] = None,
) -> None:
    """Record a vacation. Raises ValueError if member is already on vacation."""
    if get_active_vacation(conn, member_id, start) is not None:
        raise ValueError("This member is already on vacation.")
    conn.execute(
        "INSERT INTO vacations (house_id, member_id, start_date, end_date, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            house_id,
            member_id,
            start.isoformat(),
            end.isoformat() if end else None,
            _now_iso(),
        ),
    )
    conn.commit()


def end_vacation(conn: sqlite3.Connection, member_id: int, today: date) -> bool:
    """Set end_date to today on the active vacation. Returns False if not on vacation."""
    row = get_active_vacation(conn, member_id, today)
    if row is None:
        return False
    conn.execute(
        "UPDATE vacations SET end_date = ? WHERE vacation_id = ?",
        (today.isoformat(), row["vacation_id"]),
    )
    conn.commit()
    return True


def list_active_vacations(
    conn: sqlite3.Connection, house_id: int, today: date
) -> list[sqlite3.Row]:
    """All members currently on vacation, with their display names."""
    members = database.list_members(conn, house_id)
    result = []
    for m in members:
        v = get_active_vacation(conn, m["member_id"], today)
        if v is not None:
            result.append((m["display_name"], v["start_date"], v["end_date"]))
    return result


def active_member_ids(conn: sqlite3.Connection, house_id: int, today: date) -> set[int]:
    """IDs of members who are NOT currently on vacation.

    Calls init_tables so it is safe to call even when the vacation cog hasn't
    been loaded yet (e.g. in tests that only set up chores or finance tables).
    """
    init_tables(conn)
    members = database.list_members(conn, house_id)
    active: set[int] = set()
    for m in members:
        if get_active_vacation(conn, m["member_id"], today) is None:
            active.add(m["member_id"])
    return active


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


def _parse_date(text: str) -> date:
    """Parse YYYY-MM-DD. Raises ValueError with a friendly message on bad input."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"Could not parse '{text}' as a date. Use YYYY-MM-DD, e.g. 2026-07-10.")


class Vacation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(
        name="vacation-start",
        description="Put yourself in vacation mode",
    )
    @app_commands.describe(
        end="Return date in YYYY-MM-DD (optional — leave blank for open-ended)",
    )
    async def vacation_start(
        self,
        interaction: discord.Interaction,
        end: str | None = None,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        today = datetime.now(timezone.utc).date()
        end_date: Optional[date] = None
        if end:
            try:
                end_date = _parse_date(end)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
            if end_date < today:
                await interaction.response.send_message(
                    "Return date can't be in the past.", ephemeral=True
                )
                return

        try:
            start_vacation(self.bot.db, house["house_id"], member["member_id"], today, end_date)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        name = interaction.user.display_name
        if end_date:
            msg = f"{name} is on vacation until {_fmt_date(end_date)}. You'll be skipped in chores and bill splits."
        else:
            msg = f"{name} is on vacation. You'll be skipped in chores and bill splits until `/vacation-end` is run."
        await interaction.response.send_message(msg)

    @app_commands.command(
        name="vacation-end",
        description="End your vacation and return to the house rotation",
    )
    async def vacation_end(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        _, member = result

        today = datetime.now(timezone.utc).date()
        ended = end_vacation(self.bot.db, member["member_id"], today)
        if not ended:
            await interaction.response.send_message(
                "You're not currently on vacation.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{interaction.user.display_name} is back! You'll be included in chores and bill splits again."
        )

    @app_commands.command(name="vacations", description="Show who is currently on vacation")
    async def vacations(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        today = datetime.now(timezone.utc).date()
        entries = list_active_vacations(self.bot.db, house["house_id"], today)
        await interaction.response.send_message(format_vacation_list(entries))


async def setup(bot: commands.Bot):
    await bot.add_cog(Vacation(bot))
