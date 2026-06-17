from datetime import date

import database
from cogs import chores


def _setup(conn):
    house_id = database.create_house(conn, "g1", "House")
    m1 = database.add_member(conn, house_id, "u1", "Alice")
    m2 = database.add_member(conn, house_id, "u2", "Bob")
    chores.init_tables(conn)
    return house_id, m1, m2


def test_reminder_is_none_when_no_chores(conn):
    house_id, *_ = _setup(conn)
    assert chores.render_chores_reminder(conn, house_id, date(2026, 1, 1)) is None


def test_reminder_lists_chores_and_assignees(conn):
    house_id, _m1, _m2 = _setup(conn)
    chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    chores.add_chore(conn, house_id, "Trash", "daily", "2026-01-01")

    # period 0 -> first member (Alice); period 1 -> second member (Bob)
    msg_day0 = chores.render_chores_reminder(conn, house_id, date(2026, 1, 1))
    assert "Dishes" in msg_day0 and "Trash" in msg_day0
    assert "Alice" in msg_day0

    msg_day1 = chores.render_chores_reminder(conn, house_id, date(2026, 1, 2))
    assert "Bob" in msg_day1


def test_reminder_reflects_completion_and_swap(conn):
    house_id, m1, m2 = _setup(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    # day 0, period 0
    chores.record_completion(conn, cid, 0, m1)
    chores.record_swap(conn, cid, 0, m2)

    msg = chores.render_chores_reminder(conn, house_id, date(2026, 1, 1))
    assert "done" in msg
    assert "swapped" in msg
    assert "Bob" in msg  # swap override assignee
