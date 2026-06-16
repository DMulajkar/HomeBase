# Discord House Bot: Project Scaffold + Expenses Feature

Date: 2026-06-16

## Purpose

Build a Discord bot for managing a shared house/apartment with roommates. Long-term
scope includes chore management, expense splitting/debt tracking, grocery lists,
maintenance tickets, scheduling, and house governance, but the bot is built
incrementally, one feature at a time.

This spec covers:
1. The project scaffold (entry point, cog structure, core database schema) that
   every future feature will build on.
2. The first complete feature: expense splitting and debt tracking.

Stack: Python, discord.py (slash commands / `app_commands`), SQLite, cogs-based
command structure.

## Out of scope (for this slice)

Chores, groceries, maintenance tickets, scheduling, governance — to be designed and
built in separate future passes.

## Project layout

```
HomeBase/
├── bot.py                  # entry point: loads token, registers cogs, starts bot
├── database.py             # sqlite connection + houses/members schema & helpers
├── cogs/
│   ├── __init__.py
│   ├── core.py              # /house-setup, /join-house — infra, not a "feature"
│   └── expenses.py          # expense feature: commands + its own table setup
├── requirements.txt
└── .env.example
```

`core.py` exists because `/house-setup` and `/join-house` have to live somewhere to
populate the houses/members tables — they're plumbing every future feature depends
on, not a "feature" like chores/groceries, so they're kept out of `expenses.py`.

## Core data model (`database.py`)

`database.py` owns connection setup and the two core tables that every future
feature will reference:

```sql
CREATE TABLE houses (
    house_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE members (
    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL REFERENCES houses(house_id),
    discord_user_id TEXT NOT NULL,
    display_name TEXT,
    joined_at TEXT NOT NULL,
    UNIQUE(house_id, discord_user_id)
);
```

A "member" row is scoped to one house, since the same Discord user could in
principle be a member of multiple houses (servers) the bot serves.

`database.py` exposes plain functions other modules use (no ORM). Every function
takes the sqlite connection as an explicit first argument rather than relying on
module-level state — this keeps the functions trivially testable against an
in-memory database:
- `connect(path)` — opens and returns a sqlite connection (row factory set to
  `sqlite3.Row`).
- `init_db(conn)` — ensures the core tables exist on the given connection.
- `get_house(conn, guild_id)` / `create_house(conn, guild_id, name)`
- `get_member(conn, house_id, discord_user_id)` / `add_member(conn, house_id, discord_user_id, display_name)`
- `list_members(conn, house_id)`

The bot opens a single connection at startup (`bot.py`) and stores it on the bot
instance as `bot.db`; cogs access it via `self.bot.db`, which serves as the
"shared connection" every feature reads and writes through. Each feature cog
creates and owns its own tables (foreign-keyed to `houses` / `members`) using that
shared connection — `expenses.py` does this for its tables, and future cogs
(chores, groceries, etc.) will follow the same pattern.

## Core commands (`cogs/core.py`)

- `/house-setup` — creates the house row for the current Discord server (keyed on
  guild ID). Errors if a house already exists for this server.
- `/join-house` — registers the calling user as a member of this server's house.
  Errors if the house isn't set up yet, or if the user already joined.

Both commands reject usage outside a guild (DMs).

## Expenses feature (`cogs/expenses.py`)

### Feature tables

```sql
CREATE TABLE expenses (
    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL REFERENCES houses(house_id),
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    paid_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
    created_at TEXT NOT NULL
);

CREATE TABLE expense_splits (
    split_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL REFERENCES expenses(expense_id),
    member_id INTEGER NOT NULL REFERENCES members(member_id),
    share_cents INTEGER NOT NULL
);

CREATE TABLE settlements (
    settlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL REFERENCES houses(house_id),
    from_member_id INTEGER NOT NULL REFERENCES members(member_id), -- who paid cash
    to_member_id INTEGER NOT NULL REFERENCES members(member_id),   -- who received it
    amount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

All money is stored as integer cents to avoid floating point rounding errors.
User-facing amounts are entered/displayed as decimal dollars (e.g. `12.50`) and
converted to/from cents at the command boundary.

### Equal-split logic

When an expense is added for amount `amount_cents` split across `N` current house
members:
- Each member's base share is `amount_cents // N`.
- The remainder `amount_cents % N` cents is distributed one cent at a time to the
  first `remainder` members (stable order, e.g. by `member_id`), so the shares
  always sum exactly to `amount_cents`.
- The payer is included in the split (they owe their own share too; paying for the
  expense just means they fronted the cash).
- One `expense_splits` row is written per member.

### Commands

- `/add-expense description amount [paid_by]` — records a new expense. `paid_by`
  defaults to the invoking user if omitted. Splits the amount equally across all
  current house members per the logic above.
  - Shorthand: `/pay description amount [paid_by]` — identical behavior, calls the
    same underlying function.
- `/settle amount to` — records that the invoking user paid `amount` in cash to
  member `to`, to be netted against what they owe each other. Writes a row to
  `settlements` (`from_member_id` = invoker, `to_member_id` = `to`).
- `/balances` — computes and displays net pairwise debts across all house members.
  - Shorthand: `/bal` — identical behavior, calls the same underlying function.

### Balance computation

For any pair of members (X, Y):
- `debt(X,Y)` = sum of `share_cents` from `expense_splits` where the split's
  member is X and the expense's `paid_by_member_id` is Y (i.e. amounts X owes Y
  from expenses Y paid for).
- `paid(X,Y)` = sum of `amount_cents` from `settlements` where `from_member_id` = X
  and `to_member_id` = Y (cash X already paid Y).

Net amount X owes Y = `debt(X,Y) - debt(Y,X) - paid(X,Y) + paid(Y,X)`.

- If positive: X owes Y that amount.
- If negative: Y owes X the absolute value.
- If zero: the pair is settled and omitted from `/balances` output.

`/balances` iterates over all distinct member pairs in the house, computes the net
per pair, and lists only the non-zero ones (e.g. "Bob owes Alice $30.00"). If every
pair nets to zero, it reports that the house is fully settled.

### Error handling

- All expense commands reject usage outside a guild (DMs).
- All expense commands require the house to be set up and the invoking user to be
  a registered member; errors point the user to `/house-setup` / `/join-house`.
- `paid_by` (for `/add-expense`/`/pay`) and `to` (for `/settle`) must already be
  registered house members, otherwise the command errors out.
- `/add-expense`/`/pay` requires at least one house member to exist (the payer
  counts, so this is effectively always true once the payer has joined).
- Amounts must be positive.

## Supporting files

- `requirements.txt` — `discord.py`, `python-dotenv`.
- `.env.example` — `DISCORD_TOKEN=` placeholder, documents the required env var.
- `bot.py` — loads `DISCORD_TOKEN` from environment via `python-dotenv`, creates the
  bot with slash-command support, calls `database.init_db()`, loads the `core` and
  `expenses` cogs as extensions, and runs the bot.

## Testing approach

Given this is a stateful Discord bot, testing focuses on the parts that don't
require a live Discord connection:
- Unit tests for the equal-split remainder-distribution logic (various N and
  amounts, including non-divisible cases).
- Unit tests for the net pairwise balance computation given a set of expenses and
  settlements (including the zero-net / fully-settled case, and the
  overpayment-flips-direction case).
- Unit tests for `database.py` helper functions against an in-memory SQLite DB
  (house/member creation, uniqueness constraints).

Manual verification of the actual slash commands against a real Discord server is
out of scope for automated tests but should be done once implemented.
