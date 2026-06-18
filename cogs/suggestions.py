import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def format_suggestions_list(rows: list[tuple[int, str]]) -> str:
    """Render all suggestions as a numbered anonymous list.

    rows: list of (number, text) pairs in submission order.
    """
    if not rows:
        return "No suggestions yet. Submit one with `/suggestion`."
    lines = [f"**House suggestions** ({len(rows)} total)", ""]
    for number, text in rows:
        lines.append(f"#{number}: {text}")
    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestions (
            suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def record_suggestion(
    conn: sqlite3.Connection, house_id: int, member_id: int, text: str
) -> int:
    """Insert a suggestion and return its number (1-based count for this house)."""
    conn.execute(
        "INSERT INTO suggestions (house_id, member_id, text, created_at) VALUES (?, ?, ?, ?)",
        (house_id, member_id, text, _now_iso()),
    )
    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM suggestions WHERE house_id = ?", (house_id,)
    ).fetchone()[0]


def suggestion_count(conn: sqlite3.Connection, house_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM suggestions WHERE house_id = ?", (house_id,)
    ).fetchone()[0]


def list_suggestions(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, str]]:
    """Return all suggestions as (number, text) in submission order."""
    rows = conn.execute(
        "SELECT ROW_NUMBER() OVER (ORDER BY suggestion_id) AS number, text "
        "FROM suggestions WHERE house_id = ? ORDER BY suggestion_id",
        (house_id,),
    ).fetchall()
    return [(r["number"], r["text"]) for r in rows]


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


class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(
        name="suggestion",
        description="Submit an anonymous suggestion to the house",
    )
    @app_commands.describe(text="Your suggestion — stored without your name attached")
    async def suggestion(self, interaction: discord.Interaction, text: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        record_suggestion(self.bot.db, house["house_id"], member["member_id"], text)
        await interaction.response.send_message(
            "Your suggestion was recorded anonymously.", ephemeral=True
        )

    @app_commands.command(
        name="suggestions",
        description="Show all anonymous house suggestions",
    )
    async def suggestions(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        rows = list_suggestions(self.bot.db, house["house_id"])
        await interaction.response.send_message(format_suggestions_list(rows))


async def setup(bot: commands.Bot):
    await bot.add_cog(Suggestions(bot))
