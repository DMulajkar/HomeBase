import sqlite3
from datetime import date, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database

LEAD_DAYS = 7


# --- Layer 1: pure functions ---


def parse_milestone_date(text: str) -> date:
    """Parse a date string (YYYY-MM-DD). Raises ValueError on bad input."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"Could not parse '{text}' as a date. Use YYYY-MM-DD format, e.g. 2026-12-25.")


def days_until(today: date, milestone_date: date, is_recurring: bool) -> int:
    """Days from today until the next occurrence of a milestone.

    For recurring milestones, rolls to next year if the date has already passed
    this year. For one-time milestones, may be negative (already passed).
    """
    target = milestone_date.replace(year=today.year)
    if is_recurring and target < today:
        target = target.replace(year=today.year + 1)
    return (target - today).days


def _next_occurrence(today: date, milestone_date: date, is_recurring: bool) -> date:
    target = milestone_date.replace(year=today.year)
    if is_recurring and target < today:
        target = target.replace(year=today.year + 1)
    return target


def format_milestone_row(row: sqlite3.Row, today: date) -> str:
    ms_date = date.fromisoformat(row["date"])
    is_recurring = bool(row["is_recurring"])
    d = days_until(today, ms_date, is_recurring)
    recurring_tag = " [annual]" if is_recurring else ""

    if not is_recurring and d < 0:
        when = f"passed {-d} day{'s' if -d != 1 else ''} ago"
    elif d == 0:
        when = "today"
    elif d == 1:
        when = "tomorrow"
    else:
        when = f"in {d} days"

    next_occ = _next_occurrence(today, ms_date, is_recurring)
    desc = f" — {row['description']}" if row["description"] else ""
    return f"{next_occ.strftime('%b %d')} — {row['name']}{desc} ({when}){recurring_tag}"


def format_milestones_list(rows: list[sqlite3.Row], today: date) -> str:
    if not rows:
        return "No milestones yet. Add one with `/milestone-add`."
    sorted_rows = sorted(
        rows,
        key=lambda r: days_until(today, date.fromisoformat(r["date"]), bool(r["is_recurring"]))
    )
    lines = [f"**House milestones** ({len(rows)} total)", ""]
    for row in sorted_rows:
        lines.append(format_milestone_row(row, today))
    return "\n".join(lines)


def render_upcoming_milestones(conn: sqlite3.Connection, house_id: int, today: date) -> str | None:
    """Post to #memories if any milestones are within LEAD_DAYS."""
    rows = get_milestones_near_date(conn, house_id, today, LEAD_DAYS)
    if not rows:
        return None
    lines = ["Upcoming milestones:"]
    for row in rows:
        lines.append(f"  {format_milestone_row(row, today)}")
    return "\n".join(lines)


# --- Layer 2: DB functions ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS milestones (
            milestone_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id      INTEGER NOT NULL REFERENCES houses(house_id),
            member_id     INTEGER NOT NULL REFERENCES members(member_id),
            name          TEXT NOT NULL,
            date          TEXT NOT NULL,
            description   TEXT,
            is_recurring  INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        )
        """
    )
    conn.commit()


def create_milestone(
    conn: sqlite3.Connection,
    house_id: int,
    member_id: int,
    name: str,
    date_str: str,
    description: str | None,
    is_recurring: bool,
) -> int:
    cur = conn.execute(
        "INSERT INTO milestones (house_id, member_id, name, date, description, is_recurring, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (house_id, member_id, name, date_str, description, 1 if is_recurring else 0, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_milestones(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM milestones WHERE house_id = ? ORDER BY date",
        (house_id,),
    ).fetchall()


def get_milestones_near_date(
    conn: sqlite3.Connection, house_id: int, today: date, days_ahead: int
) -> list[sqlite3.Row]:
    """Return milestones whose next occurrence falls within days_ahead days from today."""
    all_rows = list_milestones(conn, house_id)
    result = []
    for row in all_rows:
        ms_date = date.fromisoformat(row["date"])
        d = days_until(today, ms_date, bool(row["is_recurring"]))
        if 0 <= d <= days_ahead:
            result.append(row)
    return sorted(result, key=lambda r: days_until(today, date.fromisoformat(r["date"]), bool(r["is_recurring"])))


def delete_milestone_by_name(conn: sqlite3.Connection, house_id: int, name: str) -> bool:
    cur = conn.execute(
        "DELETE FROM milestones WHERE house_id = ? AND lower(name) = lower(?)",
        (house_id, name),
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


class Milestones(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="milestone-add", description="Add a house milestone or important date")
    @app_commands.describe(
        name="Name of the milestone, e.g. 'House anniversary'",
        date="Date in YYYY-MM-DD format, e.g. 2026-12-25",
        description="Optional details",
        recurring="Whether this repeats every year (default: yes)",
    )
    async def milestone_add(
        self,
        interaction: discord.Interaction,
        name: str,
        date: str,
        description: str | None = None,
        recurring: bool = True,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        try:
            parsed = parse_milestone_date(date)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        create_milestone(
            self.bot.db, house["house_id"], member["member_id"],
            name, parsed.isoformat(), description, recurring,
        )
        recur_note = " (repeats annually)" if recurring else " (one-time)"
        await interaction.response.send_message(
            f"Milestone added: **{name}** on {parsed.strftime('%B %d, %Y')}{recur_note}."
        )

    @app_commands.command(name="milestones", description="View all house milestones and important dates")
    async def milestones(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        rows = list_milestones(self.bot.db, house["house_id"])
        today = datetime.now(timezone.utc).date()
        await interaction.response.send_message(format_milestones_list(rows, today))

    @app_commands.command(name="milestone-remove", description="Delete a house milestone")
    @app_commands.describe(name="Name of the milestone to remove")
    async def milestone_remove(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if not delete_milestone_by_name(self.bot.db, house["house_id"], name):
            await interaction.response.send_message(
                f"No milestone named '{name}' found.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Milestone '{name}' removed.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Milestones(bot))
