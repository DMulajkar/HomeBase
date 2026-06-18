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
    ChannelSpec("general", "House chat and anything that doesn't fit elsewhere.", "General house chat"),
    ChannelSpec("food", "Meals, recipes, leftovers, and dinner plans.", "Meals, recipes & dinner plans"),
    ChannelSpec("memories", "Photos and moments from the house.", "Share photos & house moments"),
    ChannelSpec("wiki", "House reference: Wi-Fi, landlord, lease, rules, and more.", "House reference & shared info"),
    ChannelSpec("bot-commands", "Run HomeBase bot commands here.", "A place to run bot commands"),
    ChannelSpec(
        "welcome",
        "House rules, bot setup, and important commands.",
        "House rules, setup & key commands",
        welcome=True,
    ),
]


def build_welcome_message(house_name: str) -> list[discord.Embed]:
    """Build the welcome embeds posted into the #welcome channel.

    Returns a list of embeds (sent together in one message) so each section
    stays under Discord's per-embed character limits. Constructable and
    testable without a live Discord connection.
    """

    # --- Embed 1: Welcome & getting started ---
    welcome = discord.Embed(
        title=f"Welcome to {house_name}",
        description=(
            "This is your house's home base. Everything the house needs — "
            "expenses, chores, bills, groceries, and more — lives here.\n\n"
            "**New to the house? Follow these steps:**"
        ),
        color=discord.Color.blurple(),
    )
    welcome.add_field(
        name="Step 1 — Join the house",
        value=(
            "Run `/join-house`. This adds you to expense splits, bill splits, "
            "and the chore rotation. Everyone must do this."
        ),
        inline=False,
    )
    welcome.add_field(
        name="Step 2 — Add your birthday (optional)",
        value=(
            "The bot will prompt you right after `/join-house`. You can also "
            "run `/birthday-set` any time. The house gets reminded on your day."
        ),
        inline=False,
    )
    welcome.add_field(
        name="Step 3 — Use `/homebase` anytime",
        value=(
            "Run `/homebase` for a live snapshot: bills due, chores pending, "
            "groceries needed, and a house health score."
        ),
        inline=False,
    )
    welcome.add_field(
        name="House rules",
        value="No rules set yet. An admin can pin the house rules in this channel.",
        inline=False,
    )
    welcome.set_footer(text="Full command reference below.")

    # --- Embed 2: Money ---
    money = discord.Embed(
        title="Money",
        color=discord.Color.green(),
    )
    money.add_field(
        name="Expenses",
        value=(
            "`/expense description amount` — log a shared expense; split equally across all members\n"
            "`/expense description amount charge_to:@member` — charge the full amount to one person\n"
            "`/pay to:@member amount` — record paying someone back\n"
            "`/pay to:@member` — settle your full balance with them in one shot\n"
            "`/balances` — see who owes whom across the whole house\n"
            "`/ledger` — see every expense you've been charged for, with descriptions and dates"
        ),
        inline=False,
    )
    money.add_field(
        name="Recurring Bills",
        value=(
            "`/bill-add name kind due_day payer amount` — define a recurring bill (fixed or variable)\n"
            "`/bills` — list all bills and this month's posted/pending status\n"
            "`/bill-post name amount` — post a variable bill (or override a fixed one)\n"
            "`/bill-remove name` — remove a bill definition\n\n"
            "*Fixed bills post themselves automatically on their due day.*"
        ),
        inline=False,
    )

    # --- Embed 3: Chores & Groceries ---
    chores_groceries = discord.Embed(
        title="Chores & Groceries",
        color=discord.Color.orange(),
    )
    chores_groceries.add_field(
        name="Chores",
        value=(
            "`/chore-add name cadence` — add a chore with daily / weekly / monthly rotation\n"
            "`/chores` — view all chores, assignees, and due dates\n"
            "`/complete name` — mark a chore done for this period\n"
            "`/swap name member` — hand off this period's chore to someone else\n"
            "`/chore-history` — see how many chores each member has completed\n"
            "`/leaderboard` — monthly rankings combining chores and grocery runs"
        ),
        inline=False,
    )
    chores_groceries.add_field(
        name="Groceries",
        value=(
            "`/grocery-add name category` — add an item (Food / Household Supplies / Cleaning Supplies)\n"
            "`/groceries` — view the current list by category\n"
            "`/grocery-bought name` — mark an item bought and remove it from the list\n"
            "`/grocery-remove name` — remove an item without marking it bought\n"
            "`/grocery-done amount` — end a shopping run: clears the list, records the expense"
        ),
        inline=False,
    )

    # --- Embed 4: House life ---
    life = discord.Embed(
        title="House Life",
        color=discord.Color.purple(),
    )
    life.add_field(
        name="Meal voting",
        value=(
            "`/meal-propose name` — propose a meal (starts a poll if none is open)\n"
            "`/meal-vote name` — cast or change your vote\n"
            "`/meal-results` — see current standings\n"
            "`/meal-close` — close the poll and announce the winner"
        ),
        inline=False,
    )
    life.add_field(
        name="Subscriptions",
        value=(
            "`/sub-add name email password` — save shared account credentials (password encrypted)\n"
            "`/subs` — list subscriptions (names + emails only, no passwords)\n"
            "`/sub-password name` — retrieve a password privately (only you see it)\n"
            "`/sub-update name` — update email or password\n"
            "`/sub-remove name` — delete a subscription"
        ),
        inline=False,
    )
    life.add_field(
        name="House wiki",
        value=(
            "`/wiki-setup` — pre-populate 27 common entries as placeholders\n"
            "`/wiki-set key value [category]` — add or update an entry\n"
            "`/wiki key` — look up an entry\n"
            "`/wiki-list` — view all entries grouped by category\n"
            "`/wiki-remove key` — delete an entry"
        ),
        inline=False,
    )
    life.add_field(
        name="Vacation, birthdays & suggestions",
        value=(
            "`/vacation-start [end]` — go on vacation (skipped in chores and bill splits)\n"
            "`/vacation-end` — return from vacation\n"
            "`/vacations` — see who's currently away\n"
            "`/birthday-set` — set your birthday (month + day only)\n"
            "`/birthdays` — see all house birthdays\n"
            "`/suggestion text` — post anonymous feedback to #suggestions"
        ),
        inline=False,
    )

    return [welcome, money, chores_groceries, life]


# --- Layer 3: Discord plumbing (not unit-tested, no live-client tests) ---


def resolve_house_channel(guild: discord.Guild, name: str):
    """Find a text channel by name inside this guild's HomeBase category.

    Returns the channel or None. Scoping the lookup to the category means a
    like-named channel elsewhere in the server is never matched. Shared by the
    scheduler's auto-posts and the /pay payment confirmation.
    """
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category is None:
        return None
    return discord.utils.get(category.text_channels, name=name)


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
            await channel.send(embeds=build_welcome_message(house_name))

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


    @app_commands.command(name="welcome", description="Re-post the welcome message and command cheat sheet")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome(self, interaction: discord.Interaction):
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
        await interaction.response.send_message("Posting welcome message...", ephemeral=True)
        await interaction.channel.send(embeds=build_welcome_message(house_name))


async def setup(bot: commands.Bot):
    await bot.add_cog(Channels(bot))
