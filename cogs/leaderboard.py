import calendar
import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import chores, groceries

# Points awarded per contribution type.
POINTS_PER_CHORE = 1
POINTS_PER_GROCERY_RUN = 2  # grocery runs take more effort than a single chore


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def compute_scores(
    chore_counts: list[tuple[int, Optional[str], int]],
    grocery_run_counts: dict[int, int],
) -> list[tuple[int, Optional[str], int]]:
    """Combine chore completions and grocery runs into a ranked score list.

    `chore_counts` is `(member_id, name, count)` from completion_counts_for_month.
    `grocery_run_counts` maps member_id -> number of grocery runs that month.

    Returns `(rank, name, score)` sorted by score desc, standard competition
    ranking for ties. Members with zero score are excluded.
    """
    totals: dict[int, tuple[Optional[str], int]] = {}
    for member_id, name, chore_count in chore_counts:
        score = chore_count * POINTS_PER_CHORE + grocery_run_counts.get(member_id, 0) * POINTS_PER_GROCERY_RUN
        totals[member_id] = (name, score)

    nonzero = sorted(
        [(name, score) for _, (name, score) in totals.items() if score > 0],
        key=lambda ns: -ns[1],
    )

    ranked: list[tuple[int, Optional[str], int]] = []
    prev_score: Optional[int] = None
    prev_rank = 0
    for i, (name, score) in enumerate(nonzero, start=1):
        if score != prev_score:
            prev_rank = i
            prev_score = score
        ranked.append((prev_rank, name, score))

    return ranked


def _medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def format_leaderboard(month_label: str, ranked: list[tuple[int, Optional[str], int]]) -> str:
    """Render the combined leaderboard post."""
    if not ranked:
        return f"🏆 **{month_label} Rankings**\nNo contributions recorded yet."
    lines = [f"🏆 **{month_label} Rankings**"]
    for rank, name, score in ranked:
        lines.append(f"{_medal(rank)} {name} — {score} pts")
    lines.append(f"\n_{POINTS_PER_CHORE} pt per chore · {POINTS_PER_GROCERY_RUN} pts per grocery run_")
    return "\n".join(lines)


# --- Layer 2: DB helpers (conn first, unit-tested) ---


def grocery_run_counts_for_month(
    conn: sqlite3.Connection, house_id: int, year: int, month: int
) -> dict[int, int]:
    """Map member_id -> number of grocery runs they did in the given month."""
    runs = groceries.grocery_runs_for_month(conn, house_id, year, month)
    counts: dict[int, int] = {}
    for r in runs:
        counts[r["member_id"]] = counts.get(r["member_id"], 0) + 1
    return counts


# --- Scheduler render ---


def render_monthly_leaderboard(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """Cross-system monthly leaderboard posted to #chores on the 1st.

    Summarizes the month that just ended. Returns None off-day or when nobody
    scored any points.
    """
    if today.day != 1:
        return None
    year = today.year - 1 if today.month == 1 else today.year
    month = 12 if today.month == 1 else today.month - 1
    month_label = f"{calendar.month_name[month]} {year}"

    chore_counts = chores.completion_counts_for_month(conn, house_id, year, month)
    run_counts = grocery_run_counts_for_month(conn, house_id, year, month)
    ranked = compute_scores(chore_counts, run_counts)
    if not ranked:
        return None
    return format_leaderboard(month_label, ranked)


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


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Show this month's contribution rankings")
    async def leaderboard(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        today = datetime.now(timezone.utc).date()
        month_label = f"{calendar.month_name[today.month]} {today.year}"

        chore_counts = chores.completion_counts_for_month(
            self.bot.db, house["house_id"], today.year, today.month
        )
        run_counts = grocery_run_counts_for_month(
            self.bot.db, house["house_id"], today.year, today.month
        )
        ranked = compute_scores(chore_counts, run_counts)
        await interaction.response.send_message(format_leaderboard(month_label, ranked))


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
