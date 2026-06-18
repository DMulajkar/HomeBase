import calendar
import re
import sqlite3
from datetime import date, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure functions ---


def parse_event_date(text: str) -> date:
    """Parse a date string (YYYY-MM-DD). Raises ValueError on bad input."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"Could not parse '{text}' as a date. Use YYYY-MM-DD format, e.g. 2026-12-25.")


def parse_event_time(text: str) -> str:
    """Parse a time string into HH:MM (24h). Accepts '7pm', '7:30pm', '19:00', '7:00'.

    Returns HH:MM string. Raises ValueError on bad input.
    """
    text = text.strip().lower().replace(" ", "")
    # Try 12h formats: 7pm, 7:30pm, 07:30am
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)$', text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        meridiem = m.group(3)
        if hour < 1 or hour > 12 or minute > 59:
            raise ValueError(f"Invalid time '{text}'.")
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    # Try 24h format: 19:00, 07:30
    m = re.match(r'^(\d{1,2}):(\d{2})$', text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"Invalid time '{text}'.")
        return f"{hour:02d}:{minute:02d}"
    raise ValueError(
        f"Could not parse '{text}' as a time. Try formats like '7pm', '7:30pm', or '19:00'."
    )


def format_time_display(hhmm: str) -> str:
    """Convert HH:MM (24h) to '7:00 PM' style."""
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    meridiem = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    if minute:
        return f"{display_hour}:{minute:02d} {meridiem}"
    return f"{display_hour} {meridiem}"


def format_event(row: sqlite3.Row) -> str:
    """Single event line: 'Jun 21 at 7 PM — Dinner with roommates'"""
    event_date = date.fromisoformat(row["date"])
    date_str = event_date.strftime("%b %d")
    time_str = f" at {format_time_display(row['time'])}" if row["time"] else ""
    desc = f" — {row['description']}" if row["description"] else ""
    return f"#{row['event_id']} | {date_str}{time_str} — {row['name']}{desc}"


def format_events_list(rows: list[sqlite3.Row], heading: str) -> str:
    if not rows:
        return f"No events {heading}."
    lines = [f"**House events** ({heading}, {len(rows)} total)", ""]
    for row in rows:
        lines.append(format_event(row))
    return "\n".join(lines)


def render_daily_events(conn: sqlite3.Connection, house_id: int, today: date) -> str | None:
    """Post to #general if there are any events today."""
    rows = get_events_for_date(conn, house_id, today)
    if not rows:
        return None
    if len(rows) == 1:
        row = rows[0]
        time_str = f" at {format_time_display(row['time'])}" if row["time"] else ""
        return f"Today's event: {row['name']}{time_str}"
    lines = ["Events today:"]
    for row in rows:
        time_str = f" at {format_time_display(row['time'])}" if row["time"] else ""
        lines.append(f"  {row['name']}{time_str}")
    return "\n".join(lines)


# --- Layer 2: DB functions ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id    INTEGER NOT NULL REFERENCES houses(house_id),
            member_id   INTEGER NOT NULL REFERENCES members(member_id),
            name        TEXT NOT NULL,
            date        TEXT NOT NULL,
            time        TEXT,
            description TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def create_event(
    conn: sqlite3.Connection,
    house_id: int,
    member_id: int,
    name: str,
    date_str: str,
    time_str: str | None,
    description: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO calendar_events (house_id, member_id, name, date, time, description, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (house_id, member_id, name, date_str, time_str, description, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def get_events_for_date(conn: sqlite3.Connection, house_id: int, target: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM calendar_events WHERE house_id = ? AND date = ? ORDER BY time NULLS LAST, event_id",
        (house_id, target.isoformat()),
    ).fetchall()


def list_upcoming_events(conn: sqlite3.Connection, house_id: int, today: date, days: int = 30) -> list[sqlite3.Row]:
    end = date.fromordinal(today.toordinal() + days)
    return conn.execute(
        "SELECT * FROM calendar_events WHERE house_id = ? AND date >= ? AND date <= ? "
        "ORDER BY date, time NULLS LAST, event_id",
        (house_id, today.isoformat(), end.isoformat()),
    ).fetchall()


def list_events_by_month(
    conn: sqlite3.Connection, house_id: int, year: int, month: int
) -> list[sqlite3.Row]:
    month_key = f"{year:04d}-{month:02d}"
    return conn.execute(
        "SELECT * FROM calendar_events WHERE house_id = ? AND substr(date, 1, 7) = ? "
        "ORDER BY date, time NULLS LAST, event_id",
        (house_id, month_key),
    ).fetchall()


def delete_event(conn: sqlite3.Connection, house_id: int, event_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM calendar_events WHERE event_id = ? AND house_id = ?",
        (event_id, house_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --- Layer 3: Discord plumbing ---


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


_MONTH_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if i}


def _parse_month_arg(text: str) -> tuple[int, int] | None:
    """Parse 'June', 'jun', '6', '2026-06' into (year, month). Returns None on failure."""
    text = text.strip()
    today = datetime.now(timezone.utc).date()
    # YYYY-MM
    m = re.match(r'^(\d{4})-(\d{2})$', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Numeric month
    if text.isdigit():
        month = int(text)
        if 1 <= month <= 12:
            return today.year, month
    # Month name (full or abbreviated)
    lower = text.lower()
    for name, idx in _MONTH_NAMES.items():
        if name.startswith(lower) or lower.startswith(name[:3]):
            return today.year, idx
    return None


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="event-add", description="Add an event to the house calendar")
    @app_commands.describe(
        name="Event name, e.g. 'Dinner with roommates'",
        date="Date in YYYY-MM-DD format, e.g. 2026-07-04",
        time="Optional time, e.g. '7pm', '7:30pm', or '19:00'",
        description="Optional details",
    )
    async def event_add(
        self,
        interaction: discord.Interaction,
        name: str,
        date: str,
        time: str | None = None,
        description: str | None = None,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        try:
            parsed_date = parse_event_date(date)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        parsed_time = None
        if time is not None:
            try:
                parsed_time = parse_event_time(time)
            except ValueError as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return

        event_id = create_event(
            self.bot.db, house["house_id"], member["member_id"],
            name, parsed_date.isoformat(), parsed_time, description,
        )
        time_display = f" at {format_time_display(parsed_time)}" if parsed_time else ""
        await interaction.response.send_message(
            f"Event added (#{event_id}): **{name}** on {parsed_date.strftime('%B %d, %Y')}{time_display}."
        )

    @app_commands.command(name="events", description="View upcoming events or all events in a month")
    @app_commands.describe(month="Optional: month to view, e.g. 'July', '7', or '2026-07'")
    async def events(self, interaction: discord.Interaction, month: str | None = None):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        today = datetime.now(timezone.utc).date()

        if month is not None:
            parsed = _parse_month_arg(month)
            if parsed is None:
                await interaction.response.send_message(
                    f"Could not parse '{month}' as a month. Try 'July', '7', or '2026-07'.", ephemeral=True
                )
                return
            year, month_num = parsed
            rows = list_events_by_month(self.bot.db, house["house_id"], year, month_num)
            heading = f"{calendar.month_name[month_num]} {year}"
        else:
            rows = list_upcoming_events(self.bot.db, house["house_id"], today)
            heading = "next 30 days"

        await interaction.response.send_message(format_events_list(rows, heading))

    @app_commands.command(name="event-remove", description="Remove an event from the calendar by its number")
    @app_commands.describe(event_id="The event number shown in /events")
    async def event_remove(self, interaction: discord.Interaction, event_id: int):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if not delete_event(self.bot.db, house["house_id"], event_id):
            await interaction.response.send_message(
                f"Event #{event_id} not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Event #{event_id} removed.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
