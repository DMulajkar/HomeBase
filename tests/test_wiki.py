import database
from cogs import wiki


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    wiki.init_tables(conn)
    return house_id, alice, bob


# --- pure ---


def test_normalize_key_lowercases_and_strips():
    assert wiki.normalize_key("  Wi-Fi Password  ") == "wi-fi password"
    assert wiki.normalize_key("Landlord") == "landlord"


def test_format_entry_includes_category():
    msg = wiki.format_entry("wifi password", "HomeBase2024!", "Access & Security")
    assert "**wifi password**" in msg
    assert "HomeBase2024!" in msg
    assert "Access & Security" in msg


def test_format_wiki_list_empty():
    msg = wiki.format_wiki_list([])
    assert "empty" in msg.lower() and "/wiki-set" in msg


def test_format_wiki_list_groups_by_category():
    entries = [
        ("quiet hours",   "10pm–8am",      "House Rules"),
        ("alarm code",    "1234",           "Access & Security"),
        ("trash pickup",  "Tuesday",        "Utilities & Services"),
        ("landlord",      "Jane 555-1234",  "Building & Maintenance"),
    ]
    msg = wiki.format_wiki_list(entries)
    assert "📖 **House wiki**" in msg
    assert "**Access & Security**" in msg
    assert "**House Rules**" in msg
    # Access & Security appears before House Rules (CATEGORIES order)
    assert msg.index("Access & Security") < msg.index("House Rules")


def test_group_by_category_respects_order():
    entries = [
        ("quiet hours", "10pm", "House Rules"),
        ("alarm code",  "1234", "Access & Security"),
    ]
    grouped = wiki.group_by_category(entries)
    keys = list(grouped.keys())
    assert keys.index("Access & Security") < keys.index("House Rules")


# --- DB ---


def test_set_and_get_entry_with_category(conn):
    house_id, alice, _ = _house(conn)
    created = wiki.set_entry(conn, house_id, "alarm code", "1234", alice, "Access & Security")
    assert created is True
    entry = wiki.get_entry(conn, house_id, "alarm code")
    assert entry["value"] == "1234"
    assert entry["category"] == "Access & Security"


def test_set_defaults_to_general(conn):
    house_id, alice, _ = _house(conn)
    wiki.set_entry(conn, house_id, "misc", "stuff", alice)
    assert wiki.get_entry(conn, house_id, "misc")["category"] == "General"


def test_set_updates_existing_including_category(conn):
    house_id, alice, bob = _house(conn)
    wiki.set_entry(conn, house_id, "wifi password", "old", alice, "General")
    created = wiki.set_entry(conn, house_id, "wifi password", "new", bob, "Access & Security")
    assert created is False
    entry = wiki.get_entry(conn, house_id, "wifi password")
    assert entry["value"] == "new"
    assert entry["category"] == "Access & Security"


def test_get_missing_returns_none(conn):
    house_id, *_ = _house(conn)
    assert wiki.get_entry(conn, house_id, "ghost") is None


def test_list_entries_ordered_by_category_then_key(conn):
    house_id, alice, _ = _house(conn)
    wiki.set_entry(conn, house_id, "quiet hours", "10pm", alice, "House Rules")
    wiki.set_entry(conn, house_id, "alarm code", "1234", alice, "Access & Security")
    wiki.set_entry(conn, house_id, "gate code", "5678", alice, "Access & Security")
    rows = wiki.list_entries(conn, house_id)
    # Access & Security comes first; within it, alarm code before gate code
    assert rows[0]["category"] == "Access & Security"
    assert rows[0]["key"] == "alarm code"
    assert rows[1]["key"] == "gate code"
    assert rows[2]["category"] == "House Rules"


def test_remove_entry(conn):
    house_id, alice, _ = _house(conn)
    wiki.set_entry(conn, house_id, "wifi password", "abc", alice)
    assert wiki.remove_entry(conn, house_id, "wifi password") is True
    assert wiki.remove_entry(conn, house_id, "wifi password") is False


def test_seed_setup_entries_adds_all(conn):
    house_id, alice, _ = _house(conn)
    added, skipped = wiki.seed_setup_entries(conn, house_id, alice)
    assert added == len(wiki.SETUP_ENTRIES)
    assert skipped == 0
    # All entries exist now
    assert len(wiki.list_entries(conn, house_id)) == len(wiki.SETUP_ENTRIES)


def test_seed_setup_entries_skips_existing(conn):
    house_id, alice, _ = _house(conn)
    # Pre-set one entry that setup would add
    wiki.set_entry(conn, house_id, "alarm code", "my custom value", alice, "Access & Security")
    added, skipped = wiki.seed_setup_entries(conn, house_id, alice)
    assert skipped == 1
    assert added == len(wiki.SETUP_ENTRIES) - 1
    # Existing entry was not overwritten
    assert wiki.get_entry(conn, house_id, "alarm code")["value"] == "my custom value"


def test_wiki_state_save_and_get(conn):
    house_id, alice, _ = _house(conn)
    assert wiki.get_wiki_message_id(conn, house_id) is None
    wiki.save_wiki_message_id(conn, house_id, "111222333")
    assert wiki.get_wiki_message_id(conn, house_id) == "111222333"


def test_wiki_state_upserts(conn):
    house_id, alice, _ = _house(conn)
    wiki.save_wiki_message_id(conn, house_id, "aaa")
    wiki.save_wiki_message_id(conn, house_id, "bbb")
    assert wiki.get_wiki_message_id(conn, house_id) == "bbb"


def test_wiki_state_clear(conn):
    house_id, alice, _ = _house(conn)
    wiki.save_wiki_message_id(conn, house_id, "aaa")
    wiki.clear_wiki_message_id(conn, house_id)
    assert wiki.get_wiki_message_id(conn, house_id) is None


def test_entries_are_house_scoped(conn):
    house_id, alice, _ = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    wiki.set_entry(conn, other, "wifi password", "abc", other_alice)
    assert wiki.list_entries(conn, house_id) == []
