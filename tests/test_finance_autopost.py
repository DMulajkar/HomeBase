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


def test_autopost_none_when_nothing_due(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 15, m1, "2026-06-01")
    # Before the 15th -> not due.
    assert finance.render_due_fixed_bills(conn, house_id, date(2026, 6, 14)) is None


def test_autopost_posts_due_fixed_bill(conn):
    house_id, m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")

    msg = finance.render_due_fixed_bills(conn, house_id, date(2026, 6, 1))
    assert msg is not None
    assert "Rent" in msg

    bill = finance.get_bill(conn, house_id, "Rent")
    assert finance.is_posted(conn, bill["bill_id"], "2026-06") is True
    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert net == {(m2, m1): 5000}


def test_autopost_is_idempotent_across_ticks(conn):
    house_id, m1, _ = _setup(conn)
    finance.add_bill(conn, house_id, "Rent", "fixed", 10000, 1, m1, "2026-06-01")

    first = finance.render_due_fixed_bills(conn, house_id, date(2026, 6, 1))
    assert first is not None
    # A later tick the same month finds nothing new to post.
    second = finance.render_due_fixed_bills(conn, house_id, date(2026, 6, 2))
    assert second is None
    # Exactly one expense was created.
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1


def test_autopost_ignores_variable_bills(conn):
    house_id, _m1, m2 = _setup(conn)
    finance.add_bill(conn, house_id, "Electric", "variable", None, 1, m2, "2026-06-01")
    assert finance.render_due_fixed_bills(conn, house_id, date(2026, 6, 15)) is None
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
