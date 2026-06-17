from datetime import date

import database
from cogs import expenses, finance


def _setup(conn):
    house_id = database.create_house(conn, "g1", "House")
    m1 = database.add_member(conn, house_id, "u1", "Alice")
    m2 = database.add_member(conn, house_id, "u2", "Bob")
    expenses.init_tables(conn)
    finance.init_tables(conn)
    return house_id, m1, m2


def test_is_summary_day():
    assert finance.is_summary_day(date(2026, 6, 1), 1) is True
    assert finance.is_summary_day(date(2026, 6, 2), 1) is False


def test_summary_none_on_non_summary_day(conn):
    house_id, *_ = _setup(conn)
    assert finance.render_monthly_summary(conn, house_id, date(2026, 6, 17)) is None


def test_summary_settled_when_no_debts(conn):
    house_id, *_ = _setup(conn)
    msg = finance.render_monthly_summary(conn, house_id, date(2026, 6, 1))
    assert msg is not None and "settled up" in msg


def test_summary_reports_outstanding_balance(conn):
    house_id, m1, m2 = _setup(conn)
    # Alice fronts $100 rent split two ways -> Bob owes Alice $50.
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")
    finance.record_posting(conn, bill, "2026-06", 10000, [m1, m2])
    msg = finance.render_monthly_summary(conn, house_id, date(2026, 7, 1))
    assert msg is not None and "Bob owes Alice $50.00" in msg
