# HomeBase

A Discord bot for running a shared house with roommates — expenses, chores, and
recurring bills — built one feature at a time. It tracks who owes whom, rotates
chores fairly, and posts daily reminders so the house keeps running without
nagging.

## What it does

- **Expenses** — log shared costs, split them equally, and see who owes whom.
- **Chores** — recurring chores that rotate automatically through housemates,
  with completion tracking and a daily reminder.
- **Bills** — recurring rent/utilities/subscriptions that post into the expense
  ledger; fixed bills post themselves on their due day.
- **Groceries** — a shared shopping list grouped into Food / Household / Cleaning,
  with add, bought, and remove.
- **Channels** — an interactive picker that creates the house's Discord
  channels (`#chores`, `#rent-and-utilities`, `#groceries`, and more).

Everything runs on slash commands.

## Setup

Requires **Python 3.12**. On this machine use the `py` launcher (`python` /
`python3` are broken Windows Store stubs).

```powershell
py -m pip install -r requirements.txt
```

Create a `.env` file (gitignored) in the project root:

```
DISCORD_TOKEN=your-bot-token-here
GUILD_ID=your-server-id      # optional: instant slash-command sync for one server
```

Leave `GUILD_ID` blank for global command sync (can take ~an hour to appear in
Discord). With it set, commands sync instantly to that one server — use it
during development.

The bot needs these Discord permissions in your server: **View Channels**,
**Send Messages**, **Embed Links**, and **Manage Channels** (for channel
creation).

## Running

```powershell
py bot.py            # run the bot (reads .env)
py -m pytest         # run the test suite
py -m pytest -v      # verbose
```

There is no build step.

## First-time house setup

Run these once, in order:

1. **`/house-setup`** — registers this Discord server as a "house." It then
   shows a picker so you can create the house channels. *(Run once per server.)*
2. **`/join-house`** — **every** roommate runs this. Only joined members are
   included in expense splits, bill splits, and the chore rotation. The order
   people join is also the chore rotation order.

After that, use the commands below.

---

## Command reference

### House & members

#### `/house-setup`
Registers the current server as a house and opens the channel picker. Run once.
- No arguments.

#### `/join-house`
Adds you to the house. Required before you appear in splits or the chore
rotation.
- No arguments.

#### `/house-members`
Lists everyone in the house, in join order (which is also the chore rotation
order).
- No arguments.

#### `/setup-channels`
Re-opens the channel picker to create any house channels you didn't make during
setup (or that were deleted). Idempotent — channels that already exist are
skipped, so it's safe to re-run.
- No arguments.

### Expenses

#### `/expense`
Logs a shared expense paid by you and splits it equally across all house
members. The remainder (if it doesn't divide evenly) is distributed one cent at
a time, so shares always sum exactly to the total.
- `description` — what the expense was for, e.g. `Pizza night`.
- `amount` — dollars, e.g. `42.50`. Must be positive.
- `charge_to` *(optional)* — a single member to charge the **whole** amount to,
  instead of splitting it. Use this when you fronted money for one person: it
  goes entirely on their debt to you, and nobody else is involved. You can't
  charge an expense to yourself.

Examples:
- `/expense description:Groceries amount:60` — if there are 3 members, each owes
  you $20.
- `/expense description:Bob's ticket amount:45 charge_to:@Bob` — Bob alone owes
  you the full $45.

#### `/pay`
Records that you paid another member back toward what you owe them. This reduces
your balance with that person, and posts a confirmation to `#rent-and-utilities`
showing the payment and your updated balance with them (settled up, still owing,
or — if you overpaid — them now owing you).
- `to` — the member you paid.
- `amount` *(optional)* — dollars you paid. Must be positive. **Leave it blank to
  settle your whole balance with them** — the bot pays off exactly what you
  currently owe that person. If you don't owe them anything, it does nothing.

Examples:
- `/pay to:@Alice amount:20` — pay Alice $20 toward what you owe her.
- `/pay to:@Alice` — settle up with Alice completely.

#### `/balances`
Shows who owes whom across the whole house (net of all expenses and payments).
Says "Everyone is settled up!" when balances are clear.
- No arguments.

### Chores

Chores rotate automatically by date — each period the chore moves to the next
member round-robin, so it's fair over time with no manual reassigning.

#### `/chore-add`
Adds a recurring chore to the rotation, starting today.
- `name` — the chore, e.g. `Dishes`.
- `cadence` — `daily`, `weekly`, or `monthly` (how often it rotates).

Example: `/chore-add name:Trash cadence:weekly`.

#### `/chores`
Shows every chore with its current assignee, whether it's done or pending, and
its due date.
- No arguments.

#### `/complete`
Marks a chore done for the current period, and posts a public confirmation to
`#chores` showing who finished it and their running contribution count. Anyone
can complete any chore; it's credited to whoever runs the command (this feeds
`/chore-history`). Completing the same chore twice in one period is rejected.
- `name` — the chore you finished.

#### `/swap`
Hands off **this period only** to another member; the normal rotation resumes
next period. `/chores` will show the chore as `(swapped)`.
- `name` — the chore to reassign.
- `member` — who will do it this period.

#### `/chore-history`
Shows a tally of how many chores each member has completed.
- No arguments.

### Bills (rent & utilities)

A bill is a recurring template. Posting a bill for a month creates a normal
expense (split equally, fronted by the bill's payer), so it flows into
`/balances` and `/pay` like any other expense.

There are two kinds:
- **fixed** — the amount is the same each month (rent, internet, subscriptions).
  These **auto-post on their due day**.
- **variable** — the amount changes (utilities). You post these manually with
  the real amount when the bill arrives.

#### `/bill-add`
Defines a recurring bill.
- `name` — e.g. `Rent` or `Electric`.
- `kind` — `fixed` or `variable`.
- `due_day` — day of the month it's due, `1`–`31` (clamped to the month's
  length, so `31` becomes the last day of shorter months).
- `payer` — the member who fronts the money (the person others owe).
- `amount` — dollars. **Required for fixed** bills; omit for variable.

Examples:
- `/bill-add name:Rent kind:fixed due_day:1 payer:@Alice amount:1500`
- `/bill-add name:Electric kind:variable due_day:15 payer:@Bob`

#### `/bills`
Lists all bills with their kind, amount (or "varies"), due day, payer, and this
month's status (✅ posted / ⏳ pending).
- No arguments.

#### `/bill-post`
Posts a bill for the current month — creates the split expense.
- `name` — the bill to post.
- `amount` — dollars. **Required for variable** bills; for fixed bills it's an
  optional override (defaults to the saved amount).

Refuses if that bill is already posted for the current month.

Examples:
- `/bill-post name:Electric amount:120.50` — log this month's utilities.
- `/bill-post name:Rent` — post rent early using its saved amount.

#### `/bill-remove`
Deletes a recurring bill definition. Expenses it already created stay (they're
real debt).
- `name` — the bill to remove.

### Groceries

A shared grocery list grouped into three categories: **Food**, **Household
Supplies**, and **Cleaning Supplies**. Items stay on the list until someone buys
or removes them; a bought item drops off but is kept as history, so you can add
it again next time you run low.

#### `/grocery-add`
Adds an item to the list under a category.
- `name` — what to buy, e.g. `Milk`.
- `category` — `Food`, `Household Supplies`, or `Cleaning Supplies`.

The same item can't be on the active list twice.

#### `/groceries`
Shows the current list, grouped by category.
- No arguments.

#### `/grocery-bought`
Marks an item as bought, removing it from the active list (and crediting you).
- `name` — the item you bought.

#### `/grocery-remove`
Removes an item that's no longer needed (without marking it bought).
- `name` — the item to remove.

#### `/grocery-done`
Ends a shopping run — marks **everything** on the list as bought, clears it for
next time, and posts a trip summary to `#groceries`.
- `amount` *(optional)* — total spent in dollars. If provided, it's recorded as a
  shared expense and split equally among all house members, flowing into `/balances`
  and `/pay` like any other expense.

The workflow: add items throughout the week with `/grocery-add`, then run
`/grocery-done` (with the receipt total) when you get home.

---

## Automatic posts

The scheduler checks every 15 minutes and posts once per day, at **09:00 UTC**:

- **Daily chore reminder** → `#chores`: the day's chore assignments.
- **Monthly chore rankings** → `#chores`: on the 1st of each month, a 🏆
  leaderboard of who completed the most chores in the month that just ended,
  with any active per-member streaks.
- **Fixed bills** → `#rent-and-utilities`: each fixed bill posts itself (creates
  the split expense) on its due day. Variable bills are never auto-posted —
  post them with `/bill-post`.
- **Due-date reminders** → `#rent-and-utilities`: a daily heads-up listing bills
  coming due within the next 3 days (and not yet posted this month), so you can
  move money ahead of time. Variable bills include a `/bill-post` nudge.
- **Monthly financial summary** → `#rent-and-utilities`: on the 1st of each
  month, a report of outstanding balances (who owes whom).

These require the matching channel to exist under the **HomeBase** category
(created by `/house-setup` or `/setup-channels`).

Two posts are **event-driven** rather than scheduled, firing the moment the
command runs:

- A **payment confirmation** is posted to `#rent-and-utilities` when someone
  runs `/pay` (see the `/pay` command above).
- A **completion confirmation** is posted to `#chores` when someone runs
  `/complete` (see the `/complete` command above).

## Project layout

```
bot.py             # entry point; opens the DB and loads cogs
database.py        # cross-cutting houses & members tables
scheduler.py       # pure schedule logic + schedule_state table
conftest.py        # pytest fixture: fresh in-memory DB per test
cogs/
  core.py          # /house-setup, /join-house, /house-members
  channels.py      # channel picker + /setup-channels
  expenses.py      # /expense, /pay, /balances
  chores.py        # /chore-add, /chores, /complete, /swap, /chore-history
  finance.py       # /bill-add, /bills, /bill-post, /bill-remove
  groceries.py     # /grocery-add, /groceries, /grocery-bought, /grocery-remove
  scheduler.py     # the daily auto-post loop
docs/superpowers/specs/   # design docs for each feature
tests/             # unit tests (pure + DB layers)
```

See `CLAUDE.md` for architecture details and the feature roadmap.
