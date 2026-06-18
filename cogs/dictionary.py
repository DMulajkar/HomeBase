from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

import database


@dataclass(frozen=True)
class CommandEntry:
    name: str
    description: str


COMMAND_CATEGORIES: list[tuple[str, list[CommandEntry]]] = [
    ("House Setup", [
        CommandEntry("/house-setup", "Register this Discord server as a house and open the channel picker."),
        CommandEntry("/join-house", "Add yourself to the house so you appear in splits, bills, and chore rotation."),
        CommandEntry("/house-members", "List everyone in the house in join order (also the chore rotation order)."),
        CommandEntry("/setup-channels", "Open the channel picker to create or re-create any HomeBase channels."),
        CommandEntry("/welcome", "Re-post the welcome message and full command cheat sheet to the current channel."),
        CommandEntry("/delete-house", "Permanently delete the house and all its data (admin only, confirmation required)."),
    ]),
    ("Expenses & Payments", [
        CommandEntry("/expense", "Log a shared expense paid by you, split equally across all house members."),
        CommandEntry("/pay", "Record a payment toward what you owe someone (omit amount to settle in full)."),
        CommandEntry("/balances", "Show who owes whom across the whole house after all expenses and payments."),
        CommandEntry("/ledger", "See every expense you've been charged for, with descriptions, dates, and amounts."),
    ]),
    ("Bills", [
        CommandEntry("/bill-add", "Define a recurring bill (fixed or variable) with a payer and due day."),
        CommandEntry("/bills", "List all recurring bills and whether each has been posted this month."),
        CommandEntry("/bill-post", "Post a variable bill for the current month (or override a fixed bill's amount)."),
        CommandEntry("/bill-remove", "Delete a recurring bill definition (past expenses it created are kept)."),
    ]),
    ("Chores", [
        CommandEntry("/chore-add", "Add a recurring chore to the rotation with a daily, weekly, or monthly cadence."),
        CommandEntry("/chores", "View all chores with current assignees, completion status, and due dates."),
        CommandEntry("/complete", "Mark a chore done for the current period and post a confirmation to #chores."),
        CommandEntry("/swap", "Hand off this period's chore to another member; rotation resumes next period."),
        CommandEntry("/chore-history", "Show how many chores each member has completed in total."),
    ]),
    ("Groceries", [
        CommandEntry("/grocery-add", "Add an item to the shared grocery list under Food, Household Supplies, or Cleaning Supplies."),
        CommandEntry("/groceries", "View the current grocery list grouped by category."),
        CommandEntry("/grocery-bought", "Mark an item as bought and remove it from the active list."),
        CommandEntry("/grocery-remove", "Remove an item from the list without marking it as bought."),
        CommandEntry("/grocery-done", "End a shopping run: clears the list and optionally records a split expense."),
    ]),
    ("Meal Voting", [
        CommandEntry("/meal-propose", "Propose a meal option (starts a new poll if none is currently open)."),
        CommandEntry("/meal-vote", "Cast or change your vote for a meal in the current poll."),
        CommandEntry("/meal-results", "Show the current vote standings without closing the poll."),
        CommandEntry("/meal-close", "Close the poll and announce the winning meal to #groceries."),
    ]),
    ("Subscriptions", [
        CommandEntry("/sub-add", "Save a shared subscription's email and password (password stored encrypted)."),
        CommandEntry("/subs", "List all saved subscriptions showing names and emails (no passwords)."),
        CommandEntry("/sub-password", "Retrieve a subscription's password privately (only you see the response)."),
        CommandEntry("/sub-update", "Update the email or password for an existing subscription."),
        CommandEntry("/sub-remove", "Delete a saved subscription."),
    ]),
    ("House Wiki", [
        CommandEntry("/wiki-setup", "Pre-populate the wiki with 27 common placeholder entries."),
        CommandEntry("/wiki-set", "Add a new wiki entry or overwrite an existing one."),
        CommandEntry("/wiki", "Look up a single wiki entry by key."),
        CommandEntry("/wiki-list", "View all wiki entries grouped by category."),
        CommandEntry("/wiki-remove", "Delete a wiki entry by key."),
    ]),
    ("Vacation & Birthdays", [
        CommandEntry("/vacation-start", "Mark yourself as on vacation, pausing your chore rotation and bill splits."),
        CommandEntry("/vacation-end", "Return from vacation and re-enter the normal rotation and splits."),
        CommandEntry("/vacations", "Show all members currently on vacation with their dates."),
        CommandEntry("/birthday-set", "Set or update your birthday (month and day only, no year)."),
        CommandEntry("/birthdays", "Show all house members who have a birthday on record."),
    ]),
    ("Calendar & Milestones", [
        CommandEntry("/event-add", "Add an event to the house calendar with a date, optional time, and description."),
        CommandEntry("/events", "View upcoming events (next 30 days) or all events in a specific month."),
        CommandEntry("/event-remove", "Remove an event from the calendar by its ID number."),
        CommandEntry("/milestone-add", "Add a house milestone or important date, optionally repeating annually."),
        CommandEntry("/milestones", "View all milestones with countdowns to their next occurrence."),
        CommandEntry("/milestone-remove", "Delete a milestone by name."),
    ]),
    ("Memories & Suggestions", [
        CommandEntry("/quote", "Save a memorable quote or funny moment from the house."),
        CommandEntry("/quotes", "View all saved house quotes, optionally filtered to one member."),
        CommandEntry("/quote-remove", "Delete a saved quote by its number."),
        CommandEntry("/suggestion", "Post an anonymous suggestion to #suggestions (no name attached)."),
        CommandEntry("/suggestions", "View all anonymous suggestions submitted to the house."),
    ]),
    ("Rankings & Dashboard", [
        CommandEntry("/leaderboard", "Show this month's house rankings combining chores and grocery runs."),
        CommandEntry("/homebase", "Show a single at-a-glance dashboard: bills, chores, groceries, and house health score."),
        CommandEntry("/dictionary", "Show this command dictionary."),
    ]),
    ("Settings", [
        CommandEntry("/settings", "View this house's current configuration with defaults shown where unset."),
        CommandEntry("/set", "Change a house setting such as reminder hour, lead days, or auto-post toggles."),
    ]),
]


def build_dictionary_embeds() -> list[discord.Embed]:
    embeds = []
    for category, entries in COMMAND_CATEGORIES:
        embed = discord.Embed(title=category, color=discord.Color.blurple())
        lines = "\n".join(f"`{e.name}` — {e.description}" for e in entries)
        embed.description = lines
        embeds.append(embed)
    embeds[0].title = "Command Dictionary — " + embeds[0].title
    embeds[-1].set_footer(text=f"{sum(len(e) for _, e in COMMAND_CATEGORIES)} commands total")
    return embeds


class Dictionary(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="dictionary", description="Show every HomeBase command and what it does")
    async def dictionary(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message(
                "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
            )
            return
        await interaction.response.send_message(embeds=build_dictionary_embeds(), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dictionary(bot))
