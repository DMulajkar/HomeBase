# Groceries slice 1 (shared list) — design

Date: 2026-06-17
Status: approved
Phase: 3 — Groceries system (`#groceries`) — first slice

## Purpose

The shared grocery list: housemates add what the house needs, see it grouped by
category, mark things bought, and remove things no longer needed. This is the
foundation the later Phase 3 items (low-stock warnings, shopping-run summaries,
spending analytics, meal planning) build on. Per the one-feature-per-pass rule,
this slice is **the list and its commands only** — no auto-posts.

## Scope

In:
- Categories: Food / Household Supplies / Cleaning Supplies (fixed set).
- `/grocery-add`, `/groceries` (view), `/grocery-bought`, `/grocery-remove`.

Out (later slices): inventory/quantity tracking, low-stock auto-posts, shopping
trip summaries/confirmations, spending analytics, `/meal-plan`.

## Command naming

Flat hyphenated names (`/grocery-add`, `/grocery-bought`, …) to match the
existing `/chore-add`, `/bill-add`, `/bill-post` convention and CLAUDE.md's
"one command per action with a single clear name". This supersedes the original
roadmap's `/grocery add` subcommand-group spelling.

## Architecture (own cog, own table)

`cogs/groceries.py`, wired in `bot.py` setup_hook. Owns one table, created from
the cog `__init__` via `init_tables` (per the cog-table-ownership rule). Follows
the three-layer split.

### Layer 1 — pure functions (unit-tested)

- `group_by_category(items)` — `(category, name)` pairs → `{category: [names]}`,
  ordered by the fixed `CATEGORIES` then name; empty in, empty out.
- `format_grocery_list(grouped)` — per-category checklist text, with an
  empty-state line pointing at `/grocery-add`.

### Layer 2 — DB access (conn first; unit-tested against the `conn` fixture)

`grocery_items(item_id, house_id, name, category, added_by_member_id, created_at,
bought_at, bought_by_member_id)`.

**Key choice — partial unique index.** `CREATE UNIQUE INDEX ... ON
grocery_items(house_id, name) WHERE bought_at IS NULL`. Only one *active* row per
name per house, but bought rows are exempt — so buying an item turns it into
history and the same name can be needed again later without colliding. This is
why "bought" sets a timestamp rather than deleting, while "remove" deletes
outright (it was never bought).

- `add_item` — insert; `IntegrityError` from the index → `ValueError("already on
  the grocery list")`.
- `list_needed` — active rows ordered by `category, name`.
- `mark_bought` — set `bought_at`/`bought_by` on the active row; returns whether
  one matched (`rowcount > 0`).
- `remove_item` — delete the active row; returns whether one matched.

### Layer 3 — Discord plumbing

Standard guard (`_get_house_and_member`: DM / house-exists / membership). Category
is a `Literal[...]` so Discord renders a choice picker and invalid values can't
arrive. `bought`/`remove` report a friendly ephemeral "no item named …" when the
name doesn't match an active item.

## Testing

- Pure: category/name ordering, empty grouping, empty-state and grouped
  rendering.
- DB (`conn` fixture): add + ordered list; duplicate-active rejected; bought
  drops from `list_needed` and the name can be re-added (partial-index behavior);
  bought/remove return False when nothing matches; items are house-scoped.

## Future hooks

`bought_at`/`bought_by_member_id` are recorded now (not just deletion) so the
later analytics and shopping-summary slices have purchase history to read, and a
purchase-confirmation auto-post can reuse the same data — no schema change needed
to add those.
