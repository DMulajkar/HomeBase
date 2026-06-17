# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

**Use the `py` launcher for everything.** On this machine `python` / `python3` are broken Windows Store stub shims and will fail. The interpreter is Python 3.12 via `py`.

## Commands

```powershell
py -m pip install -r requirements.txt   # install deps
py bot.py                               # run the bot (reads .env)
py -m pytest                            # run the full test suite
py -m pytest -v                         # verbose
py -m pytest tests/test_expenses_db.py::test_record_expense_end_to_end_balance -v   # single test
```

There is no build step and no linter configured. `.env` (gitignored) must contain `DISCORD_TOKEN`; set `GUILD_ID` to a server ID for instant slash-command sync during development (leave blank for global sync, which can take ~an hour to propagate).

## What this is

A Discord bot for managing a shared house/apartment with roommates, built incrementally one feature at a time. Only the expenses feature exists so far. Future features (chores, groceries, maintenance, scheduling, governance) will each arrive as a separate cog. **Do not build features ahead of the current request** — the scope is deliberately one feature per pass.

## Architecture

**Three-layer separation is the core design choice.** Every feature is split so that logic can be tested without a live Discord connection:

1. **Pure functions** — money math and balance computation, no I/O. (`split_amount`, `compute_net_balances`, `dollars_to_cents` in `cogs/expenses.py`.)
2. **DB functions** — every one takes a `sqlite3.Connection` as its first argument (no global connection, no `self`). This is what lets tests run against an in-memory `:memory:` database. (`database.py`, and the `record_*`/`get_*` functions in `cogs/expenses.py`.)
3. **Discord command handlers** — the `commands.Cog` methods that call layers 1 and 2 and own all user-facing messages and guards.

Tests target layers 1 and 2 only; there are no tests that spin up a Discord client. The `conn` pytest fixture (`conftest.py`) hands each test a fresh in-memory DB.

**Cog ownership of tables.** `database.py` owns only the two cross-cutting tables every feature depends on: `houses` (one row per Discord server, keyed by `guild_id`) and `members` (one row per user per house). Each feature cog creates and owns its *own* tables by calling its `init_tables(conn)` from the cog's `__init__`. `cogs/expenses.py` owns `expenses`, `expense_splits`, and `settlements`. Follow this pattern for new features — don't add feature tables to `database.py`.

**Single shared connection.** `bot.py` opens one long-lived `sqlite3` connection at startup, stores it as `self.db`, and cogs reach it via `self.bot.db`. This connection is bound to the event-loop thread and is only safe because every DB call is synchronous on that thread. **Do not offload DB calls with `asyncio.to_thread`** without switching to a thread-safe connection (see the comment in `bot.py`).

**Money is always integer cents.** Dollars from Discord input are converted once at the boundary via `dollars_to_cents`, which uses `Decimal(str(amount))` to avoid binary-float rounding errors (e.g. `2.675` → `268`, not `267`). Never store or compute money as a float. Equal splits distribute the remainder one cent at a time to the first N members so shares always sum exactly to the total.

**Balances are net pairwise**, not group-settlement-minimized. For each ordered pair the net of (debts owed) minus (settlements paid) is computed; zero-net pairs are omitted. `get_debts` derives "who owes whom" from `expense_splits` joined to the payer on `expenses`; `get_payments` reads the `settlements` table. Both are scoped by `house_id`.

## Adding a feature

A new feature is a new file in `cogs/`. Wire it up by adding one `await self.load_extension("cogs.<name>")` line in `bot.py`'s `setup_hook`. Give the cog an `init_tables(conn)` for any new tables and call it from the cog's `__init__`. Keep pure logic and DB access as standalone functions (layers 1 and 2) so they can be unit-tested against the `conn` fixture; reserve the Cog methods for Discord plumbing and guards (DM rejection, house-exists check, membership check — see `_get_house_and_member` in `cogs/expenses.py` for the shared guard pattern). For high-traffic commands, add a short alias command that shares the same `_impl` method (e.g. `/pay` → add-expense, `/bal` → balances).
