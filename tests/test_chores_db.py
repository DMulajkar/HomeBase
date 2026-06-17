import pytest

import database
from cogs import chores


def _setup(conn):
    house_id = database.create_house(conn, "g1", "House")
    m1 = database.add_member(conn, house_id, "u1", "Alice")
    m2 = database.add_member(conn, house_id, "u2", "Bob")
    chores.init_tables(conn)
    return house_id, m1, m2


def test_add_and_list_chores(conn):
    house_id, _m1, _m2 = _setup(conn)
    chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    chores.add_chore(conn, house_id, "Trash", "weekly", "2026-01-01")
    rows = chores.list_chores(conn, house_id)
    assert [r["name"] for r in rows] == ["Dishes", "Trash"]
    assert rows[0]["cadence"] == "daily"


def test_duplicate_chore_name_rejected(conn):
    house_id, *_ = _setup(conn)
    chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    with pytest.raises(ValueError):
        chores.add_chore(conn, house_id, "Dishes", "weekly", "2026-01-01")


def test_get_chore(conn):
    house_id, *_ = _setup(conn)
    chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    assert chores.get_chore(conn, house_id, "Dishes")["cadence"] == "daily"
    assert chores.get_chore(conn, house_id, "Nope") is None


def test_record_completion_unique_per_period(conn):
    house_id, m1, m2 = _setup(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    chores.record_completion(conn, cid, 0, m1)
    assert chores.get_completion(conn, cid, 0)["member_id"] == m1
    with pytest.raises(ValueError):
        chores.record_completion(conn, cid, 0, m2)
    # a different period is fine
    chores.record_completion(conn, cid, 1, m2)
    assert chores.get_completion(conn, cid, 1)["member_id"] == m2


def test_swap_override_upserts(conn):
    house_id, m1, m2 = _setup(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    chores.record_swap(conn, cid, 0, m1)
    assert chores.get_override(conn, cid, 0)["member_id"] == m1
    chores.record_swap(conn, cid, 0, m2)  # overwrites, not duplicates
    assert chores.get_override(conn, cid, 0)["member_id"] == m2
    assert chores.get_override(conn, cid, 1) is None


def test_completion_counts_tally(conn):
    house_id, m1, m2 = _setup(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", "2026-01-01")
    chores.record_completion(conn, cid, 0, m1)
    chores.record_completion(conn, cid, 1, m1)
    chores.record_completion(conn, cid, 2, m2)
    counts = {mid: cnt for mid, _name, cnt in chores.completion_counts(conn, house_id)}
    assert counts[m1] == 2
    assert counts[m2] == 1


def test_completion_counts_includes_members_with_zero(conn):
    house_id, m1, m2 = _setup(conn)
    counts = {mid: cnt for mid, _name, cnt in chores.completion_counts(conn, house_id)}
    assert counts == {m1: 0, m2: 0}
