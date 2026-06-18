from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import discord
from discord.ext import commands, tasks

import database
import scheduler
from cogs import birthdays, channels, chores, events, finance, groceries, leaderboard, milestones, quotes
from cogs.settings import get_setting

REMINDER_HOUR_UTC = 9
CHECK_INTERVAL_MINUTES = 15


@dataclass(frozen=True)
class ScheduledJob:
    key: str  # unique per-job identifier, used as the schedule_state job_key
    channel: str  # target channel name in each guild
    render: Callable[..., Optional[str]]  # (conn, house_id, today) -> message or None


# Auto-posts register here. Each runs once per UTC day at REMINDER_HOUR_UTC.
JOBS = [
    ScheduledJob(key="chores-reminder", channel="chores", render=chores.render_chores_reminder),
    ScheduledJob(key="chore-rankings", channel="chores", render=chores.render_rankings),
    ScheduledJob(key="fixed-bills", channel="rent-and-utilities", render=finance.render_due_fixed_bills),
    ScheduledJob(key="bills-due-reminder", channel="rent-and-utilities", render=finance.render_upcoming_bills),
    ScheduledJob(key="monthly-summary", channel="rent-and-utilities", render=finance.render_monthly_summary),
    ScheduledJob(key="grocery-spending", channel="groceries", render=groceries.render_spending_report),
    ScheduledJob(key="leaderboard", channel="chores", render=leaderboard.render_monthly_leaderboard),
    ScheduledJob(key="birthday-reminder", channel="general", render=birthdays.render_birthday_reminder),
    ScheduledJob(key="weekly-quote", channel="memories", render=quotes.render_weekly_quote),
    ScheduledJob(key="milestone-reminder", channel="memories", render=milestones.render_upcoming_milestones),
    ScheduledJob(key="event-reminder", channel="general", render=events.render_daily_events),
]


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        scheduler.init_tables(bot.db)
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def tick(self):
        now = datetime.now(timezone.utc)
        for house in database.list_houses(self.bot.db):
            guild = self.bot.get_guild(int(house["guild_id"]))
            if guild is None:
                continue
            for job in JOBS:
                await self._run_job(house, guild, job, now)

    async def _run_job(self, house, guild: discord.Guild, job: ScheduledJob, now: datetime):
        reminder_hour = int(get_setting(self.bot.db, house["house_id"], "reminder_hour", str(REMINDER_HOUR_UTC)))
        last_run = scheduler.get_last_run_date(self.bot.db, house["house_id"], job.key)
        if not scheduler.is_due(now, last_run, reminder_hour):
            return
        if get_setting(self.bot.db, house["house_id"], f"post.{job.key}", "on") != "on":
            return
        # Resolve inside the HomeBase category only, so a like-named channel
        # elsewhere in the server never receives the post.
        channel = channels.resolve_house_channel(guild, job.channel)
        if channel is None:
            return
        message = job.render(self.bot.db, house["house_id"], now.date())
        if not message:
            return
        try:
            await channel.send(message)
        except discord.Forbidden:
            return
        scheduler.set_last_run(self.bot.db, house["house_id"], job.key, now.date(), now)

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Scheduler(bot))
