# Auto-Post System (Scheduler) — Slice 1 Design

**Date:** 2026-06-17
**Status:** Approved

## Scope

The cross-cutting scheduler prerequisite plus its first job: a once-daily chore
**reminder** posted to `#chores`, listing each chore with its current assignee
and pending/done status. Reminders only — no overdue flagging.

This unblocks all future auto-posts (other jobs just register with the
scheduler).

## Architecture

### `scheduler.py` (module, like `database.py`)

Pure due-logic plus a `schedule_state` table (owned here, per the
cog-owns-its-tables convention).

- **Pure:** `is_due(now: datetime, last_run_date: date | None, reminder_hour: int) -> bool`
  — true when `now.hour >= reminder_hour` and we have not already run today
  (`last_run_date is None or last_run_date < now.date()`), all in UTC.
- **DB (conn first arg):**
  - `init_tables(conn)`
  - `get_last_run_date(conn, house_id, job_key) -> date | None`
  - `set_last_run(conn, house_id, job_key, run_date, run_at=None)` (upsert)

`schedule_state` columns: `house_id`, `job_key`, `last_run_date`, `last_run_at`,
PRIMARY KEY `(house_id, job_key)`.

### `cogs/scheduler.py` (the `Scheduler` cog)

Runs a `discord.ext.tasks` loop every 15 minutes; `before_loop` calls
`wait_until_ready`. Each tick (now = UTC):

1. `database.list_houses(db)`.
2. For each house, resolve its guild via `bot.get_guild(int(guild_id))`; skip if
   the bot isn't in it.
3. For each registered job, if `scheduler.is_due(now, last_run, REMINDER_HOUR_UTC)`:
   - resolve the target channel by name (`discord.utils.get(guild.text_channels,
     name=job.channel)`); skip if missing.
   - `message = job.render(db, house_id, now.date())`; skip if `None`/empty.
   - `await channel.send(message)`; on `discord.Forbidden`, skip.
   - `scheduler.set_last_run(db, house_id, job.key, now.date(), now)`.

DB calls remain synchronous on the loop thread (single-connection rule); only
`channel.send` is awaited.

**Job registry:** a small `JOBS` list. Slice 1 has one entry:
`chores-reminder` → channel `chores` → `chores.render_chores_reminder`. Future
auto-posts append entries here.

Constants: `REMINDER_HOUR_UTC = 9`, `CHECK_INTERVAL_MINUTES = 15`.

### `cogs/chores.py`

- Add `render_chores_reminder(conn, house_id, today) -> str | None` — returns
  `None` when there are no chores (so nothing posts); otherwise a message listing
  each chore with assignee (override applied) and pending/done status.
- Extract a shared helper `current_assignee(conn, chore, member_ids, today) ->
  (assignee_id, done, swapped, period_index)` used by both `/chores` and
  `render_chores_reminder` to avoid duplicating assignee/override/completion logic.

### `database.py`

- Add `list_houses(conn) -> list[Row]` (the `houses` table is owned here).

## Behavior details

- **Reminder hour:** constant `REMINDER_HOUR_UTC = 9`. Per-house/timezone
  configuration is deferred.
- **Once per day:** `last_run` is recorded only when a message is actually
  posted, so the first time there are chores to remind about on/after the hour,
  it posts exactly once that day; subsequent ticks that day are not due.
- **Missing channel / no permission / bot not in guild:** silently skipped that
  tick; it will retry next tick (and post once the situation is fixed, still at
  most once that day).

## Testing (layers 1 & 2 only — no Discord client)

- `is_due`: before the hour; after the hour but already ran today; after the hour
  on a new day; never run before.
- `set_last_run` / `get_last_run_date` roundtrip and upsert (second write
  overwrites).
- `render_chores_reminder`: `None` when no chores; contains each chore name and
  its assignee when chores exist.
- The `tick` loop is Discord plumbing and is not unit-tested.

## Wiring

- Load `cogs.scheduler` in `bot.py`'s `setup_hook` (after the feature cogs so
  their render functions are importable).
- Roadmap/CLAUDE.md: mark the scheduler prerequisite done and the chores
  "reminders" auto-post item done.

## Out of scope (YAGNI for slice 1)

- Per-house reminder hour / timezone configuration.
- Overdue alerts, streaks, rankings, completion confirmations (later jobs).
- Catch-up suppression (on startup after the hour, the day's reminder will post
  if it hasn't yet — acceptable).
