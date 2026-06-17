import database
from cogs import expenses


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    expenses.init_tables(conn)
    return house_id, alice, bob


# --- pure: net_between ---


def test_net_between_a_owes_b():
    net = {(1, 2): 500}
    assert expenses.net_between(net, 1, 2) == 500


def test_net_between_reverses_sign():
    net = {(1, 2): 500}
    assert expenses.net_between(net, 2, 1) == -500


def test_net_between_settled_is_zero():
    assert expenses.net_between({}, 1, 2) == 0


# --- pure: format_payment_confirmation ---


def test_confirmation_still_owes():
    msg = expenses.format_payment_confirmation("Bob", "Alice", 2000, 3000)
    assert "Bob" in msg and "Alice" in msg
    assert "$20.00" in msg and "still owes" in msg and "$30.00" in msg


def test_confirmation_settled():
    msg = expenses.format_payment_confirmation("Bob", "Alice", 5000, 0)
    assert "settled up" in msg


def test_confirmation_overpaid_flips_direction():
    msg = expenses.format_payment_confirmation("Bob", "Alice", 7000, -2000)
    assert "Alice now owes Bob $20.00" in msg


# --- integration: real settlement feeds the confirmation ---


def test_partial_payment_reports_remaining_debt(conn):
    house_id, alice, bob = _house(conn)
    # Alice fronts $100 split two ways -> Bob owes Alice $50.
    expenses.record_expense(conn, house_id, "Rent", 10000, alice, [alice, bob])
    # Bob pays Alice $30 back.
    expenses.record_settlement(conn, house_id, bob, alice, 3000)

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    net_after = expenses.net_between(net, bob, alice)
    assert net_after == 2000  # Bob still owes Alice $20
    msg = expenses.format_payment_confirmation("Bob", "Alice", 3000, net_after)
    assert "Bob still owes Alice $20.00" in msg


def test_full_payment_settles(conn):
    house_id, alice, bob = _house(conn)
    expenses.record_expense(conn, house_id, "Rent", 10000, alice, [alice, bob])
    expenses.record_settlement(conn, house_id, bob, alice, 5000)

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert expenses.net_between(net, bob, alice) == 0


# --- "settle in full": /pay with no amount uses the whole owed balance ---


def test_settle_in_full_amount_is_the_owed_balance(conn):
    """With no amount, /pay settles exactly what the payer currently owes."""
    house_id, alice, bob = _house(conn)
    # Alice fronts $100 split two ways -> Bob owes Alice $50.
    expenses.record_expense(conn, house_id, "Rent", 10000, alice, [alice, bob])

    net_before = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    # This is the amount the handler would settle when amount is omitted.
    owed = expenses.net_between(net_before, bob, alice)
    assert owed == 5000

    expenses.record_settlement(conn, house_id, bob, alice, owed)
    net_after = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert expenses.net_between(net_after, bob, alice) == 0  # fully settled


def test_settle_in_full_when_nothing_owed_is_nonpositive(conn):
    """When the payer owes nothing, the computed settle amount is <= 0 (handler rejects)."""
    house_id, alice, bob = _house(conn)
    # Bob fronts the expense, so Alice owes Bob — Bob owes Alice nothing.
    expenses.record_expense(conn, house_id, "Rent", 10000, bob, [alice, bob])

    net = expenses.compute_net_balances(
        expenses.get_debts(conn, house_id), expenses.get_payments(conn, house_id)
    )
    assert expenses.net_between(net, bob, alice) <= 0
