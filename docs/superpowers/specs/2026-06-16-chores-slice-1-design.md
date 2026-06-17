# Chores System — Slice 1 Design

**Date:** 2026-06-16
**Status:** Approved

## Scope

The first slice of the chores system (Phase 2 of the roadmap), covering the
"Core + rotation engine" without the scheduler:

- Define chores with a cadence (daily / weekly / monthly).
- See current assignments (`/chores`).
- Mark a chore done for the current period (`/complete`).
- Override the current period's assignee (`/swap`).
- View a contribution tally (`/chore-history`).

**Deferred to later slices:** streaks, overdue alerts, and any auto-posted
reminders/rotations (these need the cross-cutting scheduler, which does not
exist yet).

New cog `cogs/chores.py`, owning its own tables, following the three-layer
architecture and the `_get_house_and_member` guard pattern.

## Rotation model

Rotation is **deterministic by time** — no scheduler required. A chore stores a
`cadence` and a `start_date` (set to the creation date). The current assignee is
a pure function of the date:

- `period_index` = number of periods elapsed since `start_date`:
  - **daily:** `(today - start_date).days`
  - **weekly:** `(today - start_date).days // 7`
  - **monthly:** calendar-month offset `(today.year - start.year) * 12 + (today.month - start.month)`
- `assignee = members_ordered[period_index % N]`, where `members_ordered` is the
  house members ordered by `member_id` (stable).

Daily/weekly periods anchor to `start_date`; **monthly periods rotate on calendar
month boundaries** (the 1st), not on the start day-of-month. This simplification
is intentional for slice 1 and documented to callers.

`/chores` computes the current assignee on demand, so nothing needs to be
scheduled or pre-rotated.

## Data model (chores cog owns these tables)

1. **`chores`**
   - `chore_id` INTEGER PK
   - `house_id` INTEGER FK → houses
   - `name` TEXT
   - `cadence` TEXT ('daily' | 'weekly' | 'monthly')
   - `start_date` TEXT (ISO date)
   - `created_at` TEXT
   - `UNIQUE(house_id, name)`

2. **`chore_completions`** — one completion per chore per period
   - `completion_id` INTEGER PK
   - `chore_id` INTEGER FK → chores
   - `period_index` INTEGER
   - `member_id` INTEGER FK → members
   - `completed_at` TEXT
   - `UNIQUE(chore_id, period_index)`

3. **`chore_swaps`** — per-period assignee override
   - `swap_id` INTEGER PK
   - `chore_id` INTEGER FK → chores
   - `period_index` INTEGER
   - `member_id` INTEGER FK → members (who is now responsible this period)
   - `created_at` TEXT
   - `UNIQUE(chore_id, period_index)`

A swap is a one-off override of a single period's assignee; the next period
resumes the normal rotation order.

## Layer 1 — pure functions (unit-tested)

- `CADENCES`: the allowed cadence values.
- `current_period_index(cadence, start_date, today) -> int`
- `assignee_for_period(member_ids_ordered, period_index) -> member_id`
- `period_end_date(cadence, start_date, period_index) -> date` (for "due by")

All take/return plain `datetime.date` values so they are testable without
Discord or a DB.

## Layer 2 — DB functions (take `conn` first, unit-tested)

- `init_tables(conn)`
- `add_chore(conn, house_id, name, cadence, start_date) -> chore_id`
  (raises `ValueError` on duplicate name in a house)
- `get_chore(conn, house_id, name)`
- `list_chores(conn, house_id)`
- `record_completion(conn, chore_id, period_index, member_id)`
  (raises `ValueError` if that period is already completed)
- `get_completion(conn, chore_id, period_index)`
- `record_swap(conn, chore_id, period_index, member_id)` (upsert override)
- `get_override(conn, chore_id, period_index)`
- `completion_counts(conn, house_id) -> list[(member_id, display_name, count)]`

## Layer 3 — commands (cog methods, guarded)

Guard via a local `_get_house_and_member` (DM rejection, house-exists,
membership), matching the per-cog convention.

- `/chore-add name cadence` — `cadence` is a daily/weekly/monthly choice;
  `start_date = today (UTC)`. Rejects duplicate names.
- `/chores` — lists each chore: cadence, current assignee (override applied),
  done/pending this period, and due-by date.
- `/complete name` — caller marks the current period done; rejects if already
  completed or chore unknown.
- `/swap name member` — sets `member` as the current period's assignee
  (override). `member` must be a house member.
- `/chore-history` — completion-count tally per member.

## Wiring

- Register `cogs.chores` in `bot.py`'s `setup_hook`.
- The `#chores` channel already exists in the channel catalog — no change there.

## Testing

Matching the existing suite (layers 1 & 2 only, no Discord client):

- **Layer 1:** period index across boundaries for each cadence; rotation
  wrap-around; period_end_date.
- **Layer 2:** add/list/duplicate chores; completion insert + uniqueness;
  swap override upsert; completion_counts tally.

## Out of scope (YAGNI for slice 1)

- Scheduler and any automatic posting (reminders, overdue alerts, rotations).
- Streaks and weighted fairness scoring.
- Editing a chore's cadence/members; per-chore participant subsets.
- Deleting chores (can be added later if needed).
