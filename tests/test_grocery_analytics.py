from datetime import date

import database
from cogs import groceries


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    groceries.init_tables(conn)
    return house_id, alice, bob


def _run(conn, house_id, member_id, amount_cents, run_at_iso):
    conn.execute(
        "INSERT INTO grocery_runs (house_id, member_id, amount_cents, expense_id, run_at) "
        "VALUES (?, ?, ?, NULL, ?)",
        (house_id, member_id, amount_cents, run_at_iso),
    )
    conn.commit()


# --- pure: spending_by_member ---


def test_spending_by_member_aggregates_and_sorts():
    runs = [("Alice", 5000), ("Bob", 3000), ("Alice", 2000)]
    result = groceries.spending_by_member(runs)
    assert result == [("Alice", 7000), ("Bob", 3000)]


def test_spending_by_member_single():
    assert groceries.spending_by_member([("Alice", 4000)]) == [("Alice", 4000)]


# --- pure: format_spending_report ---


def test_format_spending_report_includes_totals():
    msg = groceries.format_spending_report("June 2026", 9000, [("Alice", 7000), ("Bob", 2000)], 3)
    assert "June 2026" in msg
    assert "$90.00" in msg
    assert "3 shopping runs" in msg
    assert "Alice: $70.00" in msg
    assert "Bob: $20.00" in msg


def test_format_spending_report_single_run():
    msg = groceries.format_spending_report("June 2026", 5000, [("Alice", 5000)], 1)
    assert "1 shopping run" in msg and "runs" not in msg


# --- DB: grocery_runs_for_month ---


def test_grocery_runs_for_month_filters_by_month(conn):
    house_id, alice, bob = _house(conn)
    _run(conn, house_id, alice, 5000, "2026-06-10T12:00:00+00:00")
    _run(conn, house_id, bob, 3000, "2026-06-20T12:00:00+00:00")
    _run(conn, house_id, alice, 4000, "2026-07-05T12:00:00+00:00")  # should not appear

    runs = groceries.grocery_runs_for_month(conn, house_id, 2026, 6)
    assert len(runs) == 2
    assert all(r["amount_cents"] > 0 for r in runs)


def test_grocery_runs_excludes_no_amount(conn):
    house_id, alice, _bob = _house(conn)
    # A run with no amount (no expense recorded) should not appear.
    conn.execute(
        "INSERT INTO grocery_runs (house_id, member_id, amount_cents, expense_id, run_at) "
        "VALUES (?, ?, NULL, NULL, ?)",
        (house_id, alice, "2026-06-10T12:00:00+00:00"),
    )
    conn.commit()
    assert groceries.grocery_runs_for_month(conn, house_id, 2026, 6) == []


# --- integration: render_spending_report ---


def test_render_spending_report_off_day_is_none(conn):
    house_id, alice, _bob = _house(conn)
    _run(conn, house_id, alice, 5000, "2026-06-10T12:00:00+00:00")
    assert groceries.render_spending_report(conn, house_id, date(2026, 7, 2)) is None


def test_render_spending_report_summarizes_previous_month(conn):
    house_id, alice, bob = _house(conn)
    _run(conn, house_id, alice, 8000, "2026-06-05T12:00:00+00:00")
    _run(conn, house_id, bob, 4500, "2026-06-20T12:00:00+00:00")
    _run(conn, house_id, alice, 6000, "2026-07-03T12:00:00+00:00")  # July, excluded

    msg = groceries.render_spending_report(conn, house_id, date(2026, 7, 1))
    assert msg is not None
    assert "June 2026" in msg
    assert "$125.00" in msg   # 80 + 45
    assert "Alice" in msg and "Bob" in msg
    assert "2 shopping runs" in msg


def test_render_spending_report_none_when_no_runs(conn):
    house_id, _alice, _bob = _house(conn)
    assert groceries.render_spending_report(conn, house_id, date(2026, 7, 1)) is None
