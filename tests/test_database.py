import pytest

import database


def test_create_house_and_get_house(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    house = database.get_house(conn, "guild-1")
    assert house["house_id"] == house_id
    assert house["name"] == "The Treehouse"


def test_get_house_returns_none_when_missing(conn):
    assert database.get_house(conn, "no-such-guild") is None


def test_create_house_duplicate_raises(conn):
    database.create_house(conn, "guild-1", "The Treehouse")
    with pytest.raises(ValueError):
        database.create_house(conn, "guild-1", "Duplicate")


def test_add_member_and_get_member(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    member_id = database.add_member(conn, house_id, "user-1", "Alice")
    member = database.get_member(conn, house_id, "user-1")
    assert member["member_id"] == member_id
    assert member["display_name"] == "Alice"


def test_get_member_returns_none_when_missing(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    assert database.get_member(conn, house_id, "no-such-user") is None


def test_add_member_duplicate_raises(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    database.add_member(conn, house_id, "user-1", "Alice")
    with pytest.raises(ValueError):
        database.add_member(conn, house_id, "user-1", "Alice Again")


def test_list_members_ordered_by_member_id(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    database.add_member(conn, house_id, "user-2", "Bob")
    database.add_member(conn, house_id, "user-1", "Alice")
    members = database.list_members(conn, house_id)
    assert [m["discord_user_id"] for m in members] == ["user-2", "user-1"]
