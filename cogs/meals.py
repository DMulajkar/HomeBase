import sqlite3
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import channels


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def tally_votes(results: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Sort (name, count) pairs by votes descending, then name for stable ties."""
    return sorted(results, key=lambda nc: (-nc[1], nc[0]))


def format_poll_results(options: list[tuple[str, int]], closed: bool = False) -> str:
    """Render current standings or the final result of a closed poll."""
    header = "🍽️ **Meal poll — final results**" if closed else "🍽️ **Meal poll — current standings**"
    if not options:
        return f"{header}\nNo meals proposed yet."
    lines = [header]
    for name, count in options:
        bar = "█" * count if count else "·"
        lines.append(f"**{name}** — {count} vote{'s' if count != 1 else ''} {bar}")
    return "\n".join(lines)


def format_winner(winner_name: str, vote_count: int, total_votes: int) -> str:
    """Winner announcement posted when a poll is closed."""
    pct = int(vote_count / total_votes * 100) if total_votes else 0
    return (
        f"🎉 **{winner_name}** wins the meal vote with "
        f"{vote_count}/{total_votes} vote{'s' if total_votes != 1 else ''} ({pct}%)!\n"
        f"Time to add ingredients to the grocery list. 🛒"
    )


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meal_polls (
            poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            created_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            created_at TEXT NOT NULL,
            closed_at TEXT,
            winner_option_id INTEGER REFERENCES meal_options(option_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meal_options (
            option_id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL REFERENCES meal_polls(poll_id),
            name TEXT NOT NULL,
            proposed_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            UNIQUE(poll_id, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meal_votes (
            vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL REFERENCES meal_polls(poll_id),
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            option_id INTEGER NOT NULL REFERENCES meal_options(option_id),
            voted_at TEXT NOT NULL,
            UNIQUE(poll_id, member_id)
        )
        """
    )
    conn.commit()


def get_open_poll(conn: sqlite3.Connection, house_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM meal_polls WHERE house_id = ? AND closed_at IS NULL ORDER BY poll_id DESC LIMIT 1",
        (house_id,),
    ).fetchone()


def create_poll(conn: sqlite3.Connection, house_id: int, member_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO meal_polls (house_id, created_by_member_id, created_at) VALUES (?, ?, ?)",
        (house_id, member_id, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def add_option(conn: sqlite3.Connection, poll_id: int, name: str, member_id: int) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO meal_options (poll_id, name, proposed_by_member_id) VALUES (?, ?, ?)",
            (poll_id, name, member_id),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"**{name}** is already in this poll.")


def get_option(conn: sqlite3.Connection, poll_id: int, name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM meal_options WHERE poll_id = ? AND name = ?", (poll_id, name)
    ).fetchone()


def record_vote(conn: sqlite3.Connection, poll_id: int, member_id: int, option_id: int) -> None:
    """Cast or update a vote. One vote per member per poll."""
    conn.execute(
        "INSERT INTO meal_votes (poll_id, member_id, option_id, voted_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(poll_id, member_id) DO UPDATE SET option_id = excluded.option_id, voted_at = excluded.voted_at",
        (poll_id, member_id, option_id, _now_iso()),
    )
    conn.commit()


def get_vote(conn: sqlite3.Connection, poll_id: int, member_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT mv.*, mo.name FROM meal_votes mv "
        "JOIN meal_options mo ON mo.option_id = mv.option_id "
        "WHERE mv.poll_id = ? AND mv.member_id = ?",
        (poll_id, member_id),
    ).fetchone()


def poll_results(conn: sqlite3.Connection, poll_id: int) -> list[tuple[str, int]]:
    """All options with vote counts, sorted by votes desc then name (ties stable)."""
    rows = conn.execute(
        "SELECT mo.name, COUNT(mv.vote_id) AS votes "
        "FROM meal_options mo "
        "LEFT JOIN meal_votes mv ON mv.option_id = mo.option_id "
        "WHERE mo.poll_id = ? "
        "GROUP BY mo.option_id "
        "ORDER BY votes DESC, mo.name",
        (poll_id,),
    ).fetchall()
    return [(r["name"], r["votes"]) for r in rows]


def close_poll(conn: sqlite3.Connection, poll_id: int, winner_option_id: int) -> None:
    conn.execute(
        "UPDATE meal_polls SET closed_at = ?, winner_option_id = ? WHERE poll_id = ?",
        (_now_iso(), winner_option_id, poll_id),
    )
    conn.commit()


def get_winner_option_id(conn: sqlite3.Connection, poll_id: int) -> Optional[int]:
    """Option with the most votes (first proposed breaks ties). None if no votes cast."""
    row = conn.execute(
        "SELECT mo.option_id, COUNT(mv.vote_id) AS votes "
        "FROM meal_options mo "
        "LEFT JOIN meal_votes mv ON mv.option_id = mo.option_id "
        "WHERE mo.poll_id = ? "
        "GROUP BY mo.option_id "
        "ORDER BY votes DESC, mo.option_id ASC "
        "LIMIT 1",
        (poll_id,),
    ).fetchone()
    if row is None or row["votes"] == 0:
        return None
    return row["option_id"]


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


class Meals(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="propose", description="Propose a meal for the house to vote on")
    @app_commands.describe(name="The meal to propose, e.g. Tacos")
    async def meal_propose(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        poll = get_open_poll(self.bot.db, house["house_id"])
        if poll is None:
            poll_id = create_poll(self.bot.db, house["house_id"], member["member_id"])
            started = True
        else:
            poll_id = poll["poll_id"]
            started = False

        try:
            add_option(self.bot.db, poll_id, name, member["member_id"])
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        prefix = "🍽️ Started a new meal poll!" if started else "🍽️ Added to the poll!"
        await interaction.response.send_message(
            f"{prefix} **{name}** is in. Use `/meal-vote` to cast your vote, "
            f"or `/meal-results` to see standings, or `/propose` to add more options."
        )

    @app_commands.command(name="meal-vote", description="Vote for a meal in the current poll")
    @app_commands.describe(name="The meal you want")
    async def meal_vote(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        poll = get_open_poll(self.bot.db, house["house_id"])
        if poll is None:
            await interaction.response.send_message(
                "No meal poll is open right now. Start one with `/meal-propose`.", ephemeral=True
            )
            return

        option = get_option(self.bot.db, poll["poll_id"], name)
        if option is None:
            await interaction.response.send_message(
                f"**{name}** isn't in this poll. See `/meal-results` for options.", ephemeral=True
            )
            return

        prev = get_vote(self.bot.db, poll["poll_id"], member["member_id"])
        record_vote(self.bot.db, poll["poll_id"], member["member_id"], option["option_id"])

        if prev is not None and prev["name"] != name:
            await interaction.response.send_message(
                f"Changed your vote from **{prev['name']}** to **{name}**. 🗳️"
            )
        else:
            await interaction.response.send_message(f"Voted for **{name}**! 🗳️")

    @app_commands.command(name="meal-results", description="Show the current meal poll standings")
    async def meal_results(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        poll = get_open_poll(self.bot.db, house["house_id"])
        if poll is None:
            await interaction.response.send_message(
                "No meal poll is open right now. Start one with `/meal-propose`.", ephemeral=True
            )
            return

        results = poll_results(self.bot.db, poll["poll_id"])
        await interaction.response.send_message(format_poll_results(results))

    @app_commands.command(name="meal-close", description="Close the meal poll and announce the winner")
    async def meal_close(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        poll = get_open_poll(self.bot.db, house["house_id"])
        if poll is None:
            await interaction.response.send_message(
                "No meal poll is open right now.", ephemeral=True
            )
            return

        results = poll_results(self.bot.db, poll["poll_id"])
        if not results:
            await interaction.response.send_message(
                "The poll has no meals yet — add some with `/meal-propose` first.", ephemeral=True
            )
            return

        winner_option_id = get_winner_option_id(self.bot.db, poll["poll_id"])
        if winner_option_id is None:
            await interaction.response.send_message(
                "Nobody has voted yet — cast some votes before closing the poll.", ephemeral=True
            )
            return

        close_poll(self.bot.db, poll["poll_id"], winner_option_id)

        winner_name, winner_votes = results[0]
        total_votes = sum(c for _, c in results)
        final_standings = format_poll_results(results, closed=True)
        announcement = format_winner(winner_name, winner_votes, total_votes)
        message = f"{final_standings}\n\n{announcement}"

        channel = channels.resolve_house_channel(interaction.guild, "groceries")
        if channel is not None and channel.id != interaction.channel_id:
            await interaction.response.send_message(
                f"Poll closed — posted the results in {channel.mention}.", ephemeral=True
            )
            try:
                await channel.send(message)
            except discord.Forbidden:
                pass
        else:
            await interaction.response.send_message(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(Meals(bot))
