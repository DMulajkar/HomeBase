# Payment confirmations (auto-post) — design

Date: 2026-06-17
Status: approved
Phase: 1 — Finance system (`#rent-and-utilities`) — final item

## Purpose

When someone runs `/pay`, post a public confirmation to `#rent-and-utilities`
showing the payment **and the resulting balance** between the two people — so
the whole house sees money move and learns whether the pair is now settled,
without anyone running `/balances`.

## Decision: event-driven, not scheduler

Every other finance auto-post is a daily scheduler tick that renders from the
DB. A payment confirmation must be **timely** — it fires the instant `/pay`
runs — so it does *not* fit the `ScheduledJob` + `render(conn, house_id, today)`
recipe. It posts directly from the `/pay` command handler. The message-building
stays a pure function (layer 1) so it is unit-tested without Discord.

## Architecture

Extends the existing `/pay` handler in `cogs/expenses.py` (settlements already
live there). No new tables.

### Layer 1 — pure functions (unit-tested)

- `net_between(net, a, b) -> int` — given the `compute_net_balances` map, the
  cents `a` owes `b`: positive if `a` owes `b`, negative if `b` owes `a`, `0` if
  settled between them.
- `format_payment_confirmation(from_name, to_name, amount_cents, net_after_cents)
  -> str` — the public message. `net_after_cents` is what `from_name` still owes
  `to_name` after the payment (negative ⇒ `to_name` now owes `from_name`).
  Three cases: still owes / overpaid (balance flipped) / all settled up.

### Layer 3 — Discord plumbing

- New shared helper `channels.resolve_house_channel(guild, name) -> TextChannel |
  None` — finds a channel by name **inside the HomeBase category** (the lookup
  the scheduler did inline). The scheduler's `_run_job` is refactored to use it,
  so channel resolution lives in one place.
- `/pay` handler, after `record_settlement`: recompute net balances, take
  `net_between(net, payer, payee)`, build the confirmation, then:
  - finance channel exists **and** it isn't where the command was run → ephemeral
    ack to the invoker + public confirmation posted to `#rent-and-utilities`;
  - finance channel missing, or the command was already run in it → post the
    confirmation as the (public) interaction response in place.
  This avoids any double message regardless of where `/pay` is invoked. A
  `discord.Forbidden` on the channel send is swallowed (the settlement is
  already recorded; the confirmation is best-effort), matching the scheduler.

## Testing (layer 1 + DB integration against the `conn` fixture)

- `net_between`: a owes b, the reverse sign, and settled (empty map) → 0.
- `format_payment_confirmation`: still-owes, settled, and balance-flipped wording.
- Integration: record an expense + a partial settlement, then confirm
  `net_between` over real `compute_net_balances` yields the remaining debt that
  the confirmation reports.

## Scope (YAGNI)

- Confirms the **pairwise** balance between the two people, not the whole house.
- No new command; this enriches `/pay`.

## Phase 1 status

This is the last Phase 1 item. With it, the finance system is complete:
expenses, bills, due-date reminders, monthly summary, and payment confirmations.
