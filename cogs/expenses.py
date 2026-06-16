import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


def split_amount(amount_cents: int, member_ids: list[int]) -> dict[int, int]:
    n = len(member_ids)
    base = amount_cents // n
    remainder = amount_cents % n
    shares = {}
    for i, member_id in enumerate(member_ids):
        shares[member_id] = base + (1 if i < remainder else 0)
    return shares


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
