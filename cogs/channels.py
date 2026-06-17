from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

import database

CATEGORY_NAME = "HomeBase"


# --- Layer 1: pure data and message building (unit-tested) ---


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    topic: str  # the Discord channel's topic/description
    description: str  # short blurb shown under the option in the setup picker
    welcome: bool = False


CHANNEL_CATALOG = [
    ChannelSpec("chores", "Chore assignments, rotations, and reminders.", "Track and assign household chores"),
    ChannelSpec(
        "rent-and-utilities",
        "Rent, utilities, bills, balances, and who owes whom.",
        "Bills, rent & shared balances",
    ),
    ChannelSpec("groceries", "Shared grocery lists and who's shopping.", "Shared shopping lists & runs"),
    ChannelSpec("food", "Meals, recipes, leftovers, and dinner plans.", "Meals, recipes & dinner plans"),
    ChannelSpec("events", "House events, hangouts, and shared calendar.", "Plan house events & hangouts"),
    ChannelSpec("memories", "Photos and moments from the house.", "Share photos & house moments"),
    ChannelSpec("bot-commands", "Run HomeBase bot commands here.", "A place to run bot commands"),
    ChannelSpec(
        "welcome",
        "House rules, bot setup, and important commands.",
        "House rules, setup & key commands",
        welcome=True,
    ),
]


def build_welcome_message(house_name: str) -> discord.Embed:
    """Build the welcome embed posted into the #welcome channel.

    discord.Embed is a plain data object, so this is constructable and testable
    without a live Discord connection.
    """
    embed = discord.Embed(
        title=f"Welcome to {house_name}! 🏠",
        description="This is your house's home base. Here's everything you need to get started.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="📜 House Rules",
        value="✏️ *No rules yet — an admin can post the house rules in this channel and pin them.*",
        inline=False,
    )
    embed.add_field(
        name="🤖 Bot Setup",
        value="New here? Run `/join-house` so you're included in expenses and everything else.",
        inline=False,
    )
    embed.add_field(
        name="⭐ Important Commands",
        value=(
            "`/expense` — add a shared expense, split equally\n"
            "`/pay` — record paying someone back\n"
            "`/balances` — see who owes whom\n"
            "`/join-house` — join this house"
        ),
        inline=False,
    )
    return embed


# --- Layer 3: Discord plumbing (not unit-tested, no live-client tests) ---


async def create_selected_channels(
    guild: discord.Guild, selected_names: list[str], house_name: str
) -> tuple[list[str], list[str]]:
    """Create the selected channels under the HomeBase category.

    Idempotent: channels that already exist (by name) are skipped. The welcome
    embed is posted only when the welcome channel is newly created, so re-runs
    never duplicate it. Returns (created, skipped) name lists. May raise
    discord.Forbidden if the bot lacks Manage Channels.
    """
    specs = [s for s in CHANNEL_CATALOG if s.name in selected_names]
    created: list[str] = []
    skipped: list[str] = []
    if not specs:
        return created, skipped

    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(CATEGORY_NAME)

    for spec in specs:
        if discord.utils.get(guild.text_channels, name=spec.name) is not None:
            skipped.append(spec.name)
            continue
        channel = await guild.create_text_channel(spec.name, category=category, topic=spec.topic)
        created.append(spec.name)
        if spec.welcome:
            await channel.send(embed=build_welcome_message(house_name))

    return created, skipped


class ChannelSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=s.name, value=s.name, description=s.description, default=True)
            for s in CHANNEL_CATALOG
        ]
        super().__init__(
            placeholder="Choose channels to create…",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_names = list(self.values)
        await interaction.response.defer()


class ChannelSetupView(discord.ui.View):
    def __init__(self, house_name: str, author_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.house_name = house_name
        self.author_id = author_id
        # All channels are default-selected; this stands in until the user edits
        # the select (whose callback overwrites it).
        self.selected_names = [s.name for s in CHANNEL_CATALOG]
        self.add_item(ChannelSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who started setup can use this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Create channels", style=discord.ButtonStyle.primary)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not self.selected_names:
            await interaction.edit_original_response(content="No channels selected — nothing created.", view=None)
            self.stop()
            return
        try:
            created, skipped = await create_selected_channels(
                interaction.guild, self.selected_names, self.house_name
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=(
                    "I'm missing a permission I need here. Please grant my role **Manage "
                    "Channels** (to create channels), plus **Send Messages** and **Embed "
                    "Links** (to post the welcome message), then run `/setup-channels` again."
                ),
                view=None,
            )
            self.stop()
            return

        lines = []
        if created:
            lines.append("✅ Created: " + ", ".join(f"#{n}" for n in created))
        if skipped:
            lines.append("↩️ Already existed: " + ", ".join(f"#{n}" for n in skipped))
        await interaction.edit_original_response(content="\n".join(lines), view=None)
        self.stop()


class Channels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup-channels", description="Create HomeBase channels for this house")
    async def setup_channels(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message(
                "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
            )
            return
        house_name = house["name"] or interaction.guild.name
        view = ChannelSetupView(house_name, interaction.user.id)
        await interaction.response.send_message(
            "Pick the channels you'd like me to create, then press **Create channels**:",
            view=view,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Channels(bot))
