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


# --- pure: days_until_due ---


def test_days_until_due_future():
    assert finance.days_until_due(date(2026, 6, 10), 15) == 5


def test_days_until_due_zero_on_due_day():
    assert finance.days_until_due(date(2026, 6, 15), 15) == 0


def test_days_until_due_none_after_due_date():
    assert finance.days_until_due(date(2026, 6, 16), 15) is None


def test_days_until_due_clamps_short_month():
    # due_day 31 in June (30 days) resolves to the 30th.
    assert finance.days_until_due(date(2026, 6, 28), 31) == 2


# --- render_upcoming_bills ---


def test_reminder_none_when_no_bills(conn):
    house_id, *_ = _setup(conn)
    assert finance.render_upcoming_bills(conn, house_id, date(2026, 6, 1)) is None


def test_reminder_lists_bill_within_window(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 15, m1, "2026-06-01")
    msg = finance.render_upcoming_bills(conn, house_id, date(2026, 6, 13))  # 2 days out
    assert msg is not None
    assert "Rent" in msg and "in 2 days" in msg


def test_reminder_says_today_on_due_day(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 15, m1, "2026-06-01")
    msg = finance.render_upcoming_bills(conn, house_id, date(2026, 6, 15))
    assert msg is not None and "due today" in msg


def test_reminder_excludes_bill_outside_window(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 15, m1, "2026-06-01")
    # 14 days out -> beyond the 3-day lead.
    assert finance.render_upcoming_bills(conn, house_id, date(2026, 6, 1)) is None


def test_reminder_skips_already_posted_bill(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 150000, 15, m1, "2026-06-01")
    bill = finance.get_bill(conn, house_id, "Rent")
    finance.record_posting(conn, bill, "2026-06", 150000, [m1, m2])
    assert finance.render_upcoming_bills(conn, house_id, date(2026, 6, 14)) is None


def test_reminder_variable_bill_shows_hint(conn):
    house_id, _m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Electric", "variable", None, 5, m2, "2026-06-01")
    msg = finance.render_upcoming_bills(conn, house_id, date(2026, 6, 3))
    assert msg is not None
    assert "varies" in msg and "/bill-post" in msg
