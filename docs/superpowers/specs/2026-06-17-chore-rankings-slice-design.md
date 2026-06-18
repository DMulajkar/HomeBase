# Chore streaks & rankings (auto-post) — design

Date: 2026-06-17
Status: approved
Phase: 2 — Chores system (`#chores`) — final item (completes Phase 2)

## Purpose

Once a month, post a 🏆 leaderboard to `#chores` ranking housemates by chores
completed in the month that just ended, plus a streak callout for members on a
multi-month roll. Turns the contribution tally (`/chore-history`) into recurring
recognition that nudges participation.

Note: the sibling Phase 2 item "overdue detection + alerts" was **dropped**
(product decision, 2026-06-17) and is not built.

## Decision: scheduler-driven, monthly, summarizing the previous month

Unlike the event-driven completion confirmation, "rankings" is a periodic
roll-up of stored state — it fits the daily `render(conn, house_id, today) ->
str | None` scheduler recipe, same as the finance monthly summary. It posts on
`RANKINGS_DAY` (the 1st) and summarizes the **previous** calendar month, so
"June Rankings" appears on July 1 with complete June data (no partial-month
leaderboard). `render` returns `None` on every other day and when nobody
completed a chore that month (no empty/noise post).

## Architecture

All in `cogs/chores.py` (completions already live there). No new tables — counts
and months are derived from `chore_completions.completed_at`. A new
`ScheduledJob(key="chore-rankings", channel="chores", render=render_rankings)`
is appended to `JOBS`.

### Layer 1 — pure functions (unit-tested)

- `previous_month(today) -> (year, month)` (and `_prev_year_month`) — January
  wraps to the prior December.
- `is_rankings_day(today, rankings_day) -> bool`.
- `rank_members(counts) -> [(rank, name, count)]` — drops zero-count members,
  sorts by count desc, **standard competition ranking** for ties (1, 2, 2, 4).
- `monthly_streak(month_keys, year, month) -> int` — consecutive months (ending
  at the given month) present in the member's set of 'YYYY-MM' completion months;
  0 if the ending month itself is absent.
- `format_rankings(month_label, ranked, streaks) -> str` — medals 🥇🥈🥉 for the
  top three then plain ranks, and an optional `🔥 **Streaks**` line.

### Layer 2 — DB access (unit-tested against the `conn` fixture)

- `completion_counts_for_month(conn, house_id, year, month)` — per-member counts
  filtered by `substr(completed_at, 1, 7) = 'YYYY-MM'`. Member rows are
  house-scoped, so the count is house-scoped without joining `chores`.
- `completion_months(conn, house_id) -> {member_id: {'YYYY-MM', ...}}` — feeds
  the streak computation.

### Layer 3 — render

`render_rankings` guards on `is_rankings_day`, resolves the previous month, ranks
that month's counts, computes streaks (≥ 2 months) for ranked members, and
formats. Wired purely as a scheduler job (no command).

## Testing (layer 1 + DB integration against the `conn` fixture)

- Pure: month wrap, rankings-day guard, competition-tie ranking, zero-drop,
  streak counting/gaps/year-wrap, and the formatted medals + streak line.
- Integration: completions are inserted with explicit `completed_at` timestamps
  so the month filter is exercised — a July completion does not count toward
  June; an empty summarized month yields `None`; a two-month run surfaces a
  streak. The off-day case returns `None`.

## Scope (YAGNI)

- Streaks are **per-member consecutive months with ≥ 1 completion**, ending at
  the summarized month — not per-chore period runs (cleaner, cadence-independent,
  and consistent with the monthly framing).
- Rankings are month-scoped; the all-time tally remains `/chore-history`.
- Posting day is the hardcoded `RANKINGS_DAY = 1` for now; per-house scheduling
  is the future Settings feature.

## Phase 2 status

Last Phase 2 item. With it (and overdue alerts dropped), the chores system is
complete: rotation, `/chores`/`/complete`/`/swap`/`/chore-history`, the daily
reminder, completion confirmations, and monthly rankings.
