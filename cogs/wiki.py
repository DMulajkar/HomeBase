import sqlite3
from datetime import datetime, timezone
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs import channels as channels_cog


CATEGORIES = (
    "Access & Security",
    "Utilities & Services",
    "Building & Maintenance",
    "House Rules",
    "Lease & Legal",
    "General",
)

# Pre-populated entries for /wiki-setup. Each tuple is (key, category, placeholder).
# Placeholders are only inserted when no entry exists for that key yet.
SETUP_ENTRIES: list[tuple[str, str, str]] = [
    # Access & Security
    ("building entry code",    "Access & Security",    "(not set)"),
    ("storage unit",           "Access & Security",    "(not set)"),
    ("mailbox",                "Access & Security",    "(not set)"),
    ("alarm code",             "Access & Security",    "(not set)"),
    ("gate code",              "Access & Security",    "(not set)"),
    # Utilities & Services
    ("trash pickup day",       "Utilities & Services", "(not set)"),
    ("recycling rules",        "Utilities & Services", "(not set)"),
    ("water shutoff location", "Utilities & Services", "(not set)"),
    ("circuit breaker",        "Utilities & Services", "(not set)"),
    ("thermostat rules",       "Utilities & Services", "(not set)"),
    ("isp account number",     "Utilities & Services", "(not set)"),
    ("router login",           "Utilities & Services", "(not set)"),
    # Building & Maintenance
    ("maintenance contact",    "Building & Maintenance", "(not set)"),
    ("property manager",       "Building & Maintenance", "(not set)"),
    ("landlord contact",       "Building & Maintenance", "(not set)"),
    ("plumber contact",        "Building & Maintenance", "(not set)"),
    ("electrician contact",    "Building & Maintenance", "(not set)"),
    ("package delivery",       "Building & Maintenance", "(not set)"),
    # House Rules
    ("quiet hours",            "House Rules",          "(not set)"),
    ("guest policy",           "House Rules",          "(not set)"),
    ("cleaning schedule",      "House Rules",          "(not set)"),
    ("dishwasher rule",        "House Rules",          "(not set)"),
    ("laundry instructions",   "House Rules",          "(not set)"),
    # Lease & Legal
    ("lease end date",         "Lease & Legal",        "(not set)"),
    ("rent due date",          "Lease & Legal",        "(not set)"),
    ("security deposit",       "Lease & Legal",        "(not set)"),
    ("lease location",         "Lease & Legal",        "(not set)"),
    ("renters insurance",      "Lease & Legal",        "(not set)"),
]


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def normalize_key(key: str) -> str:
    """Lowercase and strip a key so lookups are case-insensitive."""
    return key.strip().lower()


def format_entry(key: str, value: str, category: str) -> str:
    return f"**{key}** _(_{category}_)_\n{value}"


def group_by_category(
    entries: list[tuple[str, str, str]]
) -> dict[str, list[tuple[str, str]]]:
    """Group `(key, value, category)` triples into {category: [(key, value)]}.

    Categories appear in CATEGORIES order; only non-empty categories are included.
    """
    order = {c: i for i, c in enumerate(CATEGORIES)}
    grouped: dict[str, list[tuple[str, str]]] = {}
    for key, value, category in sorted(
        entries, key=lambda e: (order.get(e[2], len(CATEGORIES)), e[0])
    ):
        grouped.setdefault(category, []).append((key, value))
    return grouped


def format_wiki_list(entries: list[tuple[str, str, str]]) -> str:
    """Render all entries grouped by category."""
    if not entries:
        return "The house wiki is empty. Add something with `/wiki-set`, or run `/wiki-setup` to pre-populate common entries."
    grouped = group_by_category(entries)
    lines = ["📖 **House wiki**"]
    for category, items in grouped.items():
        lines.append(f"\n**{category}**")
        for key, value in items:
            lines.append(f"• **{key}**: {value}")
    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_entries (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            set_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            updated_at TEXT NOT NULL,
            UNIQUE(house_id, key)
        )
        """
    )
    # Upgrade existing installs that predate the category column.
    try:
        conn.execute("ALTER TABLE wiki_entries ADD COLUMN category TEXT NOT NULL DEFAULT 'General'")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Tracks the single live message posted into #wiki per house so it can be
    # deleted and replaced whenever any entry changes.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_state (
            house_id INTEGER PRIMARY KEY REFERENCES houses(house_id),
            message_id TEXT NOT NULL
        )
        """
    )
    conn.commit()


def set_entry(
    conn: sqlite3.Connection,
    house_id: int,
    key: str,
    value: str,
    member_id: int,
    category: str = "General",
) -> bool:
    """Insert or update a wiki entry. Returns True if created, False if updated."""
    existing = get_entry(conn, house_id, key)
    conn.execute(
        "INSERT INTO wiki_entries (house_id, key, value, category, set_by_member_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(house_id, key) DO UPDATE SET "
        "value = excluded.value, category = excluded.category, "
        "set_by_member_id = excluded.set_by_member_id, updated_at = excluded.updated_at",
        (house_id, key, value, category, member_id, _now_iso()),
    )
    conn.commit()
    return existing is None


def get_entry(conn: sqlite3.Connection, house_id: int, key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM wiki_entries WHERE house_id = ? AND key = ?", (house_id, key)
    ).fetchone()


def list_entries(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM wiki_entries WHERE house_id = ? ORDER BY category, key",
        (house_id,),
    ).fetchall()


def remove_entry(conn: sqlite3.Connection, house_id: int, key: str) -> bool:
    cur = conn.execute(
        "DELETE FROM wiki_entries WHERE house_id = ? AND key = ?", (house_id, key)
    )
    conn.commit()
    return cur.rowcount > 0


def seed_setup_entries(
    conn: sqlite3.Connection, house_id: int, member_id: int
) -> tuple[int, int]:
    """Insert all SETUP_ENTRIES that don't already exist. Returns (added, skipped)."""
    added = skipped = 0
    for key, category, placeholder in SETUP_ENTRIES:
        if get_entry(conn, house_id, key) is None:
            set_entry(conn, house_id, key, placeholder, member_id, category)
            added += 1
        else:
            skipped += 1
    return added, skipped


def get_wiki_message_id(conn: sqlite3.Connection, house_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT message_id FROM wiki_state WHERE house_id = ?", (house_id,)
    ).fetchone()
    return row["message_id"] if row else None


def save_wiki_message_id(conn: sqlite3.Connection, house_id: int, message_id: str) -> None:
    conn.execute(
        "INSERT INTO wiki_state (house_id, message_id) VALUES (?, ?) "
        "ON CONFLICT(house_id) DO UPDATE SET message_id = excluded.message_id",
        (house_id, message_id),
    )
    conn.commit()


def clear_wiki_message_id(conn: sqlite3.Connection, house_id: int) -> None:
    conn.execute("DELETE FROM wiki_state WHERE house_id = ?", (house_id,))
    conn.commit()


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


async def _sync_wiki_channel(bot: commands.Bot, guild: discord.Guild, house_id: int) -> None:
    """Delete the old wiki message (if any) and post a fresh one to #wiki.

    Silently does nothing if the #wiki channel doesn't exist — wiki commands
    still work, they just won't mirror to the channel until it's created.
    """
    channel = channels_cog.resolve_house_channel(guild, "wiki")
    if channel is None:
        return

    # Delete the previous message if we have a record of it.
    old_id = get_wiki_message_id(bot.db, house_id)
    if old_id:
        try:
            old_msg = await channel.fetch_message(int(old_id))
            await old_msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass  # already deleted or inaccessible
        clear_wiki_message_id(bot.db, house_id)

    # Post the fresh wiki.
    rows = list_entries(bot.db, house_id)
    triples = [(e["key"], e["value"], e["category"]) for e in rows]
    new_msg = await channel.send(format_wiki_list(triples))
    save_wiki_message_id(bot.db, house_id, str(new_msg.id))


class Wiki(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="wiki-set", description="Add or update a house wiki entry")
    @app_commands.describe(
        key="Short label, e.g. 'wifi password' or 'landlord contact'",
        value="The information to store",
        category="Which section this belongs in (default: General)",
    )
    async def wiki_set(
        self,
        interaction: discord.Interaction,
        key: str,
        value: str,
        category: Literal[
            "Access & Security",
            "Utilities & Services",
            "Building & Maintenance",
            "House Rules",
            "Lease & Legal",
            "General",
        ] = "General",
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        normalized = normalize_key(key)
        created = set_entry(self.bot.db, house["house_id"], normalized, value, member["member_id"], category)
        verb = "Added" if created else "Updated"
        await interaction.response.send_message(
            f"{verb} **{normalized}** under *{category}* in the house wiki.", ephemeral=True
        )
        await _sync_wiki_channel(self.bot, interaction.guild, house["house_id"])

    @app_commands.command(name="wiki", description="Look up a house wiki entry")
    @app_commands.describe(key="What to look up, e.g. 'wifi password'")
    async def wiki(self, interaction: discord.Interaction, key: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        normalized = normalize_key(key)
        entry = get_entry(self.bot.db, house["house_id"], normalized)
        if entry is None:
            await interaction.response.send_message(
                f"No wiki entry for **{normalized}**. See `/wiki-list` for all entries, "
                f"or `/wiki-set` to add it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            format_entry(entry["key"], entry["value"], entry["category"])
        )

    @app_commands.command(name="wiki-list", description="Show all house wiki entries grouped by category")
    async def wiki_list(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        rows = list_entries(self.bot.db, house["house_id"])
        triples = [(e["key"], e["value"], e["category"]) for e in rows]
        await interaction.response.send_message(format_wiki_list(triples))

    @app_commands.command(name="wiki-remove", description="Remove a house wiki entry")
    @app_commands.describe(key="Which entry to remove")
    async def wiki_remove(self, interaction: discord.Interaction, key: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        normalized = normalize_key(key)
        if remove_entry(self.bot.db, house["house_id"], normalized):
            await interaction.response.send_message(f"Removed **{normalized}** from the wiki.")
            await _sync_wiki_channel(self.bot, interaction.guild, house["house_id"])
        else:
            await interaction.response.send_message(
                f"No wiki entry for **{normalized}**. See `/wiki-list`.", ephemeral=True
            )

    @app_commands.command(
        name="wiki-setup",
        description="Pre-populate the wiki with common house entries (skips any already set)",
    )
    async def wiki_setup(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        added, skipped = seed_setup_entries(self.bot.db, house["house_id"], member["member_id"])
        msg = f"📖 Wiki setup complete — added **{added}** entries"
        if skipped:
            msg += f", skipped **{skipped}** that were already set"
        msg += ".\nFill them in with `/wiki-set key value category`. Run `/wiki-list` to see everything."
        await interaction.response.send_message(msg)
        await _sync_wiki_channel(self.bot, interaction.guild, house["house_id"])


async def setup(bot: commands.Bot):
    await bot.add_cog(Wiki(bot))
