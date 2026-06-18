import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

import database


# --- Layer 1: pure definitions and formatting (no I/O, unit-tested) ---


@dataclass(frozen=True)
class SettingDef:
    key: str
    description: str
    default: str
    validate: Callable[[str], bool]
    hint: str  # shown in /settings and error messages


SETTINGS: dict[str, SettingDef] = {
    "reminder_hour": SettingDef(
        key="reminder_hour",
        description="Hour (UTC, 0–23) at which daily reminders are sent",
        default="9",
        validate=lambda v: v.isdigit() and 0 <= int(v) <= 23,
        hint="0–23",
    ),
    "reminder_lead_days": SettingDef(
        key="reminder_lead_days",
        description="Days before a bill's due date to start reminding",
        default="3",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 7,
        hint="1–7",
    ),
    "summary_day": SettingDef(
        key="summary_day",
        description="Day of the month (1–28) for monthly summaries and rankings",
        default="1",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 28,
        hint="1–28",
    ),
    "post.chores-reminder": SettingDef(
        key="post.chores-reminder",
        description="Daily chore reminder auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.chore-rankings": SettingDef(
        key="post.chore-rankings",
        description="Monthly chore rankings auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.fixed-bills": SettingDef(
        key="post.fixed-bills",
        description="Fixed bill auto-posting on due day",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.bills-due-reminder": SettingDef(
        key="post.bills-due-reminder",
        description="Upcoming bill due-date reminders",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.monthly-summary": SettingDef(
        key="post.monthly-summary",
        description="Monthly financial summary auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.grocery-spending": SettingDef(
        key="post.grocery-spending",
        description="Monthly grocery spending report auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.leaderboard": SettingDef(
        key="post.leaderboard",
        description="Monthly house leaderboard auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
    "post.birthday-reminder": SettingDef(
        key="post.birthday-reminder",
        description="Birthday reminder auto-post",
        default="on",
        validate=lambda v: v.lower() in ("on", "off"),
        hint="on / off",
    ),
}


def validate_setting(key: str, raw_value: str) -> str:
    """Validate and normalize a setting value. Raises ValueError on bad input."""
    defn = SETTINGS.get(key)
    if defn is None:
        known = ", ".join(SETTINGS)
        raise ValueError(f"Unknown setting '{key}'. Known settings: {known}.")
    value = raw_value.strip().lower() if raw_value.strip().lower() in ("on", "off") else raw_value.strip()
    if not defn.validate(value):
        raise ValueError(
            f"Invalid value '{raw_value}' for '{key}'. Expected: {defn.hint}."
        )
    return value


def format_settings(current: dict[str, str]) -> str:
    """Render all settings with their current value (or default if not set)."""
    lines = ["**House settings**", ""]
    numeric_keys = ["reminder_hour", "reminder_lead_days", "summary_day"]
    toggle_keys = [k for k in SETTINGS if k.startswith("post.")]

    lines.append("*Scheduling*")
    for key in numeric_keys:
        defn = SETTINGS[key]
        value = current.get(key, defn.default)
        tag = "" if key in current else " (default)"
        lines.append(f"  {key}: {value}{tag}")

    lines.append("")
    lines.append("*Auto-post toggles*")
    for key in toggle_keys:
        defn = SETTINGS[key]
        value = current.get(key, defn.default)
        tag = "" if key in current else " (default)"
        lines.append(f"  {key}: {value}{tag}")

    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(house_id, key)
        )
        """
    )
    conn.commit()


def get_setting(
    conn: sqlite3.Connection,
    house_id: int,
    key: str,
    default: Optional[str] = None,
) -> Optional[str]:
    """Read a setting for a house. Returns `default` if not set.

    Calls init_tables so it is safe to call before the settings cog is loaded
    (e.g. from scheduler/finance/chores render functions in tests).
    """
    init_tables(conn)
    row = conn.execute(
        "SELECT value FROM settings WHERE house_id = ? AND key = ?",
        (house_id, key),
    ).fetchone()
    if row is not None:
        return row["value"]
    if default is not None:
        return default
    defn = SETTINGS.get(key)
    return defn.default if defn else None


def set_setting(conn: sqlite3.Connection, house_id: int, key: str, value: str) -> None:
    init_tables(conn)
    conn.execute(
        "INSERT INTO settings (house_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(house_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (house_id, key, value, _now_iso()),
    )
    conn.commit()


def get_all_settings(conn: sqlite3.Connection, house_id: int) -> dict[str, str]:
    """Return all explicitly-set settings for a house (keys not present use defaults)."""
    init_tables(conn)
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE house_id = ?", (house_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


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


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="settings", description="View this house's current configuration")
    async def settings(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        current = get_all_settings(self.bot.db, house["house_id"])
        await interaction.response.send_message(format_settings(current))

    @app_commands.command(name="set", description="Change a house setting")
    @app_commands.describe(
        key="Which setting to change",
        value="New value for the setting",
    )
    async def set_cmd(
        self,
        interaction: discord.Interaction,
        key: Literal[
            "reminder_hour",
            "reminder_lead_days",
            "summary_day",
            "post.chores-reminder",
            "post.chore-rankings",
            "post.fixed-bills",
            "post.bills-due-reminder",
            "post.monthly-summary",
            "post.grocery-spending",
            "post.leaderboard",
            "post.birthday-reminder",
        ],
        value: str,
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        try:
            normalized = validate_setting(key, value)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        set_setting(self.bot.db, house["house_id"], key, normalized)
        defn = SETTINGS[key]
        await interaction.response.send_message(
            f"Set **{key}** to `{normalized}`. {defn.description}."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Settings(bot))
