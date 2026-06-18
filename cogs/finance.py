import calendar
import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import expenses
from cogs.settings import get_setting as _get_setting
from cogs.vacation import active_member_ids as _active_member_ids

KINDS = ("fixed", "variable")
REMINDER_LEAD_DAYS = 3  # days before a bill's due date to start reminding
SUMMARY_DAY = 1  # day of the month to post the financial summary


# --- Layer 1: pure functions (unit-tested) ---


def due_date_for_month(year: int, month: int, due_day: int) -> date:
    """The bill's due date for a given month, clamping due_day to month length.

    A bill due on day 31 falls on Feb 28/29 in February, Apr 30 in April, etc.
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, last_day))


def period_key(d: date) -> str:
    """Month identifier used to dedupe postings, e.g. '2026-06'."""
    return f"{d.year:04d}-{d.month:02d}"


def fixed_bill_period_to_post(today: date, due_day: int, start_date: date) -> Optional[str]:
    """Period a fixed bill should post for given today, or None.

    Returns the current month's period key when today has reached this month's
    (clamped) due date AND that due date is on/after start_date — so a bill is
    never back-billed for a month that ended before it existed. The caller still
    checks whether the period was already posted.
    """
    due = due_date_for_month(today.year, today.month, due_day)
    if today < due:
        return None
    if due < start_date:
        return None
    return period_key(today)


def days_until_due(today: date, due_day: int) -> Optional[int]:
    """Whole days from today until this month's (clamped) due date.

    Returns 0 on the due day and None once this month's due date has passed.
    """
    due = due_date_for_month(today.year, today.month, due_day)
    if due < today:
        return None
    return (due - today).days


def is_summary_day(today: date, summary_day: int) -> bool:
    """Whether today is the day of the month to post the financial summary."""
    return today.day == summary_day


# --- Layer 2: DB functions (each takes sqlite3.Connection first) ---


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bills (
            bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('fixed', 'variable')),
            amount_cents INTEGER,
            due_day INTEGER NOT NULL,
            payer_member_id INTEGER NOT NULL REFERENCES members(member_id),
            start_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(house_id, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bill_postings (
            posting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL REFERENCES bills(bill_id),
            period TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            expense_id INTEGER NOT NULL REFERENCES expenses(expense_id),
            posted_at TEXT NOT NULL,
            UNIQUE(bill_id, period)
        )
        """
    )
    conn.commit()


def add_bill(
    conn: sqlite3.Connection,
    house_id: int,
    name: str,
    kind: str,
    amount_cents: Optional[int],
    due_day: int,
    payer_member_id: int,
    start_date: str,
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO bills (house_id, name, kind, amount_cents, due_day, payer_member_id, "
            "start_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                house_id,
                name,
                kind,
                amount_cents,
                due_day,
                payer_member_id,
                start_date,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A bill named '{name}' already exists in this house")


def get_bill(conn: sqlite3.Connection, house_id: int, name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bills WHERE house_id = ? AND name = ?", (house_id, name)
    ).fetchone()


def list_bills(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bills WHERE house_id = ? ORDER BY name", (house_id,)
    ).fetchall()


def remove_bill(conn: sqlite3.Connection, house_id: int, name: str) -> bool:
    """Delete a bill and its posting records. Expenses it created remain."""
    bill = get_bill(conn, house_id, name)
    if bill is None:
        return False
    conn.execute("DELETE FROM bill_postings WHERE bill_id = ?", (bill["bill_id"],))
    conn.execute("DELETE FROM bills WHERE bill_id = ?", (bill["bill_id"],))
    conn.commit()
    return True


def is_posted(conn: sqlite3.Connection, bill_id: int, period: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM bill_postings WHERE bill_id = ? AND period = ?", (bill_id, period)
    ).fetchone()
    return row is not None


def record_posting(
    conn: sqlite3.Connection,
    bill: sqlite3.Row,
    period: str,
    amount_cents: int,
    member_ids: list[int],
) -> int:
    """Post a bill for a period: create the expense and record the posting.

    Reuses expenses.record_expense so the resulting debt flows into the normal
    balance system. Raises ValueError if the period is already posted. Relies on
    the single-threaded event-loop model (per CLAUDE.md) for the
    check-then-insert; there is no cross-thread race.
    """
    if is_posted(conn, bill["bill_id"], period):
        raise ValueError(f"'{bill['name']}' is already posted for {period}")

    description = f"{bill['name']} — {period}"
    expense_id = expenses.record_expense(
        conn,
        bill["house_id"],
        description,
        amount_cents,
        bill["payer_member_id"],
        member_ids,
    )
    conn.execute(
        "INSERT INTO bill_postings (bill_id, period, amount_cents, expense_id, posted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (bill["bill_id"], period, amount_cents, expense_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return expense_id


# --- Layer 3: Discord plumbing ---


def render_due_fixed_bills(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """Post any fixed bills due today and announce them. Deliberate side effect.

    Used as a scheduler ScheduledJob render. Posting is exactly-once per period
    thanks to bill_postings' UNIQUE(bill_id, period) plus the is_posted check in
    record_posting, so repeated ticks never double-charge. Returns the
    announcement text, or None when nothing is due.
    """
    members = database.list_members(conn, house_id)
    active = _active_member_ids(conn, house_id, today)
    member_ids = [m["member_id"] for m in members if m["member_id"] in active]
    if not member_ids:
        return None
    names = {m["member_id"]: m["display_name"] for m in members}

    lines: list[str] = []
    for bill in list_bills(conn, house_id):
        if bill["kind"] != "fixed":
            continue
        period = fixed_bill_period_to_post(
            today, bill["due_day"], date.fromisoformat(bill["start_date"])
        )
        if period is None or is_posted(conn, bill["bill_id"], period):
            continue
        amount_cents = bill["amount_cents"]
        record_posting(conn, bill, period, amount_cents, member_ids)
        payer = names.get(bill["payer_member_id"], "someone")
        lines.append(
            f"• **{bill['name']}** — ${amount_cents / 100:.2f}, paid by {payer}, "
            f"split across {len(member_ids)} member(s)"
        )

    if not lines:
        return None
    return "💸 **Bills due today**\n" + "\n".join(lines)


def render_upcoming_bills(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """List un-posted bills coming due within REMINDER_LEAD_DAYS. No side effects.

    Used as a scheduler ScheduledJob render. Unlike render_due_fixed_bills this
    only reads — it never posts an expense. Bills already posted for the current
    period are omitted (they're no longer "upcoming"). Returns None when nothing
    is in the window or the house has no members.
    """
    members = database.list_members(conn, house_id)
    if not members:
        return None
    names = {m["member_id"]: m["display_name"] for m in members}
    period = period_key(today)

    lines: list[str] = []
    for bill in list_bills(conn, house_id):
        if is_posted(conn, bill["bill_id"], period):
            continue
        days = days_until_due(today, bill["due_day"])
        lead_days = int(_get_setting(conn, house_id, "reminder_lead_days", str(REMINDER_LEAD_DAYS)))
        if days is None or days > lead_days:
            continue
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        amount = f"${bill['amount_cents'] / 100:.2f}" if bill["amount_cents"] is not None else "varies"
        payer = names.get(bill["payer_member_id"], "someone")
        hint = "" if bill["kind"] == "fixed" else " — post with `/bill-post`"
        lines.append(f"• **{bill['name']}** — {amount}, due {when}, paid by {payer}{hint}")

    if not lines:
        return None
    return "🔔 **Upcoming bills**\n" + "\n".join(lines)


def render_monthly_summary(conn: sqlite3.Connection, house_id: int, today: date) -> Optional[str]:
    """Once-a-month outstanding-balance report. No side effects.

    Returns None on every day except SUMMARY_DAY (so the daily scheduler tick
    posts it once a month). Balances are cumulative all-time net, so the report
    is labelled "as of <date>" rather than scoped to one month.
    """
    summary_day = int(_get_setting(conn, house_id, "summary_day", str(SUMMARY_DAY)))
    if not is_summary_day(today, summary_day):
        return None
    members = database.list_members(conn, house_id)
    if not members:
        return None

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    header = f"📊 **Monthly financial summary** (as of {today.isoformat()})"
    if not net:
        return f"{header}\nEveryone is settled up! 🎉"
    names = {m["member_id"]: m["display_name"] for m in members}
    return header + "\n" + "\n".join(expenses.format_net_balances(net, names))


class Finance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="bill-add", description="Define a recurring bill (rent, utilities, etc.)")
    @app_commands.describe(
        name="Name of the bill, e.g. Rent or Electric",
        kind="fixed (same amount, auto-posts) or variable (you enter the amount each month)",
        due_day="Day of the month it's due (1–31)",
        payer="Who fronts the money (the person others owe)",
        amount="Amount in dollars — required for fixed bills",
    )
    async def bill_add(
        self,
        interaction: discord.Interaction,
        name: str,
        kind: str,
        due_day: int,
        payer: discord.Member,
        amount: Optional[float] = None,
    ):
        result = await expenses._get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        kind = kind.lower()
        if kind not in KINDS:
            await interaction.response.send_message(
                "Kind must be `fixed` or `variable`.", ephemeral=True
            )
            return
        if not 1 <= due_day <= 31:
            await interaction.response.send_message(
                "Due day must be between 1 and 31.", ephemeral=True
            )
            return

        amount_cents: Optional[int] = None
        if kind == "fixed":
            if amount is None or amount <= 0:
                await interaction.response.send_message(
                    "Fixed bills need a positive amount.", ephemeral=True
                )
                return
            amount_cents = expenses.dollars_to_cents(amount)

        payer_row = database.get_member(self.bot.db, house["house_id"], str(payer.id))
        if payer_row is None:
            await interaction.response.send_message(
                f"{payer.display_name} isn't a member of this house.", ephemeral=True
            )
            return

        try:
            add_bill(
                self.bot.db,
                house["house_id"],
                name,
                kind,
                amount_cents,
                due_day,
                payer_row["member_id"],
                date.today().isoformat(),
            )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        if kind == "fixed":
            detail = f"${amount:.2f}, auto-posts on day {due_day} each month"
        else:
            detail = f"variable, due day {due_day} — post it with `/bill-post` when it arrives"
        await interaction.response.send_message(
            f"Added bill **{name}** ({detail}), paid by {payer.display_name}."
        )

    @app_commands.command(name="bills", description="List this house's recurring bills")
    async def bills(self, interaction: discord.Interaction):
        result = await expenses._get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        rows = list_bills(self.bot.db, house["house_id"])
        if not rows:
            await interaction.response.send_message(
                "No bills yet. Add one with `/bill-add`.", ephemeral=True
            )
            return

        names = {
            m["member_id"]: m["display_name"]
            for m in database.list_members(self.bot.db, house["house_id"])
        }
        this_period = period_key(date.today())
        lines = []
        for b in rows:
            amount = f"${b['amount_cents'] / 100:.2f}" if b["amount_cents"] is not None else "varies"
            status = "✅ posted" if is_posted(self.bot.db, b["bill_id"], this_period) else "⏳ pending"
            payer = names.get(b["payer_member_id"], "?")
            lines.append(
                f"**{b['name']}** ({b['kind']}) — {amount}, due day {b['due_day']}, "
                f"paid by {payer} · this month: {status}"
            )
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="bill-post", description="Post a bill for the current month")
    @app_commands.describe(
        name="Name of the bill to post",
        amount="Amount in dollars — required for variable bills, optional override for fixed",
    )
    async def bill_post(
        self, interaction: discord.Interaction, name: str, amount: Optional[float] = None
    ):
        result = await expenses._get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        bill = get_bill(self.bot.db, house["house_id"], name)
        if bill is None:
            await interaction.response.send_message(
                f"No bill named '{name}'. See `/bills`.", ephemeral=True
            )
            return

        if amount is not None:
            if amount <= 0:
                await interaction.response.send_message("Amount must be positive.", ephemeral=True)
                return
            amount_cents = expenses.dollars_to_cents(amount)
        elif bill["amount_cents"] is not None:
            amount_cents = bill["amount_cents"]
        else:
            await interaction.response.send_message(
                f"**{name}** is a variable bill — please provide the amount.", ephemeral=True
            )
            return

        members = database.list_members(self.bot.db, house["house_id"])
        today = date.today()
        active = _active_member_ids(self.bot.db, house["house_id"], today)
        member_ids = [m["member_id"] for m in members if m["member_id"] in active]
        period = period_key(today)
        try:
            record_posting(self.bot.db, bill, period, amount_cents, member_ids)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        payer = next(
            (m["display_name"] for m in members if m["member_id"] == bill["payer_member_id"]), "?"
        )
        await interaction.response.send_message(
            f"Posted **{name}** for {period}: ${amount_cents / 100:.2f}, paid by {payer}, "
            f"split across {len(member_ids)} active member(s)."
        )

    @app_commands.command(name="bill-remove", description="Delete a recurring bill definition")
    @app_commands.describe(name="Name of the bill to remove")
    async def bill_remove(self, interaction: discord.Interaction, name: str):
        result = await expenses._get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        if remove_bill(self.bot.db, house["house_id"], name):
            await interaction.response.send_message(
                f"Removed bill **{name}**. Expenses it already created remain."
            )
        else:
            await interaction.response.send_message(
                f"No bill named '{name}'. See `/bills`.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Finance(bot))
