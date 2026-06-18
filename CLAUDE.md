# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

**Windows**: Use the `py` launcher. On this machine `python` / `python3` are broken Windows Store stub shims.

**macOS/Linux**: Use `python3` directly.

The target is Python 3.12.

## Commands

```powershell
# Windows
py -m pip install -r requirements.txt   # install deps
py bot.py                               # run the bot (reads .env)
py -m pytest                            # run the full test suite
py -m pytest -v                         # verbose
py -m pytest tests/test_expenses_db.py::test_record_expense_end_to_end_balance -v   # single test

# macOS/Linux
python3 -m pip install -r requirements.txt
python3 bot.py
python3 -m pytest
```

There is no build step and no linter configured. `.env` (gitignored) must contain:
- `DISCORD_TOKEN` — required, the bot's API token
- `GUILD_ID` — optional, a server ID for instant slash-command sync during development (leave blank for global sync, ~1 hour)
- `SUBSCRIPTION_KEY` — optional, generated via `Fernet.generate_key()` to enable encrypted password storage in `/sub-add`

## Deployment

**For local development**: Run `py bot.py` (Windows) or `python3 bot.py` (macOS/Linux) locally.

**For 24/7 hosting at no cost**: Deploy to Oracle Cloud's Always Free tier (1 Ampere A1 instance + 1 TB storage). See the README for step-by-step instructions. Use systemd to keep the bot running and auto-restart on crash.

## What this is

A full-featured Discord bot for managing a shared house/apartment with roommates. It handles expenses, bills, chores, groceries, meal voting, subscriptions, a house wiki, birthdays, vacation mode, anonymous suggestions, leaderboards, and a unified dashboard (`/homebase`). Built incrementally one feature at a time, following a three-layer architecture: pure functions (testable logic), DB functions (against `sqlite3`), and Discord command handlers. Tests use in-memory databases and do not require a live Discord connection.

All phases through Phase 5 are complete (Phases 1–5). Phase 6 (AI features) is planned but not yet started.

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

A new feature is a new file in `cogs/`. Wire it up by adding one `await self.load_extension("cogs.<name>")` line in `bot.py`'s `setup_hook`. Give the cog an `init_tables(conn)` for any new tables and call it from the cog's `__init__`. Keep pure logic and DB access as standalone functions (layers 1 and 2) so they can be unit-tested against the `conn` fixture; reserve the Cog methods for Discord plumbing and guards (DM rejection, house-exists check, membership check — see `_get_house_and_member` in `cogs/expenses.py` for the shared guard pattern). Give each feature one command per action with a single clear name (no shorthand aliases); when a command body would be shared, factor it into an `_impl` method.

## Roadmap

**Phases 1–5 are complete.** The bot is feature-complete and production-ready. Phase 6 (AI features) is planned but not yet started.

### Completed phases

The three core channels are fully operational:
- **`#chores`** — Automatic chore rotation, completion tracking, daily reminders, monthly rankings.
- **`#rent-and-utilities`** — Recurring bills (fixed/variable), payment tracking, due-date reminders, monthly summaries.
- **`#groceries`** — Shared grocery list, shopping-run summaries, monthly spending reports.

Plus cross-cutting systems: `/homebase` dashboard, meal voting, subscriptions (encrypted passwords), house wiki, vacation mode, birthdays, anonymous suggestions, and multi-system leaderboards.

### Architecture: the scheduler

To add a new auto-post: write a `render(conn, house_id, today) -> str | None` function in the feature cog and append a `ScheduledJob(key, channel, render)` to `JOBS` in `cogs/scheduler.py`. All jobs run once daily at `REMINDER_HOUR_UTC` (per-house time/timezone config is a future addition). Schedule-decision logic stays pure (layer 1) and per-house state lives in `schedule_state`.

### Phase 1 — Finance system (`#rent-and-utilities`)

**Complete.** See `cogs/expenses.py` and `cogs/finance.py`.

Features: `/expense`, `/pay`, `/balances`, `/bill-add`, `/bills`, `/bill-post`, `/bill-remove`. Equal splits in integer cents; net pairwise balances. Fixed bills auto-post on their due day. Auto-posts: due-date reminders, monthly summaries, payment confirmations.

### Phase 2 — Chores system (`#chores`)

**Complete.** See `cogs/chores.py`.

Features: `/chore-add`, `/chores`, `/complete`, `/swap`, `/chore-history`, `/leaderboard`. Automatic round-robin rotation (daily/weekly/monthly). Completion tracking with per-member tally. Auto-posts: daily reminders, monthly rankings, completion confirmations. The rotation algorithm is pure and unit-tested.

### Phase 3 — Groceries system (`#groceries`)

**Complete.** See `cogs/groceries.py`.

Features: `/grocery-add`, `/groceries`, `/grocery-bought`, `/grocery-remove`, `/grocery-done`. Categorized list (Food, Household, Cleaning). Active items unique via partial index. Auto-posts: trip summaries, monthly spending reports.

### Phase 4 — House life & coordination

**Complete.** See `cogs/meals.py`, `cogs/subscriptions.py`, `cogs/wiki.py`, `cogs/leaderboard.py`, `cogs/vacation.py`, `cogs/birthdays.py`, `cogs/suggestions.py`.

Features:
- **Meal voting**: `/meal-propose`, `/meal-vote`, `/meal-results`, `/meal-close`. One poll per house; ties broken by proposal order.
- **Subscriptions**: `/sub-add`, `/subs`, `/sub-password`, `/sub-update`, `/sub-remove`. Fernet-encrypted passwords at rest.
- **House wiki**: `/wiki-set`, `/wiki`, `/wiki-list`, `/wiki-remove`, `/wiki-setup`. Five categories + General; case-insensitive keys.
- **Leaderboards**: Cross-system monthly rankings (chores 1 pt, grocery runs 2 pts).
- **Vacation mode**: `/vacation-start`, `/vacation-end`, `/vacations`. Excludes members from chore rotation and bill splits; shared `active_member_ids` helper.
- **Birthdays**: `/birthday-set`, `/birthdays`. Month+day only; auto-post reminder on the day.
- **Suggestions**: `/suggestion`. Anonymous; posted numbered to `#suggestions`.

### Phase 5 — House Command Center

**Complete.** See `cogs/homebase.py`.

Features: `/homebase` dashboard. Single at-a-glance status: bills due, chores pending, groceries needed, house health score (0–100), top priority. Reads all other systems; owns no tables.

### Expense ledger & house deletion — DONE

- **`/ledger`** (`cogs/expenses.py`) — shows every expense you were charged for (not paid by you), with description, date, payer name, and your share. Ephemeral. Pure `get_ledger_entries` + `format_ledger`.
- **`/delete-house`** (`cogs/core.py`) — permanently deletes the house and all associated data (expenses, chores, bills, groceries, members, etc.). Admin-only (`manage_guild` permission); confirmation button required. Pure `delete_house_data` handles FK-safe deletion order.

### Settings & configuration (planned, not yet implemented)

Purpose: let each house tune the bot's behavior instead of relying on hardcoded constants. Today values like `REMINDER_HOUR_UTC`, `REMINDER_LEAD_DAYS`, and `SUMMARY_DAY` are module-level constants shared by every house; this feature will move per-house overrides into the DB.

Planned features:
- `/settings` — view the house's current configuration (with defaults shown where unset).
- `/set` — change one setting (validated). Candidates:
  - reminder time of day + timezone (replaces the global `REMINDER_HOUR_UTC`).
  - due-date reminder lead days (`REMINDER_LEAD_DAYS`) and monthly-summary day (`SUMMARY_DAY`).
  - per-auto-post enable/disable toggles (e.g. mute the daily chore reminder).

Settings will use a `get_setting(conn, house_id, key, default)` helper so missing rows fall back to today's constants (no migration needed).

### Phase 6 — AI features

Purpose: natural-language and document-understanding capabilities layered on top of the operational systems. These call out to an LLM and/or vision model; keep the prompt-building and response-parsing as pure functions (layer 1) so they can be tested with canned model responses, and isolate the model client behind a thin adapter. Build these last — they depend on the data the earlier phases produce.

- [ ] **House chat assistant** — answer natural-language questions against house data: "Who owes money?", "What's overdue?", "What chores are due today?", "What groceries do we need?". Routes the question to the relevant cog's read functions and summarizes.
- [ ] **AI meal planning / `/meal-plan`** — given a constraint ("Feed 6 people for under $80"), return a shopping list, recipes, and estimated costs; feeds the grocery list directly. (Deferred from Phase 3 — works better as an AI-assisted feature.)
- [ ] **Bill scanner** — upload a utility-bill PDF or image; extract the amount (vision/OCR), split it automatically, and create the payment/expense + reminders. Feeds the finance cog.
- [ ] **Usage prediction** — predict depletion from consumption patterns ("Toilet paper will run out in 6 days") and warn ahead of time. Feeds grocery inventory.
- [ ] **AI spending coach** — flag anomalies in spending and suggest likely causes. Example: "Electric bill is 22% higher this month. Possible causes: AC usage, more occupants."

Each phase is its own cog owning its own tables (`init_tables`), following the three-layer split and the guard pattern. Automated posts depend on the scheduler prerequisite above.
