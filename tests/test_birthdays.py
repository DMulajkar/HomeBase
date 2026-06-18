from datetime import date

import database
from cogs import birthdays


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    birthdays.init_tables(conn)
    return house_id, alice, bob


# --- pure: parse_birthday ---


def test_parse_birthday_long_month():
    assert birthdays.parse_birthday("March 15") == (3, 15)


def test_parse_birthday_lowercase():
    assert birthdays.parse_birthday("march 15") == (3, 15)


def test_parse_birthday_abbrev():
    assert birthdays.parse_birthday("Mar 15") == (3, 15)


def test_parse_birthday_slash():
    assert birthdays.parse_birthday("3/15") == (3, 15)


def test_parse_birthday_zero_padded_slash():
    assert birthdays.parse_birthday("03/15") == (3, 15)


def test_parse_birthday_dash():
    assert birthdays.parse_birthday("03-15") == (3, 15)


def test_parse_birthday_invalid():
    import pytest
    with pytest.raises(ValueError, match="Could not parse"):
        birthdays.parse_birthday("not a date")


# --- pure: format_birthday_list ---


def test_format_birthday_list_empty():
    msg = birthdays.format_birthday_list([])
    assert "No birthdays" in msg
    assert "/birthday-set" in msg


def test_format_birthday_list_shows_names_and_dates():
    entries = [("Alice", 3, 15), ("Bob", 6, 3)]
    msg = birthdays.format_birthday_list(entries)
    assert "Alice" in msg
    assert "Bob" in msg
    assert "March 15" in msg
    assert "June 3" in msg


def test_format_birthday_list_sorted_by_month_then_day():
    entries = [("Bob", 6, 3), ("Alice", 3, 15), ("Carol", 3, 5)]
    msg = birthdays.format_birthday_list(entries)
    alice_pos = msg.index("Alice")
    carol_pos = msg.index("Carol")
    bob_pos = msg.index("Bob")
    assert carol_pos < alice_pos < bob_pos  # March 5, March 15, June 3


def test_format_birthday_list_shows_count():
    entries = [("Alice", 3, 15), ("Bob", 6, 3)]
    msg = birthdays.format_birthday_list(entries)
    assert "2 total" in msg


# --- pure: render_birthday_reminder ---


def test_render_birthday_reminder_none_today(conn):
    house_id, alice, _ = _house(conn)
    birthdays.set_birthday(conn, alice, 6, 15)
    result = birthdays.render_birthday_reminder(conn, house_id, date(2026, 3, 15))
    assert result is None


def test_render_birthday_reminder_one_match(conn):
    house_id, alice, _ = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    result = birthdays.render_birthday_reminder(conn, house_id, date(2026, 3, 15))
    assert result is not None
    assert "Alice" in result


def test_render_birthday_reminder_multiple(conn):
    house_id, alice, bob = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    birthdays.set_birthday(conn, bob, 3, 15)
    result = birthdays.render_birthday_reminder(conn, house_id, date(2026, 3, 15))
    assert result is not None
    assert "Alice" in result
    assert "Bob" in result


# --- DB ---


def test_set_and_get_birthday(conn):
    house_id, alice, _ = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    row = birthdays.get_birthday(conn, alice)
    assert row["birth_month"] == 3
    assert row["birth_day"] == 15


def test_set_birthday_updates_existing(conn):
    house_id, alice, _ = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    birthdays.set_birthday(conn, alice, 6, 3)
    row = birthdays.get_birthday(conn, alice)
    assert row["birth_month"] == 6
    assert row["birth_day"] == 3


def test_get_birthday_missing_returns_none(conn):
    house_id, alice, _ = _house(conn)
    assert birthdays.get_birthday(conn, alice) is None


def test_list_birthdays_returns_display_names(conn):
    house_id, alice, bob = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    birthdays.set_birthday(conn, bob, 6, 3)
    rows = birthdays.list_birthdays(conn, house_id)
    names = [r["display_name"] for r in rows]
    assert "Alice" in names
    assert "Bob" in names


def test_list_birthdays_ordered_by_month_then_day(conn):
    house_id, alice, bob = _house(conn)
    birthdays.set_birthday(conn, alice, 6, 3)
    birthdays.set_birthday(conn, bob, 3, 15)
    rows = birthdays.list_birthdays(conn, house_id)
    assert rows[0]["birth_month"] == 3
    assert rows[1]["birth_month"] == 6


def test_list_birthdays_excludes_members_without_birthday(conn):
    house_id, alice, bob = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    rows = birthdays.list_birthdays(conn, house_id)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Alice"


def test_list_birthdays_house_scoped(conn):
    house_id, alice, _ = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    birthdays.set_birthday(conn, other_alice, 3, 15)
    assert birthdays.list_birthdays(conn, house_id) == []


def test_get_todays_birthdays(conn):
    house_id, alice, bob = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    birthdays.set_birthday(conn, bob, 6, 3)
    today = date(2026, 3, 15)
    rows = birthdays.get_todays_birthdays(conn, house_id, today)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Alice"


def test_get_todays_birthdays_empty(conn):
    house_id, alice, _ = _house(conn)
    birthdays.set_birthday(conn, alice, 3, 15)
    assert birthdays.get_todays_birthdays(conn, house_id, date(2026, 6, 3)) == []
