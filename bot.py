import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database

load_dotenv()

DB_PATH = os.environ.get("HOMEBASE_DB_PATH", "homebase.db")

intents = discord.Intents.default()


class HomeBaseBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        # sqlite3 connections are bound to the thread that created them; this is
        # only safe because cogs call self.bot.db synchronously from the same
        # event loop thread bot.run() drives. Don't offload db calls via
        # asyncio.to_thread without switching to a thread-safe connection.
        self.db = database.connect(DB_PATH)
        database.init_db(self.db)

    async def setup_hook(self):
        await self.load_extension("cogs.core")
        await self.load_extension("cogs.expenses")
        await self.tree.sync()


def main():
    token = os.environ["DISCORD_TOKEN"]
    bot = HomeBaseBot()
    bot.run(token)


if __name__ == "__main__":
    main()
