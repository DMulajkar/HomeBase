import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import channels


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


def net_between(net: dict[tuple[int, int], int], a: int, b: int) -> int:
    """Cents `a` owes `b` from a net-balance map.

    Positive if `a` owes `b`, negative if `b` owes `a`, 0 if settled between them.
    """
    if (a, b) in net:
        return net[(a, b)]
    if (b, a) in net:
        return -net[(b, a)]
    return 0


def format_payment_confirmation(
    from_name: object, to_name: object, amount_cents: int, net_after_cents: int
) -> str:
    """Public confirmation posted after a payment.

    `net_after_cents` is what `from_name` still owes `to_name` afterward; a
    negative value means the payment overshot and `to_name` now owes `from_name`.
    """
    paid = f"💸 **{from_name}** paid **{to_name}** ${amount_cents / 100:.2f}."
    if net_after_cents > 0:
        return f"{paid} {from_name} still owes {to_name} ${net_after_cents / 100:.2f}."
    if net_after_cents < 0:
        return f"{paid} {to_name} now owes {from_name} ${-net_after_cents / 100:.2f}."
    return f"{paid} They're all settled up! 🎉"


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


def get_ledger_entries(
    conn: sqlite3.Connection, house_id: int, member_id: int
) -> list[sqlite3.Row]:
    """Expenses where member_id was charged (appears in splits) but did not pay."""
    return conn.execute(
        """
        SELECT e.description, e.created_at, e.paid_by_member_id, es.share_cents
        FROM expense_splits es
        JOIN expenses e ON es.expense_id = e.expense_id
        WHERE e.house_id = ?
          AND es.member_id = ?
          AND e.paid_by_member_id != ?
        ORDER BY e.created_at DESC
        """,
        (house_id, member_id, member_id),
    ).fetchall()


def format_ledger(entries: list[sqlite3.Row], member_names: dict[int, str]) -> str:
    if not entries:
        return "Nothing here — no one has charged you for anything yet."
    lines = []
    for row in entries:
        date = row["created_at"][:10]
        payer = member_names.get(row["paid_by_member_id"], "someone")
        amount = f"${row['share_cents'] / 100:.2f}"
        lines.append(f"{date}  {payer} — {row['description']} ({amount})")
    return "\n".join(lines)


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

    @app_commands.command(
        name="expense",
        description="Add a shared expense (split equally, or charged entirely to one person)",
    )
    @app_commands.describe(
        description="What the expense was for",
        amount="Amount in dollars, e.g. 42.50",
        charge_to="Optional: charge the whole amount to this member instead of splitting it",
    )
    async def expense(
        self,
        interaction: discord.Interaction,
        description: str,
        amount: float,
        charge_to: discord.Member | None = None,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        amount_cents = dollars_to_cents(amount)

        if charge_to is not None:
            if charge_to.id == interaction.user.id:
                await interaction.response.send_message(
                    "Charging an expense to yourself has no effect.", ephemeral=True
                )
                return
            to_row = database.get_member(self.bot.db, house["house_id"], str(charge_to.id))
            if to_row is None:
                await interaction.response.send_message(
                    f"{charge_to.display_name} isn't a member of this house.", ephemeral=True
                )
                return
            # A single-member split puts the whole amount on that one person's
            # debt to the payer (you) — nothing is shared with the rest of the house.
            record_expense(
                self.bot.db,
                house["house_id"],
                description,
                amount_cents,
                member["member_id"],
                [to_row["member_id"]],
            )
            await interaction.response.send_message(
                f"Charged '{description}' (${amount:.2f}) entirely to {charge_to.display_name}, "
                f"paid by {interaction.user.display_name} — {charge_to.display_name} owes you ${amount:.2f}."
            )
            return

        members = database.list_members(self.bot.db, house["house_id"])
        member_ids = [m["member_id"] for m in members]
        record_expense(
            self.bot.db, house["house_id"], description, amount_cents, member["member_id"], member_ids
        )

        await interaction.response.send_message(
            f"Added expense '{description}' for ${amount:.2f}, paid by {interaction.user.display_name}, "
            f"split across {len(member_ids)} member(s)."
        )

    @app_commands.command(
        name="pay",
        description="Record a payment toward your shared debt (omit amount to settle in full)",
    )
    @app_commands.describe(
        to="Who you paid",
        amount="Amount in dollars you paid; leave blank to settle your whole balance with them",
    )
    async def pay(
        self, interaction: discord.Interaction, to: discord.Member, amount: float | None = None
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if to.id == interaction.user.id:
            await interaction.response.send_message("You can't settle up with yourself.", ephemeral=True)
            return

        to_row = database.get_member(self.bot.db, house["house_id"], str(to.id))
        if to_row is None:
            await interaction.response.send_message(f"{to.display_name} isn't a member of this house.", ephemeral=True)
            return

        if amount is not None:
            if amount <= 0:
                await interaction.response.send_message("Amount must be positive.", ephemeral=True)
                return
            amount_cents = dollars_to_cents(amount)
        else:
            # No amount given: settle the full balance you currently owe them.
            net_before = compute_net_balances(
                get_debts(self.bot.db, house["house_id"]), get_payments(self.bot.db, house["house_id"])
            )
            amount_cents = net_between(net_before, member["member_id"], to_row["member_id"])
            if amount_cents <= 0:
                await interaction.response.send_message(
                    f"You don't owe {to.display_name} anything to settle.", ephemeral=True
                )
                return

        record_settlement(self.bot.db, house["house_id"], member["member_id"], to_row["member_id"], amount_cents)

        net = compute_net_balances(
            get_debts(self.bot.db, house["house_id"]), get_payments(self.bot.db, house["house_id"])
        )
        net_after = net_between(net, member["member_id"], to_row["member_id"])
        confirmation = format_payment_confirmation(
            interaction.user.display_name, to.display_name, amount_cents, net_after
        )

        # Announce to the house's finance channel. If it exists and isn't where
        # the command was run, ack privately and post there; otherwise the public
        # interaction response is the confirmation (no duplicate message).
        channel = channels.resolve_house_channel(interaction.guild, "rent-and-utilities")
        if channel is not None and channel.id != interaction.channel_id:
            await interaction.response.send_message(
                f"Recorded — posted the confirmation in {channel.mention}.", ephemeral=True
            )
            try:
                await channel.send(confirmation)
            except discord.Forbidden:
                pass
        else:
            await interaction.response.send_message(confirmation)

    @app_commands.command(name="ledger", description="See every expense you've been charged for, with descriptions and dates")
    async def ledger(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        entries = get_ledger_entries(self.bot.db, house["house_id"], member["member_id"])
        member_names = {m["member_id"]: m["display_name"] for m in database.list_members(self.bot.db, house["house_id"])}
        text = format_ledger(entries, member_names)
        await interaction.response.send_message(f"**Your ledger:**\n```\n{text}\n```", ephemeral=True)

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
