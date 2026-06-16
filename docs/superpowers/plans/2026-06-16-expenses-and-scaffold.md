# Project Scaffold + Expenses Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the Discord house-bot project (entry point, cogs structure, core houses/members schema) and build the first complete feature — equal-split expense tracking with settle-up and net pairwise balance queries.

**Architecture:** A `discord.py` bot (`bot.py`) using slash commands (`app_commands`), backed by a single SQLite connection stored on the bot instance (`bot.db`). `database.py` owns the connection setup and the two core tables (`houses`, `members`) every feature depends on. Each feature lives in its own cog under `cogs/`; `cogs/core.py` handles house/member registration (infrastructure every feature needs, not a feature itself), and `cogs/expenses.py` owns the expense-tracking feature end-to-end, including its own tables (`expenses`, `expense_splits`, `settlements`).

**Tech Stack:** Python 3.11+, discord.py 2.x (`app_commands`), SQLite (`sqlite3` stdlib), `python-dotenv`, `pytest`.

Spec: `docs/superpowers/specs/2026-06-16-expenses-and-scaffold-design.md`

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `cogs/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
discord.py>=2.3.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `.env.example`**

```
DISCORD_TOKEN=your-bot-token-here
```

- [ ] **Step 3: Create empty `cogs/__init__.py`**

```python
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .env.example cogs/__init__.py
git commit -m "chore: scaffold project files (requirements, env example, cogs package)"
```

---

### Task 2: Core database module (`database.py`)

**Files:**
- Create: `database.py`
- Create: `conftest.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

Create `conftest.py` at the project root (this also makes pytest add the project root to `sys.path`, so `import database` works from `tests/`):

```python
import sqlite3

import pytest

import database


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    database.init_db(connection)
    yield connection
    connection.close()
```

Create `tests/test_database.py`:

```python
import pytest

import database


def test_create_house_and_get_house(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    house = database.get_house(conn, "guild-1")
    assert house["house_id"] == house_id
    assert house["name"] == "The Treehouse"


def test_get_house_returns_none_when_missing(conn):
    assert database.get_house(conn, "no-such-guild") is None


def test_create_house_duplicate_raises(conn):
    database.create_house(conn, "guild-1", "The Treehouse")
    with pytest.raises(ValueError):
        database.create_house(conn, "guild-1", "Duplicate")


def test_add_member_and_get_member(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    member_id = database.add_member(conn, house_id, "user-1", "Alice")
    member = database.get_member(conn, house_id, "user-1")
    assert member["member_id"] == member_id
    assert member["display_name"] == "Alice"


def test_get_member_returns_none_when_missing(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    assert database.get_member(conn, house_id, "no-such-user") is None


def test_add_member_duplicate_raises(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    database.add_member(conn, house_id, "user-1", "Alice")
    with pytest.raises(ValueError):
        database.add_member(conn, house_id, "user-1", "Alice Again")


def test_list_members_ordered_by_member_id(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    database.add_member(conn, house_id, "user-2", "Bob")
    database.add_member(conn, house_id, "user-1", "Alice")
    members = database.list_members(conn, house_id)
    assert [m["discord_user_id"] for m in members] == ["user-2", "user-1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_database.py -v`
Expected: FAIL (or ERROR) with `ModuleNotFoundError: No module named 'database'`

- [ ] **Step 3: Implement `database.py`**

```python
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS houses (
            house_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL UNIQUE,
            name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            discord_user_id TEXT NOT NULL,
            display_name TEXT,
            joined_at TEXT NOT NULL,
            UNIQUE(house_id, discord_user_id)
        )
        """
    )
    conn.commit()


def create_house(conn: sqlite3.Connection, guild_id: str, name: Optional[str]) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO houses (guild_id, name, created_at) VALUES (?, ?, ?)",
            (guild_id, name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A house already exists for guild {guild_id}")


def get_house(conn: sqlite3.Connection, guild_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM houses WHERE guild_id = ?", (guild_id,)).fetchone()


def add_member(conn: sqlite3.Connection, house_id: int, discord_user_id: str, display_name: Optional[str]) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO members (house_id, discord_user_id, display_name, joined_at) VALUES (?, ?, ?, ?)",
            (house_id, discord_user_id, display_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"Member {discord_user_id} already exists in house {house_id}")


def get_member(conn: sqlite3.Connection, house_id: int, discord_user_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM members WHERE house_id = ? AND discord_user_id = ?",
        (house_id, discord_user_id),
    ).fetchone()


def list_members(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM members WHERE house_id = ? ORDER BY member_id", (house_id,)
    ).fetchall()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add database.py conftest.py tests/test_database.py
git commit -m "feat: add database.py with houses/members core schema"
```

---

### Task 3: Expense splitting logic (`split_amount`)

**Files:**
- Create: `cogs/expenses.py`
- Test: `tests/test_expenses_split.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expenses_split.py`:

```python
from cogs import expenses


def test_split_amount_even():
    shares = expenses.split_amount(300, [1, 2, 3])
    assert shares == {1: 100, 2: 100, 3: 100}


def test_split_amount_with_remainder():
    shares = expenses.split_amount(100, [1, 2, 3])
    assert shares == {1: 34, 2: 33, 3: 33}
    assert sum(shares.values()) == 100


def test_split_amount_single_member():
    shares = expenses.split_amount(500, [1])
    assert shares == {1: 500}


def test_split_amount_remainder_distributed_in_order():
    shares = expenses.split_amount(101, [10, 20, 30])
    assert shares == {10: 34, 20: 34, 30: 33}
    assert sum(shares.values()) == 101
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_expenses_split.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cogs.expenses'`

- [ ] **Step 3: Implement `split_amount` in `cogs/expenses.py`**

```python
def split_amount(amount_cents: int, member_ids: list[int]) -> dict[int, int]:
    n = len(member_ids)
    base = amount_cents // n
    remainder = amount_cents % n
    shares = {}
    for i, member_id in enumerate(member_ids):
        shares[member_id] = base + (1 if i < remainder else 0)
    return shares
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_expenses_split.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add cogs/expenses.py tests/test_expenses_split.py
git commit -m "feat: add equal-split calculation for expenses"
```

---

### Task 4: Net pairwise balance computation (`compute_net_balances`)

**Files:**
- Modify: `cogs/expenses.py`
- Test: `tests/test_expenses_balances.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expenses_balances.py`:

```python
from cogs import expenses


def test_compute_net_balances_simple_debt():
    debts = [(2, 1, 3000)]  # member 2 owes member 1 $30.00
    net = expenses.compute_net_balances(debts, [])
    assert net == {(2, 1): 3000}


def test_compute_net_balances_settled_pair_omitted():
    debts = [(2, 1, 3000)]
    payments = [(2, 1, 3000)]
    net = expenses.compute_net_balances(debts, payments)
    assert net == {}


def test_compute_net_balances_overpayment_flips_direction():
    debts = [(2, 1, 1000)]
    payments = [(2, 1, 1500)]
    net = expenses.compute_net_balances(debts, payments)
    assert net == {(1, 2): 500}


def test_compute_net_balances_self_pair_ignored():
    debts = [(1, 1, 1000)]
    net = expenses.compute_net_balances(debts, [])
    assert net == {}


def test_compute_net_balances_multiple_expenses_net_correctly():
    debts = [(2, 1, 3000), (1, 2, 1000)]
    net = expenses.compute_net_balances(debts, [])
    assert net == {(2, 1): 2000}


def test_compute_net_balances_no_debts_or_payments_is_empty():
    assert expenses.compute_net_balances([], []) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_expenses_balances.py -v`
Expected: FAIL with `AttributeError: module 'cogs.expenses' has no attribute 'compute_net_balances'`

- [ ] **Step 3: Implement `compute_net_balances` in `cogs/expenses.py`**

Add this import at the top of `cogs/expenses.py`:

```python
from collections import defaultdict
```

Add the function:

```python
def compute_net_balances(
    debts: list[tuple[int, int, int]], payments: list[tuple[int, int, int]]
) -> dict[tuple[int, int], int]:
    net: dict[tuple[int, int], int] = defaultdict(int)
    for ower, payer, cents in debts:
        if ower == payer:
            continue
        net[(ower, payer)] += cents
        net[(payer, ower)] -= cents
    for frm, to, cents in payments:
        net[(frm, to)] -= cents
        net[(to, frm)] += cents

    result: dict[tuple[int, int], int] = {}
    seen: set[tuple[int, int]] = set()
    for (a, b), amount in net.items():
        if (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        if amount > 0:
            result[(a, b)] = amount
        elif amount < 0:
            result[(b, a)] = -amount
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_expenses_balances.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add cogs/expenses.py tests/test_expenses_balances.py
git commit -m "feat: add net pairwise balance computation for expenses"
```

---

### Task 5: Expense/settlement tables and DB-backed recording functions

**Files:**
- Modify: `cogs/expenses.py`
- Test: `tests/test_expenses_db.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_expenses_db.py`:

```python
import database
from cogs import expenses


def test_record_expense_creates_splits_for_all_members(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_expense(conn, house_id, "Pizza", 2000, m1, [m1, m2])

    debts = expenses.get_debts(conn, house_id)
    assert (m2, m1, 1000) in debts
    assert (m1, m1, 1000) in debts


def test_record_settlement_and_get_payments(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_settlement(conn, house_id, m2, m1, 1000)

    payments = expenses.get_payments(conn, house_id)
    assert payments == [(m2, m1, 1000)]


def test_get_debts_empty_when_no_expenses(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    expenses.init_tables(conn)
    assert expenses.get_debts(conn, house_id) == []


def test_get_payments_empty_when_no_settlements(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    expenses.init_tables(conn)
    assert expenses.get_payments(conn, house_id) == []


def test_record_expense_end_to_end_balance(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_expense(conn, house_id, "Pizza", 2000, m1, [m1, m2])

    debts = expenses.get_debts(conn, house_id)
    payments = expenses.get_payments(conn, house_id)
    net = expenses.compute_net_balances(debts, payments)
    assert net == {(m2, m1): 1000}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_expenses_db.py -v`
Expected: FAIL with `AttributeError: module 'cogs.expenses' has no attribute 'init_tables'`

- [ ] **Step 3: Implement table init and DB-backed functions in `cogs/expenses.py`**

Add this import at the top of `cogs/expenses.py`:

```python
import sqlite3
from datetime import datetime, timezone
```

Add the functions:

```python
def init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            description TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            paid_by_member_id INTEGER NOT NULL REFERENCES members(member_id),
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expense_splits (
            split_id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_id INTEGER NOT NULL REFERENCES expenses(expense_id),
            member_id INTEGER NOT NULL REFERENCES members(member_id),
            share_cents INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settlements (
            settlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL REFERENCES houses(house_id),
            from_member_id INTEGER NOT NULL REFERENCES members(member_id),
            to_member_id INTEGER NOT NULL REFERENCES members(member_id),
            amount_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def record_expense(
    conn: sqlite3.Connection,
    house_id: int,
    description: str,
    amount_cents: int,
    paid_by_member_id: int,
    member_ids: list[int],
) -> int:
    cur = conn.execute(
        "INSERT INTO expenses (house_id, description, amount_cents, paid_by_member_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (house_id, description, amount_cents, paid_by_member_id, datetime.now(timezone.utc).isoformat()),
    )
    expense_id = cur.lastrowid
    shares = split_amount(amount_cents, member_ids)
    conn.executemany(
        "INSERT INTO expense_splits (expense_id, member_id, share_cents) VALUES (?, ?, ?)",
        [(expense_id, member_id, share) for member_id, share in shares.items()],
    )
    conn.commit()
    return expense_id


def record_settlement(
    conn: sqlite3.Connection, house_id: int, from_member_id: int, to_member_id: int, amount_cents: int
) -> int:
    cur = conn.execute(
        "INSERT INTO settlements (house_id, from_member_id, to_member_id, amount_cents, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (house_id, from_member_id, to_member_id, amount_cents, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def get_debts(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        "SELECT es.member_id AS ower_id, e.paid_by_member_id AS payer_id, es.share_cents AS cents "
        "FROM expense_splits es JOIN expenses e ON es.expense_id = e.expense_id "
        "WHERE e.house_id = ?",
        (house_id,),
    ).fetchall()
    return [(row["ower_id"], row["payer_id"], row["cents"]) for row in rows]


def get_payments(conn: sqlite3.Connection, house_id: int) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        "SELECT from_member_id, to_member_id, amount_cents FROM settlements WHERE house_id = ?",
        (house_id,),
    ).fetchall()
    return [(row["from_member_id"], row["to_member_id"], row["amount_cents"]) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_expenses_db.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full test suite so far**

Run: `python -m pytest -v`
Expected: PASS (22 passed)

- [ ] **Step 6: Commit**

```bash
git add cogs/expenses.py tests/test_expenses_db.py
git commit -m "feat: add expense/settlement tables and recording functions"
```

---

### Task 6: Expenses Cog — slash commands

**Files:**
- Modify: `cogs/expenses.py`

- [ ] **Step 1: Add Discord imports to `cogs/expenses.py`**

Add these imports at the top of `cogs/expenses.py`:

```python
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
```

- [ ] **Step 2: Add the house/member lookup helper and the `Expenses` cog**

Append to `cogs/expenses.py`:

```python
async def _get_house_and_member(bot: commands.Bot, interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return None
    house = database.get_house(bot.db, str(interaction.guild_id))
    if house is None:
        await interaction.response.send_message(
            "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
        )
        return None
    member = database.get_member(bot.db, house["house_id"], str(interaction.user.id))
    if member is None:
        await interaction.response.send_message(
            "You're not a member of this house yet. Run /join-house first.", ephemeral=True
        )
        return None
    return house, member


class Expenses(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_tables(bot.db)

    @app_commands.command(name="add-expense", description="Add a shared expense and split it equally")
    @app_commands.describe(
        description="What the expense was for",
        amount="Amount in dollars, e.g. 42.50",
        paid_by="Who paid (defaults to you)",
    )
    async def add_expense(
        self,
        interaction: discord.Interaction,
        description: str,
        amount: float,
        paid_by: Optional[discord.Member] = None,
    ):
        await self._add_expense_impl(interaction, description, amount, paid_by)

    @app_commands.command(name="pay", description="Shorthand for /add-expense")
    @app_commands.describe(
        description="What the expense was for",
        amount="Amount in dollars, e.g. 42.50",
        paid_by="Who paid (defaults to you)",
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        description: str,
        amount: float,
        paid_by: Optional[discord.Member] = None,
    ):
        await self._add_expense_impl(interaction, description, amount, paid_by)

    async def _add_expense_impl(
        self,
        interaction: discord.Interaction,
        description: str,
        amount: float,
        paid_by: Optional[discord.Member],
    ):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        payer_member = member
        payer_display = interaction.user.display_name
        if paid_by is not None:
            payer_row = database.get_member(self.bot.db, house["house_id"], str(paid_by.id))
            if payer_row is None:
                await interaction.response.send_message(
                    f"{paid_by.display_name} isn't a member of this house.", ephemeral=True
                )
                return
            payer_member = payer_row
            payer_display = paid_by.display_name

        amount_cents = round(amount * 100)
        members = database.list_members(self.bot.db, house["house_id"])
        member_ids = [m["member_id"] for m in members]
        record_expense(
            self.bot.db, house["house_id"], description, amount_cents, payer_member["member_id"], member_ids
        )

        await interaction.response.send_message(
            f"Added expense '{description}' for ${amount:.2f}, paid by {payer_display}, "
            f"split across {len(member_ids)} member(s)."
        )

    @app_commands.command(name="settle", description="Record that you paid someone toward your shared debt")
    @app_commands.describe(amount="Amount in dollars you paid", to="Who you paid")
    async def settle(self, interaction: discord.Interaction, amount: float, to: discord.Member):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, member = result
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        to_row = database.get_member(self.bot.db, house["house_id"], str(to.id))
        if to_row is None:
            await interaction.response.send_message(f"{to.display_name} isn't a member of this house.", ephemeral=True)
            return

        amount_cents = round(amount * 100)
        record_settlement(self.bot.db, house["house_id"], member["member_id"], to_row["member_id"], amount_cents)
        await interaction.response.send_message(f"Recorded: you paid {to.display_name} ${amount:.2f}.")

    @app_commands.command(name="balances", description="Show who owes whom in this house")
    async def balances(self, interaction: discord.Interaction):
        await self._balances_impl(interaction)

    @app_commands.command(name="bal", description="Shorthand for /balances")
    async def bal(self, interaction: discord.Interaction):
        await self._balances_impl(interaction)

    async def _balances_impl(self, interaction: discord.Interaction):
        result = await _get_house_and_member(self.bot, interaction)
        if result is None:
            return
        house, _ = result

        debts = get_debts(self.bot.db, house["house_id"])
        payments = get_payments(self.bot.db, house["house_id"])
        net = compute_net_balances(debts, payments)

        if not net:
            await interaction.response.send_message("Everyone is settled up!")
            return

        members = {m["member_id"]: m["display_name"] for m in database.list_members(self.bot.db, house["house_id"])}
        lines = [
            f"{members.get(ower_id, ower_id)} owes {members.get(owee_id, owee_id)} ${cents / 100:.2f}"
            for (ower_id, owee_id), cents in net.items()
        ]
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(Expenses(bot))
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `python -m pytest -v`
Expected: PASS (22 passed) — these are unit tests of the pure/DB functions; they don't exercise the Discord command layer added in this step.

- [ ] **Step 4: Sanity-check the module imports cleanly**

Run: `python -c "import cogs.expenses"`
Expected: no output, exit code 0

- [ ] **Step 5: Commit**

```bash
git add cogs/expenses.py
git commit -m "feat: wire up expense slash commands (add-expense/pay, settle, balances/bal)"
```

---

### Task 7: Core Cog — house/member registration commands

**Files:**
- Create: `cogs/core.py`

- [ ] **Step 1: Implement `cogs/core.py`**

```python
import discord
from discord import app_commands
from discord.ext import commands

import database


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="house-setup", description="Set up this server as a house")
    async def house_setup(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        existing = database.get_house(self.bot.db, str(interaction.guild_id))
        if existing is not None:
            await interaction.response.send_message("This server already has a house set up.", ephemeral=True)
            return

        database.create_house(self.bot.db, str(interaction.guild_id), interaction.guild.name)
        await interaction.response.send_message(
            f"House set up for {interaction.guild.name}! Members can now run /join-house."
        )

    @app_commands.command(name="join-house", description="Join this server's house")
    async def join_house(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        house = database.get_house(self.bot.db, str(interaction.guild_id))
        if house is None:
            await interaction.response.send_message(
                "This server doesn't have a house set up yet. Run /house-setup first.", ephemeral=True
            )
            return

        existing = database.get_member(self.bot.db, house["house_id"], str(interaction.user.id))
        if existing is not None:
            await interaction.response.send_message("You're already a member of this house.", ephemeral=True)
            return

        database.add_member(
            self.bot.db, house["house_id"], str(interaction.user.id), interaction.user.display_name
        )
        await interaction.response.send_message(f"{interaction.user.display_name} joined the house!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
```

- [ ] **Step 2: Sanity-check the module imports cleanly**

Run: `python -c "import cogs.core"`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add cogs/core.py
git commit -m "feat: add house-setup and join-house commands"
```

---

### Task 8: Bot entry point

**Files:**
- Create: `bot.py`

- [ ] **Step 1: Implement `bot.py`**

```python
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database

load_dotenv()

DB_PATH = os.environ.get("HOMEBASE_DB_PATH", "homebase.db")

intents = discord.Intents.default()


class HomeBaseBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.db = database.connect(DB_PATH)
        database.init_db(self.db)

    async def setup_hook(self):
        await self.load_extension("cogs.core")
        await self.load_extension("cogs.expenses")
        await self.tree.sync()


def main():
    token = os.environ["DISCORD_TOKEN"]
    bot = HomeBaseBot()
    bot.run(token)


if __name__ == "__main__":
    main()
```

Note: `DISCORD_TOKEN` is only read inside `main()`, not at import time, so `bot.py` can be imported for a sanity check without the environment variable set.

- [ ] **Step 2: Sanity-check the module imports cleanly**

Run: `python -c "import bot"`
Expected: no output, exit code 0 (this also creates a `homebase.db` file in the working directory — that's expected, it's the real bot's local database)

- [ ] **Step 3: Remove the sanity-check artifact database**

Run: `rm -f homebase.db`

- [ ] **Step 4: Run the full automated test suite one more time**

Run: `python -m pytest -v`
Expected: PASS (22 passed)

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: add bot entry point wiring core and expenses cogs"
```

---

### Task 9: Manual end-to-end verification

This task has no automated tests — it exercises the real Discord command layer, which requires a live bot connection and is out of scope for `pytest` per the spec's testing approach.

**Files:** none (verification only)

- [ ] **Step 1: Set up a real bot token**

Copy `.env.example` to `.env` and fill in a real `DISCORD_TOKEN` from the Discord Developer Portal for a bot invited to a test server, with the `applications.commands` scope granted.

- [ ] **Step 2: Run the bot**

Run: `python bot.py`
Expected: bot logs in and slash commands sync to the test server (may take up to an hour to propagate globally, or use a guild-specific sync if testing immediately — note this for later if slash commands don't appear right away).

- [ ] **Step 3: Walk through the golden path in the test server**

1. Run `/house-setup` — expect confirmation message, second attempt errors with "already has a house set up".
2. Run `/join-house` as two different users — expect both to succeed; running it twice as the same user errors with "already a member".
3. Run `/add-expense description:"Groceries" amount:20.00` as user A — expect confirmation, split across 2 members.
4. Run `/pay description:"Pizza" amount:10.00 paid_by:@userB` as user A — expect confirmation crediting user B as payer.
5. Run `/balances` (and `/bal`) — expect a single net line showing the correct combined debt direction and amount between A and B.
6. Run `/settle amount:<net amount> to:@<creditor>` as the debtor — expect confirmation.
7. Run `/balances` again — expect "Everyone is settled up!".

- [ ] **Step 4: Note any discrepancies**

If any step doesn't match expectations, file them as follow-up fixes before considering this feature done — do not silently patch behavior described in the spec without updating the spec first.
