import calendar
import sqlite3
from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure functions (no I/O, unit-tested) ---

_PARSE_FORMATS = ["%B %d", "%b %d", "%m/%d", "%m-%d"]


def parse_birthday(text: str) -> tuple[int, int]:
    """Parse a birthday string into (month, day). Raises ValueError on bad input."""
    text = text.strip()
    for fmt in _PARSE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.month, dt.day
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse '{text}' as a birthday. "
        "Try formats like 'March 15', '3/15', or '03-15'."
    )


def month_day_label(month: int, day: int) -> str:
    """Human-readable label, e.g. 'March 15'."""
    return f"{calendar.month_name[month]} {day}"


def format_birthday_list(entries: list[tuple[str, int, int]]) -> str:
    """Render all birthdays sorted by month then day.

    entries: list of (display_name, month, day)
    """
    if not entries:
        return "No birthdays on record. Members can add theirs with `/birthday-set`."
    sorted_entries = sorted(entries, key=lambda e: (e[1], e[2]))
    lines = [f"**House birthdays** ({len(sorted_entries)} total)", ""]
    for name, month, day in sorted_entries:
        lines.append(f"{month_day_label(month, day)} — {name}")
    return "\n".join(lines)


def render_birthday_reminder(conn: sqlite3.Connection, house_id: int, today: date) -> str | None:
    """Return a birthday message if any member's birthday is today, else None."""
    rows = get_todays_birthdays(conn, house_id, today)
    if not rows:
        return None
    names = [r["display_name"] for r in rows]
    if len(names) == 1:
        return f"Happy birthday, {names[0]}! Wish them a great one."
    joined = ", ".join(names[:-1]) + f", and {names[-1]}"
    return f"Happy birthday to {joined} today!"


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS member_birthdays (
            member_id INTEGER PRIMARY KEY REFERENCES members(member_id),
            birth_month INTEGER NOT NULL,
            birth_day INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def set_birthday(conn: sqlite3.Connection, member_id: int, month: int, day: int) -> None:
    conn.execute(
        "INSERT INTO member_birthdays (member_id, birth_month, birth_day) VALUES (?, ?, ?) "
        "ON CONFLICT(member_id) DO UPDATE SET birth_month = excluded.birth_month, birth_day = excluded.birth_day",
        (member_id, month, day),
    )
    conn.commit()


def get_birthday(conn: sqlite3.Connection, member_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM member_birthdays WHERE member_id = ?", (member_id,)
    ).fetchone()


def list_birthdays(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    """All members with a birthday on record, ordered by month then day."""
    return conn.execute(
        "SELECT m.display_name, b.birth_month, b.birth_day "
        "FROM member_birthdays b "
        "JOIN members m ON m.member_id = b.member_id "
        "WHERE m.house_id = ? "
        "ORDER BY b.birth_month, b.birth_day",
        (house_id,),
    ).fetchall()


def get_todays_birthdays(
    conn: sqlite3.Connection, house_id: int, today: date
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT m.display_name, b.birth_month, b.birth_day "
        "FROM member_birthdays b "
        "JOIN members m ON m.member_id = b.member_id "
        "WHERE m.house_id = ? AND b.birth_month = ? AND b.birth_day = ?",
        (house_id, today.month, today.day),
    ).fetchall()


# --- Layer 3: Discord plumbing ---


class BirthdayModal(discord.ui.Modal, title="Add your birthday"):
    birthday_input = discord.ui.TextInput(
        label="Birthday",
        placeholder="e.g. March 15  or  3/15  or  03-15",
        required=True,
        max_length=20,
    )

    def __init__(self, bot: commands.Bot, member_id: int):
        super().__init__()
        self.bot = bot
        self.member_id = member_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            month, day = parse_birthday(self.birthday_input.value)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        set_birthday(self.bot.db, self.member_id, month, day)
        label = month_day_label(month, day)
        await interaction.response.send_message(
            f"Birthday set to {label}. You can update it any time with `/birthday-set`.",
            ephemeral=True,
        )


class BirthdayPromptView(discord.ui.View):
    """Shown as an ephemeral follow-up after /join-house to ask about birthday."""

    def __init__(self, bot: commands.Bot, member_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.member_id = member_id

    @discord.ui.button(label="Add birthday", style=discord.ButtonStyle.primary)
    async def add_birthday(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal(self.bot, self.member_id))
        self.stop()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="No problem — you can add your birthday any time with `/birthday-set`.",
            view=None,
        )
        self.stop()


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


class Birthdays(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="birthday-set", description="Set or update your birthday")
    async def birthday_set(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        _, member = result
        await interaction.response.send_modal(BirthdayModal(self.bot, member["member_id"]))

    @app_commands.command(name="birthdays", description="Show all house members' birthdays")
    async def birthdays(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        rows = list_birthdays(self.bot.db, house["house_id"])
        entries = [(r["display_name"], r["birth_month"], r["birth_day"]) for r in rows]
        await interaction.response.send_message(format_birthday_list(entries))


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthdays(bot))
