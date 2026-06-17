# Directed expense (charge to one person) — design

Date: 2026-06-17
Status: approved
Phase: 1 — Finance system (`#rent-and-utilities`) — small enhancement to `/expense`

## Purpose

Let someone log an expense they paid that belongs **entirely to one other
person**, rather than being split across the whole house. "I fronted Bob's
concert ticket — put the full $45 on his tab." The amount lands wholly on that
member's debt to the payer; nobody else is involved.

This is interpretation #2 of "charge the expense to someone else": choosing *who
the expense covers*, not *who paid* (the payer is still the caller). Picking a
different payer is a separate, unbuilt option.

## Decision: reuse the split, don't add a code path

`record_expense(conn, house_id, description, amount_cents, paid_by, member_ids)`
already splits a total across `member_ids`. A directed expense is simply a split
whose member list is a **single** member: `split_amount(amount, [target])` is
`{target: amount}`, so the target owes the payer the full amount and the existing
balance machinery (`get_debts` → `compute_net_balances`) handles it unchanged. No
new pure or DB function is introduced — only the command grows an option.

## Architecture (layer 3 only)

`/expense` gains an optional `charge_to: discord.Member` parameter:

- omitted → unchanged behavior (equal split across all members, paid by caller);
- provided → guards (must be a house member; cannot be the caller, since owing
  yourself nets to zero), then `record_expense(..., paid_by=caller,
  member_ids=[charge_to])` and a confirmation naming the full amount owed.

No table, pure-function, or balance changes.

## Testing (layers 1 + 2 against the `conn` fixture)

- Pure: `split_amount(3000, [x]) == {x: 3000}` (the whole-amount property).
- Integration: a directed expense makes only the target owe the payer the full
  amount (uninvolved members stay at 0); a directed expense and a normal equal
  split accumulate correctly on the same pair.

The self-charge and non-member guards live in the command handler (layer 3), so
they are covered by inspection, consistent with the rest of the codebase (no
Discord-client tests).

## Scope (YAGNI)

- Single target only (the whole amount). Splitting across an arbitrary *subset*
  of members, or custom per-person shares, is not in scope.
- The payer remains the caller; a `payer:`/different-payer option is deliberately
  left out (separate feature).
