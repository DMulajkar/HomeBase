import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import discord
from discord import app_commands
from discord.ext import commands

import database


def dollars_to_cents(amount: float) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value())


def split_amount(amount_cents: int, member_ids: list[int]) -> dict[int, int]:
    n = len(member_ids)
    base = amount_cents // n
    remainder = amount_cents % n
    shares = {}
    for i, member_id in enumerate(member_ids):
        shares[member_id] = base + (1 if i < remainder else 0)
    return shares


def compute_net_balances(
    debts: list[tuple[int, int, int]], payments: list[tuple[int, int, int]]
) -> dict[tuple[int, int], int]:
    net: dict[tuple[int, int], int] = defaultdict(int)
    for ower, payer, cents in debts:
        if ower == payer:
            continue
        net[(ower, payer)] += cents
        net[(payer, ower)] -= cents
    for frm, to, cents in payments:
        net[(frm, to)] -= cents
        net[(to, frm)] += cents

    result: dict[tuple[int, int], int] = {}
    seen: set[tuple[int, int]] = set()
    for (a, b), amount in net.items():
        if (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        if amount > 0:
            result[(a, b)] = amount
        elif amount < 0:
            result[(b, a)] = -amount
    return result


def format_net_balances(net: dict[tuple[int, int], int], names: dict[int, object]) -> list[str]:
    """Render the net-balance map as '<ower> owes <owee> $X.XX' lines."""
    return [
        f"{names.get(ower_id, ower_id)} owes {names.get(owee_id, owee_id)} ${cents / 100:.2f}"
        for (ower_id, owee_id), cents in net.items()
    ]


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            description TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            paid_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expense_splits (
            split_id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_id INTEGER NOT NULL REFERENCES expenses(expense_id),
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            share_cents INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settlements (
            settlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            from_member_id INTEGER NOT NULL REFERENCES members(member_id),
            to_member_id INTEGER NOT NULL REFERENCES members(member_id),
            amount_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def record_expense(
    conn: sqlite3.Connection,
    house_id: int,
    description: str,
    amount_cents: int,
    paid_by_member_id: int,
    member_ids: list[int],
) -> int:
    shares = split_amount(amount_cents, member_ids)
    cur = conn.execute(
        "INSERT INTO expenses (house_id, description, amount_cents, paid_by_member_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (house_id, description, amount_cents, paid_by_member_id, datetime.now(timezone.utc).isoformat()),
    )
    expense_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO expense_splits (expense_id, member_id, share_cents) VALUES (?, ?, ?)",
        [(expense_id, member_id, share) for member_id, share in shares.items()],
    )
    conn.commit()
    return expense_id


def record_settlement(
    conn: sqlite3.Connection, house_id: int, from_member_id: int, to_member_id: int, amount_cents: int
) -> int:
    cur = conn.execute(
        "INSERT INTO settlements (house_id, from_member_id, to_member_id, amount_cents, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (house_id, from_member_id, to_member_id, amount_cents, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def get_debts(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        "SELECT es.member_id AS ower_id, e.paid_by_member_id AS payer_id, es.share_cents AS cents "
        "FROM expense_splits es JOIN expenses e ON es.expense_id = e.expense_id "
        "WHERE e.house_id = ?",
        (house_id,),
    ).fetchall()
    return [(row["ower_id"], row["payer_id"], row["cents"]) for row in rows]


def get_payments(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        "SELECT from_member_id, to_member_id, amount_cents FROM settlements WHERE house_id = ?",
        (house_id,),
    ).fetchall()
    return [(row["from_member_id"], row["to_member_id"], row["amount_cents"]) for row in rows]


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


class Expenses(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="expense", description="Add a shared expense and split it equally")
    @app_commands.describe(
        description="What the expense was for",
        amount="Amount in dollars, e.g. 42.50",
    )
    async def expense(
        self,
        interaction: discord.Interaction,
        description: str,
        amount: float,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        amount_cents = dollars_to_cents(amount)
        members = database.list_members(self.bot.db, house["house_id"])
        member_ids = [m["member_id"] for m in members]
        record_expense(
            self.bot.db, house["house_id"], description, amount_cents, member["member_id"], member_ids
        )

        await interaction.response.send_message(
            f"Added expense '{description}' for ${amount:.2f}, paid by {interaction.user.display_name}, "
            f"split across {len(member_ids)} member(s)."
        )

    @app_commands.command(name="pay", description="Record that you paid someone toward your shared debt")
    @app_commands.describe(amount="Amount in dollars you paid", to="Who you paid")
    async def pay(self, interaction: discord.Interaction, amount: float, to: discord.Member):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return
        if to.id == interaction.user.id:
            await interaction.response.send_message("You can't settle up with yourself.", ephemeral=True)
            return

        to_row = database.get_member(self.bot.db, house["house_id"], str(to.id))
        if to_row is None:
            await interaction.response.send_message(f"{to.display_name} isn't a member of this house.", ephemeral=True)
            return

        amount_cents = dollars_to_cents(amount)
        record_settlement(self.bot.db, house["house_id"], member["member_id"], to_row["member_id"], amount_cents)
        await interaction.response.send_message(f"Recorded: you paid {to.display_name} ${amount:.2f}.")

    @app_commands.command(name="balances", description="Show who owes whom in this house")
    async def balances(self, interaction: discord.Interaction):
        await self._balances_impl(interaction)

    async def _balances_impl(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        debts = get_debts(self.bot.db, house["house_id"])
        payments = get_payments(self.bot.db, house["house_id"])
        net = compute_net_balances(debts, payments)

        if not net:
            await interaction.response.send_message("Everyone is settled up!")
            return

        members = {m["member_id"]: m["display_name"] for m in database.list_members(self.bot.db, house["house_id"])}
        lines = format_net_balances(net, members)
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(Expenses(bot))
