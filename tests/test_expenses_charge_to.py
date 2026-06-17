import database
from cogs import expenses


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    carol = database.add_member(conn, house_id, "u3", "Carol")
    expenses.init_tables(conn)
    return house_id, alice, bob, carol


# --- pure: a single-member split is the whole amount ---


def test_split_amount_single_member_gets_full():
    assert expenses.split_amount(3000, [42]) == {42: 3000}


# --- integration: charge an expense entirely to one member ---


def test_charge_entire_expense_to_one_member(conn):
    house_id, alice, bob, carol = _house(conn)
    # Alice paid $30, but it's entirely Bob's: only Bob is in the split.
    expenses.record_expense(conn, house_id, "Bob's ticket", 3000, alice, [bob])

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert expenses.net_between(net, bob, alice) == 3000  # Bob owes Alice the full $30
    assert expenses.net_between(net, carol, alice) == 0  # Carol is uninvolved


def test_directed_and_split_expenses_combine(conn):
    house_id, alice, bob, carol = _house(conn)
    # A normal 3-way split of $30 -> Bob and Carol each owe Alice $10.
    expenses.record_expense(conn, house_id, "Groceries", 3000, alice, [alice, bob, carol])
    # Plus a $5 item charged entirely to Bob.
    expenses.record_expense(conn, house_id, "Bob's snack", 500, alice, [bob])

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert expenses.net_between(net, bob, alice) == 1500  # $10 share + $5 directed
    assert expenses.net_between(net, carol, alice) == 1000  # share only
