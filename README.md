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
- **Meal voting** — propose meals, vote (and change your vote), see standings,
  and close the poll to announce the winner.
- **Subscriptions** — store shared subscription credentials (Netflix, Spotify,
  etc.) with Fernet-encrypted passwords. Only house members can retrieve them,
  and passwords are always shown privately (ephemeral).
- **House wiki** — a shared reference for anything the house needs to remember:
  Wi-Fi password, landlord contact, lease info, parking rules, etc.
- **Birthdays** — store each roommate's birthday (month and day only); the bot
  auto-posts a reminder to `#events` on the day. Prompted automatically when
  someone runs `/join-house`.
- **Anonymous suggestions** — submit feedback or surface tension without
  attribution; the bot posts it to `#suggestions` with no name attached.
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

To enable encrypted subscription password storage, generate a key and add it:

```powershell
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the output to `.env` as `SUBSCRIPTION_KEY=<output>`. Without it the
`/sub-add` and `/sub-password` commands are disabled (the rest of the bot works
fine).

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

#### `/leaderboard`
Shows this month's house-wide contribution rankings, combining chores completed
(1 pt each) and grocery runs (2 pts each). The same leaderboard is also
auto-posted to `#chores` on the 1st of each month, summarizing the month that
just ended.
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

### Meal voting

One poll at a time per house. Propose meals, vote, and close when ready.

#### `/meal-propose`
Propose a meal for the house to vote on. If no poll is open, this starts one.
- `name` — the meal, e.g. `Tacos`.

#### `/meal-vote`
Vote for a meal in the current poll. You can change your vote at any time before the poll closes.
- `name` — the meal you want.

#### `/meal-results`
Show the current standings without closing the poll.
- No arguments.

### Subscriptions

Store shared account credentials for house subscriptions (Netflix, Spotify,
etc.) so everyone in the house can access them without asking in the group chat.

#### How password storage works

When you save a subscription, the bot **never stores your password in plain
text**. Here's what actually happens:

1. **You run `/sub-add`** with the password. Discord sends the command to the
   bot over an encrypted HTTPS connection — it's not plaintext in transit.

2. **The bot encrypts the password** using AES-128 (via the Fernet standard)
   before writing anything to the database. The result is a scrambled token that
   looks like `gAAAAABn4xK2...` — meaningless without the key.

3. **The database only ever holds the token**, not the password. If someone
   grabbed the database file off the server, they would see ciphertext, not your
   Netflix password.

4. **The encryption key** (`SUBSCRIPTION_KEY` in `.env`) is what makes
   decryption possible. It never touches the database and is gitignored, so it
   is never accidentally committed to source control. If the key is lost,
   passwords cannot be recovered — keep a backup somewhere safe.

5. **When you run `/sub-password`**, the bot decrypts the token using the key
   and sends the result back **only to you** (Discord ephemeral message — other
   people in the channel cannot see it, and it disappears when you dismiss it).

6. **`/subs` never shows passwords** — it only lists names and emails, so it is
   safe to run in any channel.

#### What this protects against

| Scenario | Protected? |
|---|---|
| Someone reads the database file off disk | ✅ Only scrambled tokens, no plaintext |
| Passwords visible in Discord chat history | ✅ Always sent privately (ephemeral) |
| Bot source code leaks online | ✅ Key is in `.env`, not in the code |
| Someone has both the DB file **and** the key | ❌ They can decrypt — keep your `.env` secure |

The last row is the honest limit: this is **encryption at rest**, not a
zero-knowledge vault. The bot needs the key to decrypt, so whoever controls the
server and the `.env` file has access. For a home server shared with your
housemates, this is the right level of protection. If you ever need to rotate
the key, you will need to re-save all passwords with the new key.

Requires `SUBSCRIPTION_KEY` to be set in `.env` (see Setup above). Without it,
`/sub-add` and `/sub-password` are disabled but the rest of the bot works
normally.

#### `/sub-add`
Save a subscription. The confirmation is private (ephemeral) so your password
is never visible in chat.
- `name` — service name, e.g. `Netflix`.
- `email` — account email.
- `password` — account password (stored encrypted).

#### `/subs`
List all saved subscriptions showing names and emails. **Passwords are never
shown here.**
- No arguments.

#### `/sub-password`
Retrieve the password for a subscription. **Only you see this response.**
- `name` — which subscription.

#### `/sub-update`
Update the email and/or password for an existing subscription.
- `name` — which subscription.
- `email` *(optional)* — new email.
- `password` *(optional)* — new password.

#### `/sub-remove`
Delete a subscription.
- `name` — which subscription to remove.

### House wiki

A shared reference for anything the house needs to remember. Entries are
simple key/value pairs — the key is a short label (case-insensitive), the value
is whatever text you want to store. Good for:

- Wi-Fi password
- Landlord name and contact number
- Lease end date
- Utility account numbers
- Building entry code
- Parking rules

Entries are grouped into five categories: **Access & Security**, **Utilities & Services**, **Building & Maintenance**, **House Rules**, and **Lease & Legal** (plus **General** as a catch-all). Keys are case-insensitive — `WiFi Password` and `wifi password` are the same entry.

#### `/wiki-setup`
Pre-populate the wiki with 27 common entries (building entry code, trash pickup day, quiet hours, lease end date, etc.) as `(not set)` placeholders. Safe to run at any time — entries you've already filled in are never overwritten.
- No arguments.

#### `/wiki-set`
Add a new entry or overwrite an existing one.
- `key` — short label, e.g. `wifi password` or `landlord contact`.
- `value` — the information to store.
- `category` *(optional)* — which section it belongs in (default: General).

#### `/wiki`
Look up a single entry by key.
- `key` — what to look up.

#### `/wiki-list`
Show every entry grouped by category.
- No arguments.

#### `/wiki-remove`
Delete an entry.
- `key` — which entry to remove.

### Birthdays

#### `/birthday-set`
Set or update your birthday. Opens a short form where you enter the date — no
year needed, just month and day. Accepted formats: `March 15`, `3/15`, `03-15`.
- No arguments (opens a modal).

#### `/birthdays`
Show all house members who have a birthday on record, sorted by month and day.
- No arguments.

The bot also auto-posts a birthday message to `#events` on the morning of
someone's birthday. Members who haven't added their birthday won't appear.

When you run `/join-house`, the bot will ask if you want to add your birthday
right then. You can always add or update it later with `/birthday-set`.

### Anonymous suggestions

A one-way channel for surfacing feedback without putting anyone on the spot.
Suggestions are numbered (`#1`, `#2`, …) so the house can refer to them, but
the author's name is never shown.

#### `/suggestion`
Post an anonymous suggestion to `#suggestions`. Only you see the confirmation;
everyone else sees only the numbered suggestion text.
- `text` — the suggestion.

Requires the `#suggestions` channel to exist (create it with `/setup-channels`).

#### `/meal-close`
Close the poll and announce the winner to `#groceries`. Ties go to the meal proposed first. Requires at least one vote.
- No arguments.

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
- **Monthly house leaderboard** → `#chores`: on the 1st of each month, a
  cross-system ranking combining chores (1 pt) and grocery runs (2 pts).
- **Fixed bills** → `#rent-and-utilities`: each fixed bill posts itself (creates
  the split expense) on its due day. Variable bills are never auto-posted —
  post them with `/bill-post`.
- **Due-date reminders** → `#rent-and-utilities`: a daily heads-up listing bills
  coming due within the next 3 days (and not yet posted this month), so you can
  move money ahead of time. Variable bills include a `/bill-post` nudge.
- **Monthly financial summary** → `#rent-and-utilities`: on the 1st of each
  month, a report of outstanding balances (who owes whom).
- **Monthly grocery spending report** → `#groceries`: on the 1st of each month,
  a summary of last month's total grocery spend and a per-member breakdown of
  who did shopping runs.
- **Birthday reminders** → `#events`: on the morning of a member's birthday, a
  message calling out their name. Only members who have added a birthday appear.

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
  groceries.py     # /grocery-add, /groceries, /grocery-bought, /grocery-remove, /grocery-done
  leaderboard.py   # /leaderboard; monthly cross-system rankings auto-post
  meals.py         # /propose, /meal-vote, /meal-results, /meal-close
  birthdays.py     # /birthday-set, /birthdays; birthday prompt on /join-house
  wiki.py          # /wiki-set, /wiki, /wiki-list, /wiki-remove
  suggestions.py   # /suggestion (anonymous)
  scheduler.py     # the daily auto-post loop
docs/superpowers/specs/   # design docs for each feature
tests/             # unit tests (pure + DB layers)
```

See `CLAUDE.md` for architecture details and the feature roadmap.
