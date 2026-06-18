from datetime import date

import database
from cogs import vacation


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    vacation.init_tables(conn)
    return house_id, alice, bob


# --- pure: is_on_vacation ---


def test_is_on_vacation_within_range():
    assert vacation.is_on_vacation("2026-06-01", "2026-06-30", date(2026, 6, 15))


def test_is_on_vacation_on_start_date():
    assert vacation.is_on_vacation("2026-06-15", "2026-06-20", date(2026, 6, 15))


def test_is_on_vacation_on_end_date():
    assert vacation.is_on_vacation("2026-06-15", "2026-06-20", date(2026, 6, 20))


def test_is_on_vacation_before_start():
    assert not vacation.is_on_vacation("2026-06-15", "2026-06-20", date(2026, 6, 14))


def test_is_on_vacation_after_end():
    assert not vacation.is_on_vacation("2026-06-15", "2026-06-20", date(2026, 6, 21))


def test_is_on_vacation_open_ended():
    assert vacation.is_on_vacation("2026-06-01", None, date(2026, 12, 31))


def test_is_on_vacation_open_ended_before_start():
    assert not vacation.is_on_vacation("2026-06-01", None, date(2026, 5, 31))


# --- pure: format_vacation_list ---


def test_format_vacation_list_empty():
    assert "No one" in vacation.format_vacation_list([])


def test_format_vacation_list_with_end_date():
    entries = [("Alice", "2026-06-15", "2026-06-22")]
    msg = vacation.format_vacation_list(entries)
    assert "Alice" in msg
    assert "June 15" in msg
    assert "June 22" in msg


def test_format_vacation_list_open_ended():
    entries = [("Bob", "2026-06-18", None)]
    msg = vacation.format_vacation_list(entries)
    assert "Bob" in msg
    assert "no return date" in msg.lower()


def test_format_vacation_list_count():
    entries = [("Alice", "2026-06-15", None), ("Bob", "2026-06-18", None)]
    msg = vacation.format_vacation_list(entries)
    assert "2 total" in msg


# --- DB ---


def test_start_and_get_active_vacation(conn):
    house_id, alice, _ = _house(conn)
    today = date(2026, 6, 15)
    vacation.start_vacation(conn, house_id, alice, today)
    row = vacation.get_active_vacation(conn, alice, today)
    assert row is not None
    assert row["start_date"] == "2026-06-15"
    assert row["end_date"] is None


def test_start_vacation_with_end_date(conn):
    house_id, alice, _ = _house(conn)
    start = date(2026, 6, 15)
    end = date(2026, 6, 22)
    vacation.start_vacation(conn, house_id, alice, start, end)
    row = vacation.get_active_vacation(conn, alice, date(2026, 6, 18))
    assert row is not None
    assert row["end_date"] == "2026-06-22"


def test_start_vacation_not_active_before_start(conn):
    house_id, alice, _ = _house(conn)
    vacation.start_vacation(conn, house_id, alice, date(2026, 6, 15))
    assert vacation.get_active_vacation(conn, alice, date(2026, 6, 14)) is None


def test_start_vacation_not_active_after_end(conn):
    house_id, alice, _ = _house(conn)
    vacation.start_vacation(conn, house_id, alice, date(2026, 6, 15), date(2026, 6, 22))
    assert vacation.get_active_vacation(conn, alice, date(2026, 6, 23)) is None


def test_start_vacation_already_on_vacation_raises(conn):
    import pytest
    house_id, alice, _ = _house(conn)
    vacation.start_vacation(conn, house_id, alice, date(2026, 6, 15))
    with pytest.raises(ValueError, match="already on vacation"):
        vacation.start_vacation(conn, house_id, alice, date(2026, 6, 18))


def test_end_vacation(conn):
    house_id, alice, _ = _house(conn)
    start = date(2026, 6, 15)
    vacation.start_vacation(conn, house_id, alice, start)
    result = vacation.end_vacation(conn, alice, date(2026, 6, 20))
    assert result is True
    assert vacation.get_active_vacation(conn, alice, date(2026, 6, 21)) is None


def test_end_vacation_not_on_vacation_returns_false(conn):
    house_id, alice, _ = _house(conn)
    vacation.init_tables(conn)
    assert vacation.end_vacation(conn, alice, date(2026, 6, 20)) is False


def test_active_member_ids_excludes_vacationers(conn):
    house_id, alice, bob = _house(conn)
    today = date(2026, 6, 15)
    vacation.start_vacation(conn, house_id, alice, today)
    active = vacation.active_member_ids(conn, house_id, today)
    assert alice not in active
    assert bob in active


def test_active_member_ids_all_active_when_no_vacations(conn):
    house_id, alice, bob = _house(conn)
    today = date(2026, 6, 15)
    active = vacation.active_member_ids(conn, house_id, today)
    assert alice in active
    assert bob in active


def test_active_member_ids_after_vacation_ends(conn):
    house_id, alice, bob = _house(conn)
    vacation.start_vacation(conn, house_id, alice, date(2026, 6, 15))
    vacation.end_vacation(conn, alice, date(2026, 6, 20))
    active = vacation.active_member_ids(conn, house_id, date(2026, 6, 21))
    assert alice in active


def test_list_active_vacations(conn):
    house_id, alice, bob = _house(conn)
    today = date(2026, 6, 15)
    vacation.start_vacation(conn, house_id, alice, today)
    entries = vacation.list_active_vacations(conn, house_id, today)
    names = [e[0] for e in entries]
    assert "Alice" in names
    assert "Bob" not in names


def test_vacations_are_house_scoped(conn):
    house_id, alice, _ = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    today = date(2026, 6, 15)
    vacation.start_vacation(conn, other, other_alice, today)
    active = vacation.active_member_ids(conn, house_id, today)
    assert alice in active
