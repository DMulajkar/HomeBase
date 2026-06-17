# Recurring bills — slice 1 design

Date: 2026-06-17
Status: approved
Phase: 1 — Finance system (`#rent-and-utilities`)

## Purpose

Give the house a way to track recurring bills (rent, utilities, internet,
shared subscriptions) so the bot always knows what's owed and when. A bill is a
**recurring template**; "posting" a bill for a month creates a normal expense
through the existing expenses ledger, so all resulting debt flows into the
current `/balances` and `/pay` system unchanged. Bills add only the
recurring/scheduling layer on top of expenses — they do not reinvent the ledger.

## Decisions (from brainstorming)

- **Posting model: hybrid by type.** Fixed bills auto-post on their due day via
  the scheduler; variable bills are posted manually with the real amount.
- **Payer: fixed per bill.** Each bill stores one designated payer (the person
  others owe), set when the bill is created.
- **Split: equal among all current members.** Reuses `expenses.split_amount`;
  custom per-member shares are deferred.

## Architecture

New cog `cogs/finance.py`, owning its own tables, following the three-layer
split. It reuses `cogs/expenses.py` helpers — `record_expense` (which writes the
`expenses` + `expense_splits` rows and feeds `get_debts`) and `split_amount`.
The finance cog imports `from cogs import expenses`.

### Layer 1 — pure functions (unit-tested)

- `due_date_for_month(year, month, due_day) -> date` — returns the bill's due
  date for a given month, **clamping** `due_day` to the month's length (e.g.
  day 31 in February → Feb 28/29; day 31 in April → Apr 30).
- `period_key(d: date) -> str` — `"YYYY-MM"` for the date's month.
- `fixed_bill_period_to_post(today, due_day, start_date) -> str | None` —
  returns the period key (`"YYYY-MM"`) that a fixed bill should post for, or
  `None`. Returns the current month's period when `today >= due_date_for_month(
  today's month)` **and** that due date is on/after `start_date` (no retroactive
  back-billing of months before the bill existed); otherwise `None`. The caller
  still checks whether that period was already posted.

### Layer 2 — DB functions (each takes `sqlite3.Connection` first)

- `init_tables(conn)` — creates `bills` and `bill_postings` (below). Called from
  the cog's `__init__`.
- `add_bill(conn, house_id, name, kind, amount_cents, due_day, payer_member_id,
  start_date) -> int` — raises `ValueError` on duplicate name in the house.
- `get_bill(conn, house_id, name) -> Row | None`
- `list_bills(conn, house_id) -> list[Row]`
- `remove_bill(conn, house_id, name) -> bool` — deletes the bill and its
  `bill_postings` rows. Expenses already created stay (they are real debt).
- `is_posted(conn, bill_id, period) -> bool`
- `record_posting(conn, bill, period, amount_cents, member_ids) -> int` —
  the integration point. Raises `ValueError` if the period is already posted;
  otherwise calls `expenses.record_expense` (description `"<name> — <period>"`,
  the given amount, the bill's fixed payer, split equally across `member_ids`),
  inserts the `bill_postings` row, and returns the new `expense_id`. Relies on
  the single-threaded event-loop model (per CLAUDE.md) for the
  check-then-insert; no cross-thread race exists.

### Layer 3 — Discord plumbing

Reuses the `_get_house_and_member` guard pattern. Commands (clean single names,
no aliases — this supersedes the roadmap's literal `/rent` and `/utilities`,
which would be aliases for the same actions):

- `/bill-add name kind amount due_day payer`
  - `kind`: `Literal["fixed", "variable"]`.
  - `amount`: dollars, **required for fixed**, ignored/optional for variable.
  - `due_day`: int 1–31 (clamped per month when posting).
  - `payer`: `discord.Member`, must be a house member.
  - `start_date` = today (UTC). Validates positive amount for fixed, due_day
    range, unique name, payer membership.
- `/bills` — lists each bill: name, kind, amount (or "varies"), due day, payer
  display name, and this month's status (✅ posted / ⏳ pending).
- `/bill-post name [amount]` — posts the current month for `name`. `amount`
  (dollars) is **required for variable** bills and an **optional override** for
  fixed (defaults to the saved amount). Refuses with a clear message if the
  current period is already posted. Announces the created expense.
- `/bill-remove name` — deletes the recurring definition (past expenses remain).

### Scheduler integration

Append one job to `JOBS` in `cogs/scheduler.py`:

```python
ScheduledJob(key="fixed-bills", channel="rent-and-utilities",
             render=finance.render_due_fixed_bills)
```

`render_due_fixed_bills(conn, house_id, today) -> str | None` (layer 3 in the
finance cog) iterates the house's **fixed** bills; for each, computes
`fixed_bill_period_to_post`; if non-`None` and not `is_posted`, calls
`record_posting` and collects an announcement line. Returns the combined
announcement, or `None` when nothing is due. This reuses the existing
daily-tick / `is_due` plumbing unchanged — the only scheduler edit is the JOBS
entry and a `from cogs import finance` import. The render has a **deliberate
side effect** (it posts the expense); this is documented at the function and is
safe because `bill_postings`' `UNIQUE(bill_id, period)` plus the up-front
`is_posted` check make posting exactly-once per period regardless of how often
the tick runs or whether the channel send succeeds.

## Schema

```sql
CREATE TABLE IF NOT EXISTS bills (
    bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_id INTEGER NOT NULL REFERENCES houses(house_id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fixed', 'variable')),
    amount_cents INTEGER,          -- required for fixed; NULL for variable
    due_day INTEGER NOT NULL,      -- 1–31, clamped to month length when posting
    payer_member_id INTEGER NOT NULL REFERENCES members(member_id),
    start_date TEXT NOT NULL,      -- date the bill was created (gates back-billing)
    created_at TEXT NOT NULL,
    UNIQUE(house_id, name)
);

CREATE TABLE IF NOT EXISTS bill_postings (
    posting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(bill_id),
    period TEXT NOT NULL,          -- 'YYYY-MM'
    amount_cents INTEGER NOT NULL,
    expense_id INTEGER NOT NULL REFERENCES expenses(expense_id),
    posted_at TEXT NOT NULL,
    UNIQUE(bill_id, period)
);
```

## Error handling

- Duplicate bill name in a house → `ValueError` (DB) → friendly ephemeral reply.
- Posting an already-posted period → `ValueError` → friendly ephemeral reply.
- Fixed bill with no/zero amount, due_day out of 1–31, non-member payer →
  rejected at the command layer with an ephemeral message.
- Scheduler channel missing or send forbidden → posting still recorded (debt is
  real); announcement simply skipped (existing `_run_job` behavior).

## Testing (layers 1 & 2 only, against the `conn` fixture)

- `due_date_for_month` clamping: Feb (non-leap and leap), 30-day and 31-day
  months, normal days.
- `period_key` formatting.
- `fixed_bill_period_to_post`: before due date → None; on/after due date →
  period; due date before `start_date` → None.
- `add_bill` + duplicate-name `ValueError`; `get_bill`; `list_bills`;
  `remove_bill` (removes bill + its postings; returns False for unknown).
- `is_posted` / `record_posting`: creates an expense that shows up in
  `expenses.get_debts` and `compute_net_balances`; double-post raises
  `ValueError`; variable posting uses the supplied amount; payer is the fixed
  payer; split is equal.
- `render_due_fixed_bills`: posts due fixed bills, is idempotent across repeated
  calls in the same period, ignores variable bills, returns `None` when nothing
  is due.

## Scope (YAGNI)

- **Monthly cadence only.** `due_day` implies monthly; weekly/annual deferred.
- **Due-date reminders** (nudging before a variable bill is due) remain a
  separate later roadmap item. This slice ships: definitions, fixed-bill
  auto-posting, and manual posting.
- No `/bill-edit` (remove + re-add).
- No custom per-member split shares.

## Wiring

`bot.py` `setup_hook` loads `cogs.finance` **before** `cogs.scheduler` (the
scheduler's `JOBS` references `finance.render_due_fixed_bills` at import time).
