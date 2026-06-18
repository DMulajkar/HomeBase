# Chore completion confirmations (auto-post) — design

Date: 2026-06-17
Status: approved
Phase: 2 — Chores system (`#chores`) — first auto-post item

## Purpose

When someone runs `/complete`, post a public confirmation to `#chores` naming
who finished the chore and their running contribution count — so the house sees
chores get knocked out in real time, the gentle visibility the chores system
exists to provide. Previously `/complete` only replied to the invoker.

## Decision: event-driven, not scheduler

Like the `/pay` payment confirmation, a completion confirmation must be
**timely** — it fires the instant `/complete` runs — so it does *not* fit the
`ScheduledJob` + `render(conn, house_id, today)` recipe (which the *daily chore
reminder* uses). It posts directly from the `/complete` command handler. The
message-building stays a pure function (layer 1) so it is unit-tested without
Discord. This is the same shape as the payment-confirmations slice; see
`2026-06-17-payment-confirmations-slice-design.md`.

## Architecture

Extends the existing `/complete` handler in `cogs/chores.py` (completions
already live there). No new tables.

### Layer 1 — pure functions (unit-tested)

- `_ordinal(n) -> str` — `1`→`1st`, `2`→`2nd`, `3`→`3rd`, teens→`th`.
- `format_completion_confirmation(member_name, chore_name, total_completions)
  -> str` — the public message. `total_completions` is the member's all-time
  chore count *including this one*; when `> 0` it appends "That's their Nth chore
  done." (a guard keeps it omittable if a count isn't known).

### Layer 2 — DB access (unit-tested against the `conn` fixture)

- `member_completion_count(conn, house_id, member_id) -> int` — all-time count
  of chores the member has completed, scoped to the house by joining
  `chore_completions` to `chores` (the completions table has no `house_id`).

### Layer 3 — Discord plumbing

- `/complete` handler, after `record_completion`: read
  `member_completion_count`, build the confirmation, then (reusing the shared
  `channels.resolve_house_channel(guild, "chores")` introduced for `/pay`):
  - `#chores` exists **and** it isn't where the command was run → ephemeral ack
    to the invoker + public confirmation posted to `#chores`;
  - `#chores` missing, or the command was already run in it → post the
    confirmation as the (public) interaction response in place.
  This avoids any double message regardless of where `/complete` is invoked. A
  `discord.Forbidden` on the channel send is swallowed (the completion is already
  recorded; the confirmation is best-effort), matching the scheduler and `/pay`.

## Testing (layer 1 + DB integration against the `conn` fixture)

- `_ordinal`: 1st/2nd/3rd/4th, the 11–13 teens exception, and 21st/22nd/23rd.
- `format_completion_confirmation`: includes member + chore wording, the 1st-chore
  case, and omits the count when `0`.
- Integration: record real completions and confirm `member_completion_count`
  increments, is scoped to the house (a same-named member in another house does
  not leak in), and feeds the confirmation wording.

## Scope (YAGNI)

- The count is **all-time** total contributions (what `/chore-history` tallies),
  not "this week" — no new time-windowed query.
- No new command; this enriches `/complete`.
- Streaks/rankings and overdue alerts are separate Phase 2 items, not in scope.
