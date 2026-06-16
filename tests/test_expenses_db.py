import database
from cogs import expenses


def test_record_expense_creates_splits_for_all_members(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_expense(conn, house_id, "Pizza", 2000, m1, [m1, m2])

    debts = expenses.get_debts(conn, house_id)
    assert (m2, m1, 1000) in debts
    assert (m1, m1, 1000) in debts


def test_record_settlement_and_get_payments(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_settlement(conn, house_id, m2, m1, 1000)

    payments = expenses.get_payments(conn, house_id)
    assert payments == [(m2, m1, 1000)]


def test_get_debts_empty_when_no_expenses(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    expenses.init_tables(conn)
    assert expenses.get_debts(conn, house_id) == []


def test_get_payments_empty_when_no_settlements(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    expenses.init_tables(conn)
    assert expenses.get_payments(conn, house_id) == []


def test_record_expense_end_to_end_balance(conn):
    house_id = database.create_house(conn, "guild-1", "The Treehouse")
    m1 = database.add_member(conn, house_id, "user-1", "Alice")
    m2 = database.add_member(conn, house_id, "user-2", "Bob")
    expenses.init_tables(conn)

    expenses.record_expense(conn, house_id, "Pizza", 2000, m1, [m1, m2])

    debts = expenses.get_debts(conn, house_id)
    payments = expenses.get_payments(conn, house_id)
    net = expenses.compute_net_balances(debts, payments)
    assert net == {(m2, m1): 1000}
