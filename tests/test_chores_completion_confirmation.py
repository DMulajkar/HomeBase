from datetime import date

import database
from cogs import chores


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    chores.init_tables(conn)
    return house_id, alice, bob


# --- pure: _ordinal ---


def test_ordinal_basic():
    assert chores._ordinal(1) == "1st"
    assert chores._ordinal(2) == "2nd"
    assert chores._ordinal(3) == "3rd"
    assert chores._ordinal(4) == "4th"


def test_ordinal_teens_are_th():
    assert chores._ordinal(11) == "11th"
    assert chores._ordinal(12) == "12th"
    assert chores._ordinal(13) == "13th"


def test_ordinal_large():
    assert chores._ordinal(21) == "21st"
    assert chores._ordinal(22) == "22nd"
    assert chores._ordinal(23) == "23rd"
    assert chores._ordinal(111) == "111th"


# --- pure: format_completion_confirmation ---


def test_confirmation_includes_member_and_chore():
    msg = chores.format_completion_confirmation("Dhruv", "Dishes", 3)
    assert "Dhruv" in msg and "Dishes" in msg
    assert "nice work" in msg.lower()
    assert "3rd chore" in msg


def test_confirmation_first_completion():
    msg = chores.format_completion_confirmation("Sarah", "Trash", 1)
    assert "1st chore" in msg


def test_confirmation_omits_count_when_unknown():
    msg = chores.format_completion_confirmation("Ryan", "Vacuum", 0)
    assert "chore done" not in msg
    assert "Ryan" in msg and "Vacuum" in msg


# --- integration: a real completion feeds the confirmation ---


def test_count_increments_with_completions(conn):
    house_id, alice, bob = _house(conn)
    chore_id = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())

    assert chores.member_completion_count(conn, house_id, alice) == 0

    chores.record_completion(conn, chore_id, 0, alice)
    chores.record_completion(conn, chore_id, 1, alice)
    assert chores.member_completion_count(conn, house_id, alice) == 2
    assert chores.member_completion_count(conn, house_id, bob) == 0

    total = chores.member_completion_count(conn, house_id, alice)
    msg = chores.format_completion_confirmation("Alice", "Dishes", total)
    assert "Alice completed **Dishes**" in msg or "**Alice** completed" in msg
    assert "2nd chore" in msg


def test_count_is_scoped_to_house(conn):
    house_id, alice, _bob = _house(conn)
    other_house = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other_house, "u1", "Alice")
    other_chore = chores.add_chore(conn, other_house, "Mop", "daily", date(2026, 6, 1).isoformat())
    chores.record_completion(conn, other_chore, 0, other_alice)

    # alice in house_id has no completions; the other house's don't leak in.
    assert chores.member_completion_count(conn, house_id, alice) == 0
