import database
from cogs import suggestions


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    suggestions.init_tables(conn)
    return house_id, alice, bob


# --- pure ---


def test_format_suggestions_list_empty():
    msg = suggestions.format_suggestions_list([])
    assert "No suggestions" in msg
    assert "/suggestion" in msg


def test_format_suggestions_list_shows_numbers_and_text():
    rows = [(1, "Fix the heater"), (2, "Get a new vacuum")]
    msg = suggestions.format_suggestions_list(rows)
    assert "#1: Fix the heater" in msg
    assert "#2: Get a new vacuum" in msg


def test_format_suggestions_list_shows_count():
    rows = [(1, "One"), (2, "Two"), (3, "Three")]
    msg = suggestions.format_suggestions_list(rows)
    assert "3 total" in msg


def test_format_suggestions_list_no_names():
    rows = [(1, "Something")]
    msg = suggestions.format_suggestions_list(rows)
    assert "Alice" not in msg
    assert "Bob" not in msg


# --- DB ---


def test_record_suggestion_returns_count(conn):
    house_id, alice, _ = _house(conn)
    assert suggestions.record_suggestion(conn, house_id, alice, "First") == 1
    assert suggestions.record_suggestion(conn, house_id, alice, "Second") == 2


def test_suggestion_count(conn):
    house_id, alice, _ = _house(conn)
    assert suggestions.suggestion_count(conn, house_id) == 0
    suggestions.record_suggestion(conn, house_id, alice, "One")
    assert suggestions.suggestion_count(conn, house_id) == 1


def test_list_suggestions_order(conn):
    house_id, alice, bob = _house(conn)
    suggestions.record_suggestion(conn, house_id, alice, "First")
    suggestions.record_suggestion(conn, house_id, bob, "Second")
    rows = suggestions.list_suggestions(conn, house_id)
    assert rows == [(1, "First"), (2, "Second")]


def test_list_suggestions_empty(conn):
    house_id, *_ = _house(conn)
    assert suggestions.list_suggestions(conn, house_id) == []


def test_suggestions_are_house_scoped(conn):
    house_id, alice, _ = _house(conn)
    other = database.create_house(conn, "g2", "Other House")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    suggestions.record_suggestion(conn, other, other_alice, "From other house")
    assert suggestions.suggestion_count(conn, house_id) == 0
    assert suggestions.list_suggestions(conn, house_id) == []


def test_multiple_members_can_submit(conn):
    house_id, alice, bob = _house(conn)
    suggestions.record_suggestion(conn, house_id, alice, "Alice's idea")
    suggestions.record_suggestion(conn, house_id, bob, "Bob's idea")
    rows = suggestions.list_suggestions(conn, house_id)
    assert len(rows) == 2
