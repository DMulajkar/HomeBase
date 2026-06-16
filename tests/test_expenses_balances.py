from cogs import expenses


def test_compute_net_balances_simple_debt():
    debts = [(2, 1, 3000)]  # member 2 owes member 1 $30.00
    net = expenses.compute_net_balances(debts, [])
    assert net == {(2, 1): 3000}


def test_compute_net_balances_settled_pair_omitted():
    debts = [(2, 1, 3000)]
    payments = [(2, 1, 3000)]
    net = expenses.compute_net_balances(debts, payments)
    assert net == {}


def test_compute_net_balances_overpayment_flips_direction():
    debts = [(2, 1, 1000)]
    payments = [(2, 1, 1500)]
    net = expenses.compute_net_balances(debts, payments)
    assert net == {(1, 2): 500}


def test_compute_net_balances_self_pair_ignored():
    debts = [(1, 1, 1000)]
    net = expenses.compute_net_balances(debts, [])
    assert net == {}


def test_compute_net_balances_multiple_expenses_net_correctly():
    debts = [(2, 1, 3000), (1, 2, 1000)]
    net = expenses.compute_net_balances(debts, [])
    assert net == {(2, 1): 2000}


def test_compute_net_balances_no_debts_or_payments_is_empty():
    assert expenses.compute_net_balances([], []) == {}
