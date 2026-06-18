import database
from cogs import groceries


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    groceries.init_tables(conn)
    return house_id, alice, bob


# --- pure: group_by_category ---


def test_group_by_category_orders_by_catalog_then_name():
    items = [
        ("Cleaning Supplies", "Bleach"),
        ("Food", "Milk"),
        ("Food", "Apples"),
        ("Household Supplies", "Paper towels"),
    ]
    grouped = groceries.group_by_category(items)
    # Categories in CATEGORIES order; names alphabetical within a category.
    assert list(grouped.keys()) == ["Food", "Household Supplies", "Cleaning Supplies"]
    assert grouped["Food"] == ["Apples", "Milk"]
    assert grouped["Cleaning Supplies"] == ["Bleach"]


def test_group_by_category_empty():
    assert groceries.group_by_category([]) == {}


# --- pure: format_grocery_list ---


def test_format_grocery_list_empty_state():
    msg = groceries.format_grocery_list({})
    assert "empty" in msg.lower()
    assert "/grocery-add" in msg


def test_format_grocery_list_groups_with_headers():
    grouped = {"Food": ["Apples", "Milk"], "Cleaning Supplies": ["Bleach"]}
    msg = groceries.format_grocery_list(grouped)
    assert "🛒 **Grocery list**" in msg
    assert "**Food**" in msg and "- Apples" in msg and "- Milk" in msg
    assert "**Cleaning Supplies**" in msg and "- Bleach" in msg


# --- DB: add / list / bought / remove ---


def test_add_and_list_needed(conn):
    house_id, alice, _bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    groceries.add_item(conn, house_id, "Bleach", "Cleaning Supplies", alice)

    needed = groceries.list_needed(conn, house_id)
    names = [r["name"] for r in needed]
    assert names == ["Bleach", "Milk"]  # ordered by category, name


def test_add_duplicate_active_rejected(conn):
    house_id, alice, _bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    try:
        groceries.add_item(conn, house_id, "Milk", "Food", alice)
        assert False, "expected ValueError on duplicate active item"
    except ValueError as e:
        assert "already on the grocery list" in str(e)


def test_mark_bought_removes_from_needed_and_allows_readd(conn):
    house_id, alice, bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)

    assert groceries.mark_bought(conn, house_id, "Milk", bob) is True
    assert groceries.list_needed(conn, house_id) == []

    # The bought row is history; the same item can be needed again.
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    assert [r["name"] for r in groceries.list_needed(conn, house_id)] == ["Milk"]


def test_mark_bought_missing_returns_false(conn):
    house_id, _alice, bob = _house(conn)
    assert groceries.mark_bought(conn, house_id, "Ghost", bob) is False


def test_remove_item(conn):
    house_id, alice, _bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    assert groceries.remove_item(conn, house_id, "Milk") is True
    assert groceries.list_needed(conn, house_id) == []
    assert groceries.remove_item(conn, house_id, "Milk") is False  # already gone


# --- pure: format_trip_summary ---


def test_format_trip_summary_no_amount(conn):
    items = [("Food", "Milk"), ("Food", "Eggs"), ("Cleaning Supplies", "Bleach")]
    msg = groceries.format_trip_summary("Dhruv", items, None, 3)
    assert "Dhruv" in msg and "3 items" in msg
    assert "**Food**" in msg and "- Milk" in msg
    assert "**Cleaning Supplies**" in msg
    assert "Total" not in msg
    assert "cleared" in msg


def test_format_trip_summary_with_amount():
    msg = groceries.format_trip_summary("Sarah", [("Food", "Milk")], 6000, 3)
    assert "$60.00" in msg and "$20.00" in msg and "3 members" in msg


def test_format_trip_summary_single_item():
    msg = groceries.format_trip_summary("Ryan", [("Food", "Milk")], None, 2)
    assert "1 item" in msg and "items" not in msg.split("1 item")[0]


# --- DB: finish_shopping_run ---


def test_finish_shopping_run_clears_all_active(conn):
    house_id, alice, bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    groceries.add_item(conn, house_id, "Bleach", "Cleaning Supplies", alice)

    bought = groceries.finish_shopping_run(conn, house_id, bob)
    assert len(bought) == 2
    assert groceries.list_needed(conn, house_id) == []


def test_finish_shopping_run_empty_list_returns_empty(conn):
    house_id, alice, _bob = _house(conn)
    assert groceries.finish_shopping_run(conn, house_id, alice) == []


def test_finish_shopping_run_allows_readd(conn):
    house_id, alice, bob = _house(conn)
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    groceries.finish_shopping_run(conn, house_id, bob)
    # After the run, the same item can be added again.
    groceries.add_item(conn, house_id, "Milk", "Food", alice)
    assert [r["name"] for r in groceries.list_needed(conn, house_id)] == ["Milk"]


def test_items_are_house_scoped(conn):
    house_id, alice, _bob = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    groceries.add_item(conn, other, "Milk", "Food", other_alice)

    assert groceries.list_needed(conn, house_id) == []  # other house's item doesn't leak
    assert [r["name"] for r in groceries.list_needed(conn, other)] == ["Milk"]
