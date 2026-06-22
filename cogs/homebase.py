import sqlite3
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import qrcode

import database
from cogs.chores import current_period_index, get_completion, list_chores
from cogs.finance import REMINDER_LEAD_DAYS, days_until_due, is_posted, list_bills, period_key
from cogs.groceries import list_needed
from cogs.settings import get_setting as _get_setting


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def compute_house_health(
    bills_overdue: int, bills_due_soon: int, chores_pending: int
) -> int:
    """Score from 0–100. Deducts for overdue bills, upcoming bills, and pending chores."""
    score = 100 - (bills_overdue * 15) - (bills_due_soon * 5) - (chores_pending * 3)
    return max(0, score)


def top_priority(
    urgent_bill_name: Optional[str],
    urgent_bill_days: Optional[int],
    chores_pending: int,
    groceries_needed: int,
) -> str:
    """One-line description of the most important thing to do right now."""
    if urgent_bill_name is not None:
        if urgent_bill_days is None:
            return f"Post the {urgent_bill_name} bill — it's past due."
        if urgent_bill_days == 0:
            return f"{urgent_bill_name} is due today."
        return f"{urgent_bill_name} is due in {urgent_bill_days} day{'s' if urgent_bill_days != 1 else ''}."
    if chores_pending > 0:
        return f"{chores_pending} chore{'s' if chores_pending != 1 else ''} still need to be done."
    if groceries_needed > 5:
        return f"The grocery list has {groceries_needed} items waiting."
    return "Everything is on track."


def format_homebase(
    bills_due: int,
    chores_pending: int,
    groceries_needed: int,
    health: int,
    priority: str,
) -> str:
    lines = [
        "**HomeBase**",
        "",
        f"Bills due:        {bills_due}",
        f"Chores pending:   {chores_pending}",
        f"Groceries needed: {groceries_needed}",
        "",
        f"House health: {health}/100",
        "",
        f"Top priority: {priority}",
    ]
    return "\n".join(lines)


# --- Layer 2: DB aggregation (conn first arg, unit-tested) ---


def gather_status(conn: sqlite3.Connection, house_id: int, today: date) -> dict:
    """Query every relevant cog table and return a flat status dict."""
    # Chores: count how many are not yet done this period
    chores_pending = 0
    for c in list_chores(conn, house_id):
        start = date.fromisoformat(c["start_date"])
        pidx = current_period_index(c["cadence"], start, today)
        if get_completion(conn, c["chore_id"], pidx) is None:
            chores_pending += 1

    # Bills: find the most urgent unpaid bill and total counts
    period = period_key(today)
    bills_overdue = 0
    bills_due_soon = 0
    urgent_bill_name: Optional[str] = None
    urgent_bill_days: Optional[int] = None  # None = overdue, int = days until due

    lead_days = int(_get_setting(conn, house_id, "reminder_lead_days", str(REMINDER_LEAD_DAYS)))
    for bill in list_bills(conn, house_id):
        if is_posted(conn, bill["bill_id"], period):
            continue
        days = days_until_due(today, bill["due_day"])
        if days is None:
            bills_overdue += 1
            if urgent_bill_name is None:
                urgent_bill_name = bill["name"]
                urgent_bill_days = None
        elif days <= lead_days:
            bills_due_soon += 1
            if urgent_bill_name is None or (
                urgent_bill_days is not None and days < urgent_bill_days
            ):
                urgent_bill_name = bill["name"]
                urgent_bill_days = days

    # Groceries: count active items
    groceries_needed = len(list_needed(conn, house_id))

    return {
        "bills_overdue": bills_overdue,
        "bills_due_soon": bills_due_soon,
        "chores_pending": chores_pending,
        "groceries_needed": groceries_needed,
        "urgent_bill_name": urgent_bill_name,
        "urgent_bill_days": urgent_bill_days,
    }


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


class HomeBase(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.venmo_qr = self._generate_venmo_qr()

    def _generate_venmo_qr(self) -> BytesIO:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data("https://venmo.com/u/DhruvMulajkar")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    @app_commands.command(name="homebase", description="At-a-glance status of the whole house")
    async def homebase(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        today = datetime.now(timezone.utc).date()
        status = gather_status(self.bot.db, house["house_id"], today)

        bills_due = status["bills_overdue"] + status["bills_due_soon"]
        health = compute_house_health(
            status["bills_overdue"], status["bills_due_soon"], status["chores_pending"]
        )
        priority = top_priority(
            status["urgent_bill_name"],
            status["urgent_bill_days"],
            status["chores_pending"],
            status["groceries_needed"],
        )

        embed = discord.Embed(
            title="HomeBase",
            description=format_homebase(
                bills_due,
                status["chores_pending"],
                status["groceries_needed"],
                health,
                priority,
            ),
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="donate", description="Support HomeBase development")
    async def donate(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Support HomeBase",
            description="Love managing your house with HomeBase? Support its development and keep it running!",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Venmo",
            value="https://venmo.com/u/DhruvMulajkar",
            inline=False,
        )

        self.venmo_qr.seek(0)
        qr_file = discord.File(self.venmo_qr, filename="venmo_qr.png")
        embed.set_image(url="attachment://venmo_qr.png")

        await interaction.response.send_message(embed=embed, file=qr_file)


async def setup(bot: commands.Bot):
    await bot.add_cog(HomeBase(bot))
