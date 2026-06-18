import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from cryptography.fernet import Fernet, InvalidToken

import database

# Passwords are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
# The key must be set in .env as SUBSCRIPTION_KEY. Generate one with:
#   py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Never commit the key. Without it the cog loads but password commands are disabled.


# --- Layer 1: pure functions (no I/O, unit-tested) ---


def encrypt_password(fernet: Fernet, plaintext: str) -> str:
    """Encrypt a plaintext password; returns a URL-safe base64 token string."""
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_password(fernet: Fernet, token: str) -> str:
    """Decrypt a stored token back to plaintext. Raises InvalidToken if tampered."""
    return fernet.decrypt(token.encode()).decode()


def format_sub_list(subs: list[tuple[str, str]]) -> str:
    """Render `(name, email)` pairs as a listing. Passwords are never shown here."""
    if not subs:
        return "No subscriptions saved yet. Add one with `/sub-add`."
    lines = ["🔑 **Shared subscriptions**"]
    for name, email in subs:
        lines.append(f"**{name}** — {email}")
    return "\n".join(lines)


# --- Layer 2: DB access (conn first arg, unit-tested) ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            sub_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            password_token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(house_id, name)
        )
        """
    )
    conn.commit()


def add_subscription(
    conn: sqlite3.Connection,
    house_id: int,
    name: str,
    email: str,
    password_token: str,
) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO subscriptions (house_id, name, email, password_token, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (house_id, name, email, password_token, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A subscription named **{name}** already exists.")


def get_subscription(conn: sqlite3.Connection, house_id: int, name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM subscriptions WHERE house_id = ? AND name = ?", (house_id, name)
    ).fetchone()


def list_subscriptions(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM subscriptions WHERE house_id = ? ORDER BY name", (house_id,)
    ).fetchall()


def remove_subscription(conn: sqlite3.Connection, house_id: int, name: str) -> bool:
    cur = conn.execute(
        "DELETE FROM subscriptions WHERE house_id = ? AND name = ?", (house_id, name)
    )
    conn.commit()
    return cur.rowcount > 0


def update_subscription(
    conn: sqlite3.Connection,
    house_id: int,
    name: str,
    email: Optional[str],
    password_token: Optional[str],
) -> bool:
    """Update email and/or password for an existing subscription. Returns False if not found."""
    sub = get_subscription(conn, house_id, name)
    if sub is None:
        return False
    new_email = email if email is not None else sub["email"]
    new_token = password_token if password_token is not None else sub["password_token"]
    conn.execute(
        "UPDATE subscriptions SET email = ?, password_token = ? WHERE house_id = ? AND name = ?",
        (new_email, new_token, house_id, name),
    )
    conn.commit()
    return True


# --- Layer 3: Discord plumbing and guards ---


def _load_fernet() -> Optional[Fernet]:
    key = os.environ.get("SUBSCRIPTION_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


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


_NO_KEY_MSG = (
    "Subscription passwords are disabled — `SUBSCRIPTION_KEY` is not set in `.env`.\n"
    "Generate a key and add it:\n"
    "```\n"
    "py -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
    "```\n"
    "Then add `SUBSCRIPTION_KEY=<output>` to your `.env` file and restart the bot."
)


class Subscriptions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)
        self._fernet = _load_fernet()

    @app_commands.command(name="sub-add", description="Save a shared subscription (password stored encrypted)")
    @app_commands.describe(
        name="Service name, e.g. Netflix",
        email="Email address for the account",
        password="Account password — stored encrypted, never shown in chat",
    )
    async def sub_add(self, interaction: discord.Interaction, name: str, email: str, password: str):
        if self._fernet is None:
            await interaction.response.send_message(_NO_KEY_MSG, ephemeral=True)
            return
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        token = encrypt_password(self._fernet, password)
        try:
            add_subscription(self.bot.db, house["house_id"], name, email, token)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        # Always ephemeral — confirms the password was saved without echoing it.
        await interaction.response.send_message(
            f"Saved **{name}** ({email}). Password stored encrypted. 🔐\n"
            f"Retrieve it anytime with `/sub-password {name}`.",
            ephemeral=True,
        )

    @app_commands.command(name="subs", description="List all shared subscriptions (names and emails only)")
    async def subs(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        rows = list_subscriptions(self.bot.db, house["house_id"])
        pairs = [(r["name"], r["email"]) for r in rows]
        await interaction.response.send_message(format_sub_list(pairs))

    @app_commands.command(name="sub-password", description="Retrieve the password for a subscription (only you see this)")
    @app_commands.describe(name="Which subscription")
    async def sub_password(self, interaction: discord.Interaction, name: str):
        if self._fernet is None:
            await interaction.response.send_message(_NO_KEY_MSG, ephemeral=True)
            return
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        sub = get_subscription(self.bot.db, house["house_id"], name)
        if sub is None:
            await interaction.response.send_message(
                f"No subscription named **{name}**. See `/subs`.", ephemeral=True
            )
            return
        try:
            plaintext = decrypt_password(self._fernet, sub["password_token"])
        except InvalidToken:
            await interaction.response.send_message(
                "Could not decrypt this password — the encryption key may have changed.", ephemeral=True
            )
            return
        # Always ephemeral — only the requester sees this.
        await interaction.response.send_message(
            f"🔑 **{name}**\nEmail: `{sub['email']}`\nPassword: `{plaintext}`",
            ephemeral=True,
        )

    @app_commands.command(name="sub-update", description="Update the email or password for a subscription")
    @app_commands.describe(
        name="Which subscription to update",
        email="New email address (leave blank to keep current)",
        password="New password (leave blank to keep current)",
    )
    async def sub_update(
        self,
        interaction: discord.Interaction,
        name: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        if password is not None and self._fernet is None:
            await interaction.response.send_message(_NO_KEY_MSG, ephemeral=True)
            return
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if email is None and password is None:
            await interaction.response.send_message(
                "Provide a new email, password, or both.", ephemeral=True
            )
            return
        token = encrypt_password(self._fernet, password) if password is not None else None
        if not update_subscription(self.bot.db, house["house_id"], name, email, token):
            await interaction.response.send_message(
                f"No subscription named **{name}**. See `/subs`.", ephemeral=True
            )
            return
        updated = []
        if email:
            updated.append("email")
        if password:
            updated.append("password")
        await interaction.response.send_message(
            f"Updated {' and '.join(updated)} for **{name}**. 🔐", ephemeral=True
        )

    @app_commands.command(name="sub-remove", description="Remove a shared subscription")
    @app_commands.describe(name="Which subscription to remove")
    async def sub_remove(self, interaction: discord.Interaction, name: str):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result
        if remove_subscription(self.bot.db, house["house_id"], name):
            await interaction.response.send_message(f"Removed **{name}**.")
        else:
            await interaction.response.send_message(
                f"No subscription named **{name}**. See `/subs`.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Subscriptions(bot))
