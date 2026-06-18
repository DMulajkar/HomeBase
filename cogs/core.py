import discord
from discord import app_commands
from discord.ext import commands

import database
from cogs.birthdays import BirthdayPromptView
from cogs.channels import ChannelSetupView


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
