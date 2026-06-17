from datetime import date

import pytest

import database
from cogs import expenses, finance


def _setup(conn):
    house_id = database.create_house(conn, "g1", "House")
    m1 = database.add_member(conn, house_id, "u1", "Alice")
    m2 = database.add_member(conn, house_id, "u2", "Bob")
    expenses.init_tables(conn)
    finance.init_tables(conn)
    return house_id, m1, m2


def test_add_and_get_bill(conn):
    house_id, m1, _ = _setup(conn)
    bill_id = finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 1, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")
    assert bill["bill_id"] == bill_id
    assert bill["kind"] == "fixed"
    assert bill["amount_cents"] == 150000
    assert bill["payer_member_id"] == m1


def test_add_bill_duplicate_name_raises(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 1, m1, "2026-06-01")
    with pytest.raises(ValueError):
        finance.add_bill(conn, house_id, "Rent", "fixed", 160000, 1, m1, "2026-06-01")


def test_variable_bill_has_null_amount(conn):
    house_id, _m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Electric", "variable", None, 15, m2, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Electric")
    assert bill["amount_cents"] is None
    assert bill["kind"] == "variable"


def test_list_bills_sorted_by_name(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Water", "variable", None, 10, m1, "2026-06-01")
    finance.add_bill(conn, house_id, "Internet", "fixed", 6000, 5, m1, "2026-06-01")
    names = [b["name"] for b in finance.list_bills(conn, house_id)]
    assert names == ["Internet", "Water"]


def test_remove_bill(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 1, m1, "2026-06-01")
    assert finance.remove_bill(conn, house_id, "Rent") is True
    assert finance.get_bill(conn, house_id, "Rent") is None
    assert finance.remove_bill(conn, house_id, "Rent") is False


def test_record_posting_creates_expense_feeding_balances(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")

    finance.record_posting(conn, bill, "2026-06", 10000, [m1, m2])

    # Bob owes Alice his half of the $100 rent that Alice (the payer) fronted.
    debts = expenses.get_debts(conn, house_id)
    payments = expenses.get_payments(conn, house_id)
    net = expenses.compute_net_balances(debts, payments)
    assert net == {(m2, m1): 5000}


def test_record_posting_is_idempotent_per_period(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")

    finance.record_posting(conn, bill, "2026-06", 10000, [m1, m2])
    assert finance.is_posted(conn, bill["bill_id"], "2026-06") is True
    with pytest.raises(ValueError):
        finance.record_posting(conn, bill, "2026-06", 10000, [m1, m2])


def test_record_posting_uses_supplied_amount_for_variable(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Electric", "variable", None, 15, m2, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Electric")

    finance.record_posting(conn, bill, "2026-06", 8000, [m1, m2])

    # Alice owes Bob (the payer) half of the $80 electric bill.
    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert net == {(m1, m2): 4000}


def test_remove_bill_clears_postings_but_keeps_expense(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")
    finance.record_posting(conn, bill, "2026-06", 10000, [m1, m2])

    finance.remove_bill(conn, house_id, "Rent")

    # The recurring definition and its posting records are gone...
    assert conn.execute("SELECT COUNT(*) FROM bill_postings").fetchone()[0] == 0
    # ...but the debt it created is real and stays.
    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert net == {(m2, m1): 5000}
