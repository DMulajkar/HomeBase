import discord
from discord import app_commands
from discord.ext import commands

import database
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

        database.add_member(
            self.bot.db, house["house_id"], str(interaction.user.id), interaction.user.display_name
        )
        await interaction.response.send_message(f"{interaction.user.display_name} joined the house!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
