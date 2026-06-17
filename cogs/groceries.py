import sqlite3
from datetime import datetime, timezone
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import channels, expenses

# The three shared-supply categories from the roadmap. Kept as a fixed tuple so
# the order is stable in the rendered list and validation is a simple membership
# check (the Discord layer also constrains input via a Literal).
CATEGORIES = ("Food", "Household Supplies", "Cleaning Supplies")


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def group_by_category(items: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Group `(category, name)` pairs into {category: [names]}.

    Categories appear in CATEGORIES order; only non-empty ones are included, and
    an unknown category (shouldn't happen given validation) sorts to the end.
    Names keep the order they arrive in (the DB hands them over sorted).
    """
    grouped: dict[str, list[str]] = {}
    order = {c: i for i, c in enumerate(CATEGORIES)}
    for category, name in sorted(items, key=lambda cn: (order.get(cn[0], len(CATEGORIES)), cn[1])):
        grouped.setdefault(category, []).append(name)
    return grouped


def format_grocery_list(grouped: dict[str, list[str]]) -> str:
    """Render grouped items as a per-category checklist, or an empty-state line."""
    if not grouped:
        return "The grocery list is empty. Add something with `/grocery-add`."
    lines = ["🛒 **Grocery list**"]
    for category, names in grouped.items():
        lines.append(f"\n**{category}**")
        lines.extend(f"- {n}" for n in names)
    return "\n".join(lines)


def format_trip_summary(
    member_name: object,
    items: list[tuple[str, str]],
    amount_cents: Optional[int],
    member_count: int,
) -> str:
    """Trip summary posted by /grocery-done.

    `items` is a list of (category, name) pairs in display order.
    `amount_cents` is the total spend, or None if not provided.
    """
    count = len(items)
    lines = [f"🛒 **{member_name}** did a shopping run and picked up {count} item{'s' if count != 1 else ''}:"]
    grouped = group_by_category(items)
    for category, names in grouped.items():
        lines.append(f"\n**{category}**")
        lines.extend(f"- {n}" for n in names)
    if amount_cents is not None:
        per = amount_cents / member_count / 100
        lines.append(
            f"\n💰 Total: ${amount_cents / 100:.2f} — split ${per:.2f} each across {member_count} member{'s' if member_count != 1 else ''}."
        )
    lines.append("\nThe grocery list has been cleared. 🧹")
    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grocery_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            added_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            created_at TEXT NOT NULL,
            bought_at TEXT,
            bought_by_member_id INTEGER REFERENCES members(member_id)
        )
        """
    )
    # Only one *active* (not-yet-bought) row per name per house. Once an item is
    # bought it leaves the active list, so the same name can be needed again
    # later without colliding — the partial index makes the history additive.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS grocery_items_active_unique "
        "ON grocery_items(house_id, name) WHERE bought_at IS NULL"
    )
    conn.commit()


def add_item(conn: sqlite3.Connection, house_id: int, name: str, category: str, member_id: int) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO grocery_items (house_id, name, category, added_by_member_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (house_id, name, category, member_id, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"'{name}' is already on the grocery list.")


def list_needed(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    """Active (not-yet-bought) items, ordered for display."""
    return conn.execute(
        "SELECT * FROM grocery_items WHERE house_id = ? AND bought_at IS NULL "
        "ORDER BY category, name",
        (house_id,),
    ).fetchall()


def mark_bought(conn: sqlite3.Connection, house_id: int, name: str, member_id: int) -> bool:
    """Mark the active item with this name as bought. False if there isn't one."""
    cur = conn.execute(
        "UPDATE grocery_items SET bought_at = ?, bought_by_member_id = ? "
        "WHERE house_id = ? AND name = ? AND bought_at IS NULL",
        (_now_iso(), member_id, house_id, name),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_item(conn: sqlite3.Connection, house_id: int, name: str) -> bool:
    """Delete the active item with this name (no longer needed). False if none."""
    cur = conn.execute(
        "DELETE FROM grocery_items WHERE house_id = ? AND name = ? AND bought_at IS NULL",
        (house_id, name),
    )
    conn.commit()
    return cur.rowcount > 0


def finish_shopping_run(
    conn: sqlite3.Connection, house_id: int, member_id: int
) -> list[tuple[str, str]]:
    """Mark every active item bought and return them as (category, name) pairs.

    Returns an empty list if the list was already empty (the command handler
    rejects that case before posting anything).
    """
    items = list_needed(conn, house_id)
    if not items:
        return []
    now = _now_iso()
    conn.execute(
        "UPDATE grocery_items SET bought_at = ?, bought_by_member_id = ? "
        "WHERE house_id = ? AND bought_at IS NULL",
        (now, member_id, house_id),
    )
    conn.commit()
    return [(row["category"], row["name"]) for row in items]


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


class Groceries(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="grocery-add", description="Add an item to the shared grocery list")
    @app_commands.describe(name="What to buy, e.g. Milk", category="Which list it belongs on")
    async def grocery_add(
        self,
        interaction: discord.Interaction,
        name: str,
        category: Literal["Food", "Household Supplies", "Cleaning Supplies"],
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        try:
            add_item(self.bot.db, house["house_id"], name, category, member["member_id"])
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Added **{name}** to the grocery list under *{category}*.")

    @app_commands.command(name="groceries", description="Show the shared grocery list")
    async def groceries(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        items = list_needed(self.bot.db, house["house_id"])
        grouped = group_by_category([(it["category"], it["name"]) for it in items])
        await interaction.response.send_message(format_grocery_list(grouped))

    @app_commands.command(name="grocery-bought", description="Mark a grocery item as bought")
    @app_commands.describe(name="The item you bought")
    async def grocery_bought(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if mark_bought(self.bot.db, house["house_id"], name, member["member_id"]):
            await interaction.response.send_message(
                f"✅ {interaction.user.display_name} bought **{name}**. Off the list!"
            )
        else:
            await interaction.response.send_message(
                f"No item named '{name}' on the list. See `/groceries`.", ephemeral=True
            )

    @app_commands.command(name="grocery-remove", description="Remove an item from the grocery list")
    @app_commands.describe(name="The item to remove (no longer needed)")
    async def grocery_remove(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if remove_item(self.bot.db, house["house_id"], name):
            await interaction.response.send_message(f"Removed **{name}** from the grocery list.")
        else:
            await interaction.response.send_message(
                f"No item named '{name}' on the list. See `/groceries`.", ephemeral=True
            )

    @app_commands.command(
        name="grocery-done",
        description="Finish a shopping run — clears the list and optionally splits the cost",
    )
    @app_commands.describe(amount="Total spent in dollars (optional) — split equally among all members")
    async def grocery_done(self, interaction: discord.Interaction, amount: Optional[float] = None):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result

        if amount is not None and amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        bought = finish_shopping_run(self.bot.db, house["house_id"], member["member_id"])
        if not bought:
            await interaction.response.send_message(
                "The grocery list is already empty — nothing to clear.", ephemeral=True
            )
            return

        members = database.list_members(self.bot.db, house["house_id"])
        member_ids = [m["member_id"] for m in members]

        amount_cents: Optional[int] = None
        if amount is not None:
            amount_cents = expenses.dollars_to_cents(amount)
            expenses.record_expense(
                self.bot.db,
                house["house_id"],
                "Groceries shopping run",
                amount_cents,
                member["member_id"],
                member_ids,
            )

        summary = format_trip_summary(
            interaction.user.display_name, bought, amount_cents, len(member_ids)
        )

        channel = channels.resolve_house_channel(interaction.guild, "groceries")
        if channel is not None and channel.id != interaction.channel_id:
            await interaction.response.send_message(
                f"Logged — posted the trip summary in {channel.mention}.", ephemeral=True
            )
            try:
                await channel.send(summary)
            except discord.Forbidden:
                pass
        else:
            await interaction.response.send_message(summary)


async def setup(bot: commands.Bot):
    await bot.add_cog(Groceries(bot))
