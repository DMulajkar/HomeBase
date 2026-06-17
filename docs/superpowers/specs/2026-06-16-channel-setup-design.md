# HomeBase Channel Setup — Design

**Date:** 2026-06-16
**Status:** Approved (pending written-spec review)

## Goal

Give the bot the ability to create a curated set of Discord channels for a house.
Channels are **optional** — an admin picks which to create from an interactive
checklist. The picker is offered during `/house-setup` and is also available
anytime via a standalone `/setup-channels` command.

## Channels

All created channels live under a single category named **HomeBase**.

| Channel        | Topic (channel description)                                  | Special |
|----------------|-------------------------------------------------------------|---------|
| `chores`       | Chore assignments, rotations, and reminders.                | —       |
| `groceries`    | Shared grocery lists and who's shopping.                     | —       |
| `food`         | Meals, recipes, leftovers, and dinner plans.                | —       |
| `events`       | House events, hangouts, and shared calendar.                | —       |
| `memories`     | Photos and moments from the house.                          | —       |
| `bot-commands` | Run HomeBase bot commands here.                             | —       |
| `welcome`      | House rules, bot setup, and important commands.             | Receives a posted welcome embed |

Discord normalizes channel names (lowercase, spaces → hyphens); all names above
are already in that form.

## Welcome channel content

When `welcome` is selected, the bot posts a welcome embed built by a pure
function `build_welcome_message(house_name)`. The embed has three sections:

1. **House Rules** — a placeholder ("✏️ *Edit this message to add your house
   rules.*") roommates edit later directly in Discord. (Per decision: default
   template, editable later — the bot does not prompt for rules at setup time.)
2. **Bot Setup** — instructions to run `/join-house` to join the house.
3. **Important Commands** — `/expense`, `/pay`, `/balances`, `/join-house`.

## Architecture

New cog module `cogs/channels.py`, following the existing cog-per-feature
pattern. **No new database table** — idempotency and lookups are done by channel
name against the live guild (decision: detect by name, YAGNI on persistence).

### Layer 1 — pure functions (unit-tested)

- `CHANNEL_CATALOG`: ordered list of channel specs, each with `name`, `topic`,
  and a `welcome: bool` flag. Exactly one entry has `welcome=True`.
- `build_welcome_message(house_name) -> discord.Embed`: constructs the welcome
  embed (House Rules placeholder + Bot Setup + Important Commands).

> Note: `discord.Embed` is a plain data object, constructable without a live
> client, so `build_welcome_message` is unit-testable.

### Layer 3 — Discord plumbing (not unit-tested)

Consistent with the existing rule that no tests spin up a Discord client.

- `ChannelSetupView(discord.ui.View)`: a `discord.ui.Select` (multi-select)
  listing the catalog channels (all pre-selected by default) plus a **Create**
  button. On confirm, calls `create_selected_channels`.
- `create_selected_channels(guild, selected_names) -> summary`: ensures the
  `HomeBase` category exists (create if missing), creates each selected channel
  under it **skipping any that already exist by name**, posts the welcome embed
  into `welcome` only when that channel was newly created (so re-runs never
  duplicate the welcome post), and returns a summary of which channels were
  created vs. skipped.

## Commands & wiring

- Register `cogs.channels` in `bot.py`'s `setup_hook`.
- `/setup-channels` (in `cogs/channels.py`): server-only, requires an existing
  house (reuses core's house-exists guard style). Sends the `ChannelSetupView`.
- `/house-setup` (in `cogs/core.py`): after creating the house, sends the same
  `ChannelSetupView` so the admin can pick channels immediately. Imports the
  view/helper from `cogs.channels`.

## Error handling

- Requires the bot to have the **Manage Channels** permission. On
  `discord.Forbidden`, reply ephemerally instructing the admin to grant the
  permission and re-run `/setup-channels`.
- Server-only: reject use in DMs (matches existing commands).
- Idempotent: re-running reports newly created vs. already-present channels;
  never duplicates.

## Testing

Unit tests (layer 1 only, matching the current suite's no-Discord-client rule):

- `CHANNEL_CATALOG`: contains exactly the 7 expected names; exactly one
  `welcome=True` entry; names are valid Discord channel name form.
- `build_welcome_message`: embed contains the rules placeholder, the
  `/join-house` setup instruction, and each important command
  (`/expense`, `/pay`, `/balances`, `/join-house`).

## Out of scope (YAGNI)

- Persisting channel IDs in the database.
- Prompting for / storing custom house-rules text at setup time.
- Per-channel permission overwrites, archiving, or deletion commands.
