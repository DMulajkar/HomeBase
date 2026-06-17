# Finance auto-posts (due-date reminders + monthly summary) — design

Date: 2026-06-17
Status: approved
Phase: 1 — Finance system (`#rent-and-utilities`)

## Purpose

Two new scheduled auto-posts that extend the recurring-bills feature, both
landing in `#rent-and-utilities`:

1. **Due-date reminders** — a daily heads-up listing bills coming due soon, so
   roommates can move money before the charge lands (and so variable bills,
   which never auto-post, get nudged for manual posting).
2. **Monthly financial summary** — a once-a-month report of outstanding
   balances (who owes whom), reusing the existing balance computation.

Both are **informational** — unlike `render_due_fixed_bills`, which has a
deliberate side effect (it posts the expense), these two read only and never
mutate the ledger.

> Note on the one-feature-per-pass rule: these two roadmap items were
> deliberately built together in one pass at the user's explicit request. They
> share the auto-post wiring and are small read-only renders.

## Decisions

- **Reminder window: fixed lead time.** A bill appears in the reminder when its
  (clamped) due date is between today and `REMINDER_LEAD_DAYS` (3) days out,
  inclusive. Per-bill lead times are deferred.
- **Reminders skip already-posted bills.** If a bill has been posted for the
  current period, it's no longer "upcoming" and is omitted — so posting rent
  early stops the nag.
- **Daily repeat within the window is intended.** The scheduler already dedupes
  to once per day; repeating "due in 3 / 2 / 1 days / today" is the point of a
  reminder, so no extra per-bill dedup is added.
- **Summary day: 1st of the month.** `SUMMARY_DAY = 1`. The render returns
  `None` on every other day, so the daily scheduler tick only posts it once a
  month. Balances are cumulative (all-time net), so the report is labelled
  "as of <date>" rather than claiming to cover a single month.
- **Best-effort monthly cadence.** If the bot is down for all of the summary
  day, that month's summary is skipped (matches the chore-reminder model). No
  catch-up.

## Architecture

No new tables and no new cog — both renders live in `cogs/finance.py` and reuse
existing helpers. The monthly summary reuses `expenses.compute_net_balances`,
`expenses.get_debts`, `expenses.get_payments`, and a new shared formatter
`expenses.format_net_balances` (factored out of `/balances` so the command and
the auto-post render identical lines).

### Layer 1 — pure functions (unit-tested)

- `days_until_due(today, due_day) -> int | None` — whole days from `today` to
  this month's `due_date_for_month(...)` (clamped to month length). Returns
  `None` when this month's due date has already passed. `0` on the due day.
- `is_summary_day(today, summary_day) -> bool` — `today.day == summary_day`.
- `expenses.format_net_balances(net, names) -> list[str]` — turns the net-balance
  map into `"<ower> owes <owee> $X.XX"` lines. Pure; used by `/balances` and the
  summary render.

### Layer 3 — render functions (DB-reading, no writes)

- `render_upcoming_bills(conn, house_id, today) -> str | None` — lists each
  un-posted bill whose `days_until_due` is in `[0, REMINDER_LEAD_DAYS]`, with
  amount (or "varies"), payer, and "due today" / "due in N day(s)". Variable
  bills get a `post with /bill-post` hint. Returns `None` when nothing is in the
  window (or the house has no members).
- `render_monthly_summary(conn, house_id, today) -> str | None` — `None` unless
  `is_summary_day(today, SUMMARY_DAY)` (and the house has members). Otherwise a
  header plus the net-balance lines, or "Everyone is settled up!" when clear.

### Scheduler integration

Append two jobs to `JOBS` in `cogs/scheduler.py` (both target
`rent-and-utilities`, both reuse the existing daily-tick / `is_due` plumbing
unchanged):

```python
ScheduledJob(key="bills-due-reminder", channel="rent-and-utilities",
             render=finance.render_upcoming_bills)
ScheduledJob(key="monthly-summary", channel="rent-and-utilities",
             render=finance.render_monthly_summary)
```

`_run_job` already skips `set_last_run` when a render returns `None`
(`scheduler.py`), so on non-summary days the monthly-summary job leaves its
state untouched and simply re-checks the next day.

## Testing (layers 1 & 3 against the `conn` fixture)

- `days_until_due`: future day, due day → 0, after due date → None, clamping in
  a short month.
- `is_summary_day`: true on the day, false otherwise.
- `render_upcoming_bills`: none with no bills; lists a bill inside the window
  ("in N days"); "due today" on the due day; excludes a bill outside the window;
  skips an already-posted bill; variable-bill hint present.
- `render_monthly_summary`: None off the summary day; "settled up" with no debts;
  reports an outstanding "X owes Y $Z" line after a posted bill.

## Scope (YAGNI)

- Fixed 3-day lead; no per-bill reminder config.
- Summary shows balances only (per roadmap: "outstanding balances, who owes
  whom") — no per-month spend breakdown.
- No catch-up if the bot misses the summary day.
- Payment confirmations remain a separate later roadmap item.

## Wiring

`bot.py` already loads `cogs.finance` before `cogs.scheduler`; no wiring change
is needed beyond the two new `JOBS` entries.
