import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs.birthdays import BirthdayPromptView
from cogs.channels import ChannelSetupView


def delete_house_data(conn: sqlite3.Connection, house_id: int) -> None:
    """Delete all data for a house in FK-safe order."""
    # Expenses
    expense_ids = [r[0] for r in conn.execute(
        "SELECT expense_id FROM expenses WHERE house_id = ?", (house_id,)
    ).fetchall()]
    if expense_ids:
        conn.execute(f"DELETE FROM expense_splits WHERE expense_id IN ({','.join('?'*len(expense_ids))})", expense_ids)
    conn.execute("DELETE FROM expenses WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM settlements WHERE house_id = ?", (house_id,))

    # Chores
    chore_ids = [r[0] for r in conn.execute(
        "SELECT chore_id FROM chores WHERE house_id = ?", (house_id,)
    ).fetchall()]
    if chore_ids:
        conn.execute(f"DELETE FROM chore_completions WHERE chore_id IN ({','.join('?'*len(chore_ids))})", chore_ids)
        conn.execute(f"DELETE FROM chore_swaps WHERE chore_id IN ({','.join('?'*len(chore_ids))})", chore_ids)
    conn.execute("DELETE FROM chores WHERE house_id = ?", (house_id,))

    # Finance
    bill_ids = [r[0] for r in conn.execute(
        "SELECT bill_id FROM bills WHERE house_id = ?", (house_id,)
    ).fetchall()]
    if bill_ids:
        conn.execute(f"DELETE FROM bill_postings WHERE bill_id IN ({','.join('?'*len(bill_ids))})", bill_ids)
    conn.execute("DELETE FROM bills WHERE house_id = ?", (house_id,))

    # Groceries
    conn.execute("DELETE FROM grocery_runs WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM grocery_items WHERE house_id = ?", (house_id,))

    # Meals
    poll_ids = [r[0] for r in conn.execute(
        "SELECT poll_id FROM meal_polls WHERE house_id = ?", (house_id,)
    ).fetchall()]
    if poll_ids:
        option_ids = [r[0] for r in conn.execute(
            f"SELECT option_id FROM meal_options WHERE poll_id IN ({','.join('?'*len(poll_ids))})", poll_ids
        ).fetchall()]
        if option_ids:
            conn.execute(f"DELETE FROM meal_votes WHERE option_id IN ({','.join('?'*len(option_ids))})", option_ids)
        conn.execute(f"DELETE FROM meal_options WHERE poll_id IN ({','.join('?'*len(poll_ids))})", poll_ids)
    conn.execute("DELETE FROM meal_polls WHERE house_id = ?", (house_id,))

    # Other house-scoped tables
    conn.execute("DELETE FROM quotes WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM milestones WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM calendar_events WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM subscriptions WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM suggestions WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM vacations WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM wiki_state WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM wiki_entries WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM settings WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM schedule_state WHERE house_id = ?", (house_id,))

    # Member-scoped tables (birthdays keyed by member_id)
    member_ids = [r[0] for r in conn.execute(
        "SELECT member_id FROM members WHERE house_id = ?", (house_id,)
    ).fetchall()]
    if member_ids:
        conn.execute(f"DELETE FROM member_birthdays WHERE member_id IN ({','.join('?'*len(member_ids))})", member_ids)

    # Members and house
    conn.execute("DELETE FROM members WHERE house_id = ?", (house_id,))
    conn.execute("DELETE FROM houses WHERE house_id = ?", (house_id,))
    conn.commit()


class DeleteHouseConfirmView(discord.ui.View):
    def __init__(self, house_id: int, house_name: str, db: sqlite3.Connection):
        super().__init__(timeout=60)
        self.house_id = house_id
        self.house_name = house_name
        self.db = db

    @discord.ui.button(label="Yes, delete everything", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        delete_house_data(self.db, self.house_id)
        self.stop()
        await interaction.response.edit_message(
            content=f"The house **{self.house_name}** and all its data have been permanently deleted.",
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled — nothing was deleted.", view=None)


def build_welcome_dm(guild_name: str, rules: str | None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Welcome to {guild_name}!",
        description=(
            "You've just joined a house managed by HomeBase. "
            "Here's how to get started:"
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Step 1 — Join the house",
        value="Run `/join-house` in the server. This adds you to expense splits, bill splits, and the chore rotation.",
        inline=False,
    )
    embed.add_field(
        name="Step 2 — Add your birthday (optional)",
        value="Run `/birthday-set` to add your birthday. The house will be reminded on your day.",
        inline=False,
    )
    embed.add_field(
        name="Step 3 — Explore",
        value="Run `/homebase` for a live snapshot of bills, chores, and groceries. Run `/dictionary` to see every available command.",
        inline=False,
    )
    if rules:
        embed.add_field(name="House Rules", value=rules, inline=False)
    embed.set_footer(text="Questions? Ask your housemates or run /dictionary for the full command list.")
    return embed


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        house = database.get_house(self.bot.db, str(member.guild.id))
        if house is None:
            return
        rules = None
        try:
            from cogs.wiki import get_entry
            row = get_entry(self.bot.db, house["house_id"], "house rules")
            if row and row["value"] != "(not set)":
                rules = row["value"]
        except Exception:
            pass
        try:
            await member.send(embed=build_welcome_dm(member.guild.name, rules))
        except discord.Forbidden:
            pass

    @app_commands.command(name="house-setup", description="Set up this server as a house")
    async def house_setup(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        existing = database.get_house(self.bot.db, str(interaction.guild_id))
        if existing is not None:
            await interaction.response.send_message("This server already has a house set up.", ephemeral=True)
            return

        database.create_house(self.bot.db, str(interaction.guild_id), interaction.guild.name)
        view = ChannelSetupView(interaction.guild.name, interaction.user.id)
        await interaction.response.send_message(
            f"House set up for {interaction.guild.name}! Members can now run /join-house.\n\n"
            "Want me to create some channels? Pick from the list, then press **Create channels**:",
            view=view,
        )

    @app_commands.command(name="join-house", description="Join this server's house")
    async def join_house(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message(
                "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
            )
            return

        existing = database.get_member(self.bot.db, house["house_id"], str(interaction.user.id))
        if existing is not None:
            await interaction.response.send_message("You're already a member of this house.", ephemeral=True)
            return

        member_id = database.add_member(
            self.bot.db, house["house_id"], str(interaction.user.id), interaction.user.display_name
        )
        await interaction.response.send_message(f"{interaction.user.display_name} joined the house!")
        await interaction.followup.send(
            "Would you like to add your birthday? The house will be reminded on your big day.",
            view=BirthdayPromptView(self.bot, member_id),
            ephemeral=True,
        )

    @app_commands.command(name="house-members", description="See who's in this house")
    async def house_members(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message(
                "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
            )
            return

        members = database.list_members(self.bot.db, house["house_id"])
        if not members:
            await interaction.response.send_message(
                "No one has joined this house yet. Run /join-house to be the first.", ephemeral=True
            )
            return

        # Listed in join order, which is also the chore rotation order.
        lines = "\n".join(f"{i}. {m['display_name']}" for i, m in enumerate(members, start=1))
        embed = discord.Embed(
            title=f"🏠 {house['name']} — {len(members)} member{'s' if len(members) != 1 else ''}",
            description=lines,
        )
        embed.set_footer(text="Listed in join order (also the chore rotation order).")
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="delete-house", description="Permanently delete this house and all its data")
    @app_commands.default_permissions(manage_guild=True)
    async def delete_house(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message("This server doesn't have a house set up.", ephemeral=True)
            return

        view = DeleteHouseConfirmView(house["house_id"], house["name"], self.bot.db)
        await interaction.response.send_message(
            f"Are you sure you want to delete **{house['name']}**? "
            "This will permanently erase all expenses, chores, bills, groceries, members, and every other record. "
            "**This cannot be undone.**",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
