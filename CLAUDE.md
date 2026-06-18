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

A Discord bot for managing a shared house/apartment with roommates, built incrementally one feature at a time. So far: the expenses feature (`cogs/expenses.py`), channel setup (`cogs/channels.py`, an interactive picker that creates the house's Discord channels), the chores system slice 1 (`cogs/chores.py`, deterministic time-based rotation), an auto-post scheduler (`scheduler.py` + `cogs/scheduler.py`) that posts a daily chore reminder, the recurring bills feature (`cogs/finance.py`, fixed/variable bills that post into the expenses ledger; fixed bills auto-post on their due day), and the groceries feature (`cogs/groceries.py`, a shared categorized grocery list). Future features (maintenance, governance) will each arrive as a separate cog. **Do not build features ahead of the current request** — the scope is deliberately one feature per pass.

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
- [x] Confirmations on completion (auto-post): `/complete` posts a public confirmation with the member's contribution count to `#chores` (event-driven, like payment confirmations; `format_completion_confirmation` + `member_completion_count` in `cogs/chores.py`). Spec: `docs/superpowers/specs/2026-06-17-chore-completion-confirmations-slice-design.md`.
- [~] ~~Overdue detection + alerts (auto-post)~~ — **dropped** (2026-06-17, product decision; not building).
- [x] Streaks and contribution rankings (auto-post): monthly chore leaderboard posted to `#chores` on the 1st, summarizing the month that just ended, with per-member streaks (`render_rankings`, plus pure `rank_members` / `monthly_streak` / `format_rankings` in `cogs/chores.py`). Spec: `docs/superpowers/specs/2026-06-17-chore-rankings-slice-design.md`.

**Phase 2 is complete** (overdue alerts deliberately dropped). Next up is Phase 3 (Groceries system).

Keep the fairness/rotation algorithm a pure function (layer 1) so it is unit-tested in isolation.

### Phase 3 — Groceries system (`#groceries`)

Purpose: manage the shared grocery list, household supplies, and related spending.

- [x] **Groceries slice 1** (`cogs/groceries.py`) — shared grocery list with categories (Food / Household Supplies / Cleaning Supplies); `/grocery-add`, `/groceries` (view), `/grocery-bought`, `/grocery-remove`. Active items are unique per house via a partial index, so a bought item becomes history and can be needed again. No auto-posts yet. Spec: `docs/superpowers/specs/2026-06-17-groceries-slice-1-design.md`. (Command names are flat/hyphenated to match `/chore-add`, `/bill-add` — superseding the `/grocery add` subcommand spelling in the original roadmap.)
- [~] ~~Inventory tracking + low-stock warnings (auto-post)~~ — **skipped** (product decision).
- [x] Shopping-run trip summary: `/grocery-done` clears the whole active list (marks all items bought), optionally records a split expense for the total spend, and posts a trip summary to `#groceries` (event-driven, same channel-fallback pattern as `/pay` and `/complete`). Pure `format_trip_summary`; DB `finish_shopping_run`. Per-item confirmations were deliberately skipped (too noisy for grocery runs).
- [x] Grocery spending analytics / reports (auto-post): monthly spend report posted to `#groceries` on the 1st, summarizing the previous month's total and per-member breakdown. Runs tracked in `grocery_runs` table (records `expense_id`, `amount_cents`, `run_at`). Pure `spending_by_member`, `format_spending_report`; DB `grocery_runs_for_month`; `render_spending_report` wired as a `ScheduledJob`.
- [~] ~~`/meal-plan` meal planning~~ — **deferred to Phase 6 (AI features)**, where it fits better as an AI-assisted feature.

**Phase 3 is complete.** Next up is Phase 4 (house life & coordination).

### Phase 4 — House life & coordination

Purpose: the smaller quality-of-life systems that reduce roommate friction and keep shared knowledge in one place. Each is its own cog following the three-layer split; most are small enough to land in a single pass.

- [x] **Shared meal voting** (`cogs/meals.py`) — one open poll per house; `/meal-propose` adds options (starts the poll if none is open); `/meal-vote` casts or changes a vote; `/meal-results` shows standings; `/meal-close` closes the poll and announces the winner to `#groceries`. Ties broken by proposal order. Pure `tally_votes`, `format_poll_results`, `format_winner`; DB `meal_polls`, `meal_options`, `meal_votes`.
- [x] **Subscription tracker** (`cogs/subscriptions.py`) — store shared subscription credentials: name, email, and password (Fernet-encrypted at rest; key in `.env` as `SUBSCRIPTION_KEY`, never committed). `/sub-add`, `/subs` (names + emails only, no passwords shown), `/sub-password` (always ephemeral), `/sub-update`, `/sub-remove`. Requires `cryptography>=42.0.0`.
- [x] **House wiki** (`cogs/wiki.py`) — categorized key/value reference store. Five categories (Access & Security, Utilities & Services, Building & Maintenance, House Rules, Lease & Legal) plus General. `/wiki-set key value [category]` upserts; `/wiki key` retrieves; `/wiki-list` shows all grouped by category; `/wiki-remove` deletes; `/wiki-setup` seeds 27 common entries as `(not set)` placeholders (skips any already filled in). Keys are case-insensitive. DB column added safely via `ALTER TABLE` for existing installs.
- [x] **Leaderboards** (`cogs/leaderboard.py`) — cross-system monthly rankings combining chores (1 pt) and grocery runs (2 pts). `/leaderboard` shows the current month on demand; `render_monthly_leaderboard` auto-posts to `#chores` on the 1st (summarizes the previous month). Pure `compute_scores` (competition-tie ranking), `format_leaderboard`. Example output:

  ```
  🏆 June Rankings
  1. Sarah
  2. Dhruv
  3. Ryan
  ```

- [ ] **Vacation mode** — temporarily remove someone from the chore rotation, recalculate bill splits to exclude them for the period, and pause their reminders; restore on return.
- [ ] **Roommate birthdays** — store birthdays and auto-post reminders.
- [x] **Anonymous suggestions** (`cogs/suggestions.py`) — `/suggestion text` posts the text to `#suggestions` without attribution; user gets an ephemeral confirmation only. Member ID stored in DB for moderation but never shown. Pure `format_suggestion(text, number)`; DB `record_suggestion` / `suggestion_count`.

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

### Settings & configuration (cross-cutting)

Purpose: let each house tune the bot's behavior instead of relying on hardcoded constants. Today values like `REMINDER_HOUR_UTC`, `REMINDER_LEAD_DAYS`, and `SUMMARY_DAY` are module-level constants shared by every house; this feature moves per-house overrides into the DB. Own its own `settings` table (one row per `house_id`, or key/value per house) and follow the three-layer split: pure validation/coercion, DB get/set with sensible defaults, and `/settings` plumbing.

- [ ] **`/settings`** — view the house's current configuration (with defaults shown where unset).
- [ ] **`/set`** — change one setting (validated). Candidate settings:
  - reminder time of day + timezone (replaces the global `REMINDER_HOUR_UTC`; the scheduler note above flags this as the long-planned per-house config).
  - due-date reminder lead days (`REMINDER_LEAD_DAYS`) and monthly-summary day (`SUMMARY_DAY`).
  - per-auto-post enable/disable toggles (e.g. mute the daily chore reminder) — pairs with vacation mode in Phase 4.
- [ ] Settings are read by the scheduler and feature cogs through a `get_setting(conn, house_id, key, default)` helper, so a missing row always falls back to today's constant (no migration needed; the constants become the defaults).

Keep validation pure (layer 1) and the read path cheap — the scheduler tick reads settings per house every cycle.

### Phase 6 — AI features

Purpose: natural-language and document-understanding capabilities layered on top of the operational systems. These call out to an LLM and/or vision model; keep the prompt-building and response-parsing as pure functions (layer 1) so they can be tested with canned model responses, and isolate the model client behind a thin adapter. Build these last — they depend on the data the earlier phases produce.

- [ ] **House chat assistant** — answer natural-language questions against house data: "Who owes money?", "What's overdue?", "What chores are due today?", "What groceries do we need?". Routes the question to the relevant cog's read functions and summarizes.
- [ ] **AI meal planning / `/meal-plan`** — given a constraint ("Feed 6 people for under $80"), return a shopping list, recipes, and estimated costs; feeds the grocery list directly. (Deferred from Phase 3 — works better as an AI-assisted feature.)
- [ ] **Bill scanner** — upload a utility-bill PDF or image; extract the amount (vision/OCR), split it automatically, and create the payment/expense + reminders. Feeds the finance cog.
- [ ] **Usage prediction** — predict depletion from consumption patterns ("Toilet paper will run out in 6 days") and warn ahead of time. Feeds grocery inventory.
- [ ] **AI spending coach** — flag anomalies in spending and suggest likely causes. Example: "Electric bill is 22% higher this month. Possible causes: AC usage, more occupants."

Each phase is its own cog owning its own tables (`init_tables`), following the three-layer split and the guard pattern. Automated posts depend on the scheduler prerequisite above.
