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

A Discord bot for managing a shared house/apartment with roommates, built incrementally one feature at a time. So far: the expenses feature (`cogs/expenses.py`), channel setup (`cogs/channels.py`, an interactive picker that creates the house's Discord channels), the chores system slice 1 (`cogs/chores.py`, deterministic time-based rotation), an auto-post scheduler (`scheduler.py` + `cogs/scheduler.py`) that posts a daily chore reminder, and the recurring bills feature (`cogs/finance.py`, fixed/variable bills that post into the expenses ledger; fixed bills auto-post on their due day). Future features (groceries, maintenance, governance) will each arrive as a separate cog. **Do not build features ahead of the current request** — the scope is deliberately one feature per pass.

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

The target product is three operational house systems built around three core channels: `#chores`, `#rent-and-utilities`, and `#groceries`. This roadmap is the **plan**, not a license to build ahead — the one-feature-per-pass rule above still holds. Build phases top to bottom; within a phase, land features one at a time with tests. Check items off as they ship.

### Done

- [x] **Expenses cog** (`cogs/expenses.py`) — `/expense`, `/pay`, `/balances`; equal splits in integer cents; net pairwise balances. This is the foundation the finance system extends.
- [x] **Channel setup** (`cogs/channels.py`) — interactive picker that creates the `HomeBase` category and channels. Note: the current catalog has no `rent-and-utilities` channel — Phase 1 should add it.
- [x] **Chores slice 1** (`cogs/chores.py`) — deterministic time-based rotation (daily/weekly/monthly), `/chore-add`, `/chores`, `/complete`, `/swap` (one-off per-period override), `/chore-history` (completion tally). No auto-posting. Spec: `docs/superpowers/specs/2026-06-16-chores-slice-1-design.md`.
- [x] **Auto-post scheduler** (`scheduler.py` + `cogs/scheduler.py`) — `discord.ext.tasks` loop (15 min) that runs once-daily jobs at `REMINDER_HOUR_UTC` per house, resolving the target channel by name. Pure `is_due(now, last_run, hour)`; per-(house, job) state in `schedule_state`. Jobs register in the `JOBS` list. First job: daily chore reminder to `#chores`. Spec: `docs/superpowers/specs/2026-06-17-auto-post-scheduler-slice-1-design.md`.

### Cross-cutting prerequisite: scheduler — DONE

The scheduler exists (`scheduler.py` pure/DB + `cogs/scheduler.py` loop). To add a new auto-post: write a `render(conn, house_id, today) -> str | None` function in the feature cog and append a `ScheduledJob(key, channel, render)` to `JOBS` in `cogs/scheduler.py`. All jobs currently run once daily at `REMINDER_HOUR_UTC` (per-house time/timezone config is still a future addition). Schedule-decision logic stays pure (layer 1) and per-house state lives in `schedule_state`.

### Phase 1 — Finance system (`#rent-and-utilities`)

Purpose: the bot always knows who owes money, who is owed, current balances, and upcoming bills. Extends the existing expenses cog (likely a new `cogs/finance.py` that reuses the splitting/balance helpers, or an expansion of `expenses.py`).

- [x] Expense tracking, balance tracking, payment tracking, settlement calculations (already in expenses cog)
- [x] Add `rent-and-utilities` to the channel catalog
- [x] Recurring **bills**: rent, utilities, internet, shared subscriptions (`cogs/finance.py`; fixed vs variable kind, fixed payer per bill, equal split, monthly cadence). Spec: `docs/superpowers/specs/2026-06-17-recurring-bills-slice-1-design.md`.
- [x] `/bill-add`, `/bills`, `/bill-post`, `/bill-remove` commands; fixed bills auto-post on their due day via the scheduler; reuse `/pay` and `/balances`. (Supersedes the literal `/rent`/`/utilities` names — those would be aliases.)
- [x] Due-date reminders (auto-post): daily heads-up of bills due within 3 days (`render_upcoming_bills`). Spec: `docs/superpowers/specs/2026-06-17-finance-autoposts-slice-design.md`.
- [x] Monthly financial summary / report (auto-post): outstanding balances, who owes whom (`render_monthly_summary`, posts on the 1st). Same spec.
- [x] Payment confirmations (auto-post): `/pay` posts a confirmation with the updated pairwise balance to `#rent-and-utilities` (event-driven, not scheduler-based; `format_payment_confirmation` + `net_between` in `cogs/expenses.py`). Spec: `docs/superpowers/specs/2026-06-17-payment-confirmations-slice-design.md`.

**Phase 1 is complete.** Next up is Phase 2 (chores auto-posts: completion confirmations, overdue alerts, streaks/rankings).

### Phase 2 — Chores system (`#chores`)

Purpose: manage recurring house responsibilities and distribute them fairly over time.

- [x] Chore definitions with cadence: daily / weekly / monthly (`/chore-add`)
- [x] Chore assignments and **automatic rotation** (deterministic round-robin by time)
- [x] `/chores` (view), `/complete`, `/swap`, `/chore-history`
- [x] Completion tracking (contribution tally via `/chore-history`)
- [x] Daily chore reminder (auto-post to `#chores` via the scheduler)
- [ ] Confirmations on completion (auto-post)
- [ ] Overdue detection + alerts (auto-post)
- [ ] Streaks and contribution rankings (auto-post)

Keep the fairness/rotation algorithm a pure function (layer 1) so it is unit-tested in isolation.

### Phase 3 — Groceries system (`#groceries`)

Purpose: manage the shared grocery list, household supplies, and related spending.

- [ ] Shared grocery list with categories: Food / Household Supplies / Cleaning Supplies
- [ ] `/grocery add`, `/grocery remove`, `/grocery bought`
- [ ] Inventory tracking + low-stock warnings (auto-post)
- [ ] Shopping-run / purchase confirmations and trip summaries (auto-post)
- [ ] Grocery spending analytics / reports (auto-post; can feed the finance system)
- [ ] `/meal-plan` meal planning

### Phase 4 — House life & coordination

Purpose: the smaller quality-of-life systems that reduce roommate friction and keep shared knowledge in one place. Each is its own cog following the three-layer split; most are small enough to land in a single pass.

- [ ] **Shared meal voting** — propose meals and vote; the bot tallies and announces the winner. Feeds Phase 3 meal planning and grocery lists.
- [ ] **Subscription tracker** — track shared subscriptions (Netflix, Spotify Family, Amazon Prime, Costco membership): cost, renewal date, who pays. Likely a thin layer over the finance bills cog (a subscription is a fixed recurring bill) with subscription-specific listing.
- [ ] **House wiki** — store and retrieve house reference info: Wi-Fi password, landlord contact, lease information, utility account numbers, parking rules. Simple key/value notes per house, retrievable on demand.
- [ ] **Leaderboards** — monthly contribution rankings (chores completed, etc.), auto-posted. Example:

  ```
  🏆 June Rankings
  1. Sarah
  2. Dhruv
  3. Ryan
  ```

- [ ] **Vacation mode** — temporarily remove someone from the chore rotation, recalculate bill splits to exclude them for the period, and pause their reminders; restore on return.
- [ ] **Roommate birthdays** — store birthdays and auto-post reminders.
- [ ] **Anonymous suggestions** — `/suggestion` posts an anonymized suggestion to the house to surface tension without attribution.

### Phase 5 — House Command Center (the unifying dashboard)

Purpose: one command that rolls up the state of every other system. Depends on Phases 1–4 being in place (it reads from them; it owns no new domain data).

- [ ] **`/homebase`** — a single at-a-glance status report aggregating across cogs. Example:

  ```
  🏠 HOMEBASE

  Bills Due:          2
  Chores Due:         4
  Groceries Needed:   8
  Maintenance Issues: 1
  House Health:       92/100

  Top Priority: Pay electric bill by Thursday.
  ```

  Keep the aggregation/scoring (e.g. "house health", "top priority") as pure functions (layer 1) fed by each cog's existing read functions, so it is unit-testable without Discord.

### Phase 6 — AI features

Purpose: natural-language and document-understanding capabilities layered on top of the operational systems. These call out to an LLM and/or vision model; keep the prompt-building and response-parsing as pure functions (layer 1) so they can be tested with canned model responses, and isolate the model client behind a thin adapter. Build these last — they depend on the data the earlier phases produce.

- [ ] **House chat assistant** — answer natural-language questions against house data: "Who owes money?", "What's overdue?", "What chores are due today?", "What groceries do we need?". Routes the question to the relevant cog's read functions and summarizes.
- [ ] **AI meal planning** — given a constraint ("Feed 6 people for under $80"), return a shopping list, recipes, and estimated costs; can feed the grocery list.
- [ ] **Bill scanner** — upload a utility-bill PDF or image; extract the amount (vision/OCR), split it automatically, and create the payment/expense + reminders. Feeds the finance cog.
- [ ] **Usage prediction** — predict depletion from consumption patterns ("Toilet paper will run out in 6 days") and warn ahead of time. Feeds grocery inventory.
- [ ] **AI spending coach** — flag anomalies in spending and suggest likely causes. Example: "Electric bill is 22% higher this month. Possible causes: AC usage, more occupants."

Each phase is its own cog owning its own tables (`init_tables`), following the three-layer split and the guard pattern. Automated posts depend on the scheduler prerequisite above.
