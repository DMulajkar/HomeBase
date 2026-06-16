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


def test_get_debts_and_payments_are_scoped_to_house(conn):
    house_1 = database.create_house(conn, "guild-1", "House One")
    house_2 = database.create_house(conn, "guild-2", "House Two")
    h1_m1 = database.add_member(conn, house_1, "user-1", "Alice")
    h1_m2 = database.add_member(conn, house_1, "user-2", "Bob")
    h2_m1 = database.add_member(conn, house_2, "user-3", "Carol")
    h2_m2 = database.add_member(conn, house_2, "user-4", "Dave")
    expenses.init_tables(conn)

    expenses.record_expense(conn, house_1, "House 1 Pizza", 2000, h1_m1, [h1_m1, h1_m2])
    expenses.record_settlement(conn, house_1, h1_m2, h1_m1, 500)
    expenses.record_expense(conn, house_2, "House 2 Groceries", 4000, h2_m1, [h2_m1, h2_m2])
    expenses.record_settlement(conn, house_2, h2_m2, h2_m1, 1000)

    house_1_debts = expenses.get_debts(conn, house_1)
    house_2_debts = expenses.get_debts(conn, house_2)
    house_1_payments = expenses.get_payments(conn, house_1)
    house_2_payments = expenses.get_payments(conn, house_2)

    assert all(member_id in (h1_m1, h1_m2) for ower, payer, _ in house_1_debts for member_id in (ower, payer))
    assert all(member_id in (h2_m1, h2_m2) for ower, payer, _ in house_2_debts for member_id in (ower, payer))
    assert house_1_payments == [(h1_m2, h1_m1, 500)]
    assert house_2_payments == [(h2_m2, h2_m1, 1000)]
