import random
import sqlite3
from datetime import date, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure functions ---


def format_quote(quote_id: int, text: str, submitted_by: str, created_at: str) -> str:
    date_str = created_at[:10]
    return f"#{quote_id} | {date_str} | added by {submitted_by}\n\"{text}\""


def format_quotes_list(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No quotes yet. Save a memorable moment with `/quote`."
    lines = [f"**House quotes** ({len(rows)} total)", ""]
    for row in rows:
        lines.append(format_quote(row["quote_id"], row["text"], row["display_name"], row["created_at"]))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_weekly_quote(conn: sqlite3.Connection, house_id: int, today: date) -> str | None:
    """Post a random quote on Mondays."""
    if today.weekday() != 0:
        return None
    row = get_random_quote(conn, house_id)
    if row is None:
        return None
    return f"Memory of the week:\n\n{format_quote(row['quote_id'], row['text'], row['display_name'], row['created_at'])}"


# --- Layer 2: DB functions ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quotes (
            quote_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id   INTEGER NOT NULL REFERENCES houses(house_id),
            member_id  INTEGER NOT NULL REFERENCES members(member_id),
            text       TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def create_quote(conn: sqlite3.Connection, house_id: int, member_id: int, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO quotes (house_id, member_id, text, created_at) VALUES (?, ?, ?, ?)",
        (house_id, member_id, text, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_quotes(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT q.quote_id, q.text, q.created_at, m.display_name "
        "FROM quotes q JOIN members m ON m.member_id = q.member_id "
        "WHERE q.house_id = ? ORDER BY q.quote_id",
        (house_id,),
    ).fetchall()


def list_quotes_by_member(conn: sqlite3.Connection, house_id: int, member_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT q.quote_id, q.text, q.created_at, m.display_name "
        "FROM quotes q JOIN members m ON m.member_id = q.member_id "
        "WHERE q.house_id = ? AND q.member_id = ? ORDER BY q.quote_id",
        (house_id, member_id),
    ).fetchall()


def get_random_quote(conn: sqlite3.Connection, house_id: int) -> sqlite3.Row | None:
    rows = conn.execute(
        "SELECT q.quote_id, q.text, q.created_at, m.display_name "
        "FROM quotes q JOIN members m ON m.member_id = q.member_id "
        "WHERE q.house_id = ?",
        (house_id,),
    ).fetchall()
    return random.choice(rows) if rows else None


def delete_quote(conn: sqlite3.Connection, house_id: int, quote_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM quotes WHERE quote_id = ? AND house_id = ?", (quote_id, house_id)
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


class Quotes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="quote", description="Save a memorable quote or moment from the house")
    @app_commands.describe(text="The quote or moment to save")
    async def quote(self, interaction: discord.Interaction, text: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        quote_id = create_quote(self.bot.db, house["house_id"], member["member_id"], text)
        await interaction.response.send_message(f"Quote saved as #{quote_id}.", ephemeral=True)

    @app_commands.command(name="quotes", description="View all house quotes, or filter to one member")
    @app_commands.describe(member="Optional: show only quotes added by this member")
    async def quotes(self, interaction: discord.Interaction, member: discord.Member | None = None):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if member is not None:
            member_row = database.get_member(self.bot.db, house["house_id"], str(member.id))
            if member_row is None:
                await interaction.response.send_message(
                    f"{member.display_name} isn't a member of this house.", ephemeral=True
                )
                return
            rows = list_quotes_by_member(self.bot.db, house["house_id"], member_row["member_id"])
        else:
            rows = list_quotes(self.bot.db, house["house_id"])
        await interaction.response.send_message(format_quotes_list(rows))

    @app_commands.command(name="quote-remove", description="Delete a saved quote by its number")
    @app_commands.describe(quote_id="The quote number shown in /quotes")
    async def quote_remove(self, interaction: discord.Interaction, quote_id: int):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if not delete_quote(self.bot.db, house["house_id"], quote_id):
            await interaction.response.send_message(
                f"Quote #{quote_id} not found.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Quote #{quote_id} deleted.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Quotes(bot))
