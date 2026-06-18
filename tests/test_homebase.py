from datetime import date

import database
from cogs import homebase
from cogs.chores import add_chore, init_tables as chores_init
from cogs.finance import add_bill, init_tables as finance_init
from cogs.groceries import add_item, init_tables as groceries_init


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    chores_init(conn)
    finance_init(conn)
    groceries_init(conn)
    return house_id, alice, bob


# --- pure: compute_house_health ---


def test_health_perfect():
    assert homebase.compute_house_health(0, 0, 0) == 100


def test_health_overdue_bill():
    assert homebase.compute_house_health(1, 0, 0) == 85


def test_health_due_soon_bill():
    assert homebase.compute_house_health(0, 1, 0) == 95


def test_health_pending_chores():
    assert homebase.compute_house_health(0, 0, 3) == 91


def test_health_clamps_to_zero():
    assert homebase.compute_house_health(10, 10, 20) == 0


def test_health_combined():
    assert homebase.compute_house_health(1, 2, 4) == 100 - 15 - 10 - 12


# --- pure: top_priority ---


def test_priority_overdue_bill():
    msg = homebase.top_priority("Rent", None, 0, 0)
    assert "Rent" in msg
    assert "past due" in msg


def test_priority_bill_due_today():
    msg = homebase.top_priority("Electric", 0, 0, 0)
    assert "Electric" in msg
    assert "today" in msg


def test_priority_bill_due_in_days():
    msg = homebase.top_priority("Internet", 2, 0, 0)
    assert "Internet" in msg
    assert "2 days" in msg


def test_priority_bill_due_in_one_day():
    msg = homebase.top_priority("Internet", 1, 0, 0)
    assert "1 day" in msg
    assert "days" not in msg


def test_priority_chores_when_no_bill():
    msg = homebase.top_priority(None, None, 3, 0)
    assert "3 chores" in msg


def test_priority_groceries_when_many():
    msg = homebase.top_priority(None, None, 0, 8)
    assert "8 items" in msg


def test_priority_all_clear():
    msg = homebase.top_priority(None, None, 0, 2)
    assert "on track" in msg


def test_priority_bill_beats_chores():
    msg = homebase.top_priority("Rent", 1, 5, 10)
    assert "Rent" in msg


# --- pure: format_homebase ---


def test_format_homebase_structure():
    msg = homebase.format_homebase(2, 3, 8, 85, "Pay the electric bill.")
    assert "HomeBase" in msg
    assert "Bills due:        2" in msg
    assert "Chores pending:   3" in msg
    assert "Groceries needed: 8" in msg
    assert "85/100" in msg
    assert "Pay the electric bill." in msg


# --- DB: gather_status ---


def test_gather_status_empty_house(conn):
    house_id, _, _ = _house(conn)
    today = date(2026, 6, 17)
    status = homebase.gather_status(conn, house_id, today)
    assert status["chores_pending"] == 0
    assert status["bills_overdue"] == 0
    assert status["bills_due_soon"] == 0
    assert status["groceries_needed"] == 0
    assert status["urgent_bill_name"] is None


def test_gather_status_counts_pending_chores(conn):
    house_id, alice, _ = _house(conn)
    today = date(2026, 6, 17)
    add_chore(conn, house_id, "Dishes", "daily", today.isoformat())
    add_chore(conn, house_id, "Trash", "weekly", today.isoformat())
    status = homebase.gather_status(conn, house_id, today)
    assert status["chores_pending"] == 2


def test_gather_status_counts_groceries(conn):
    house_id, alice, _ = _house(conn)
    today = date(2026, 6, 17)
    add_item(conn, house_id, "Milk", "Food", alice)
    add_item(conn, house_id, "Bread", "Food", alice)
    status = homebase.gather_status(conn, house_id, today)
    assert status["groceries_needed"] == 2


def test_gather_status_bill_due_soon(conn):
    house_id, alice, _ = _house(conn)
    today = date(2026, 6, 17)
    # Due day 18 = tomorrow from today (June 17)
    add_bill(conn, house_id, "Electric", "variable", None, 18, alice, today.isoformat())
    status = homebase.gather_status(conn, house_id, today)
    assert status["bills_due_soon"] == 1
    assert status["urgent_bill_name"] == "Electric"
    assert status["urgent_bill_days"] == 1


def test_gather_status_bill_overdue(conn):
    house_id, alice, _ = _house(conn)
    today = date(2026, 6, 17)
    # Due day 10 = already passed this month
    add_bill(conn, house_id, "Rent", "variable", None, 10, alice, "2026-06-01")
    status = homebase.gather_status(conn, house_id, today)
    assert status["bills_overdue"] == 1
    assert status["urgent_bill_name"] == "Rent"
    assert status["urgent_bill_days"] is None
