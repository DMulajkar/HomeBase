from cogs import expenses


def test_split_amount_even():
    shares = expenses.split_amount(300, [1, 2, 3])
    assert shares == {1: 100, 2: 100, 3: 100}


def test_split_amount_with_remainder():
    shares = expenses.split_amount(100, [1, 2, 3])
    assert shares == {1: 34, 2: 33, 3: 33}
    assert sum(shares.values()) == 100


def test_split_amount_single_member():
    shares = expenses.split_amount(500, [1])
    assert shares == {1: 500}


def test_split_amount_remainder_distributed_in_order():
    shares = expenses.split_amount(101, [10, 20, 30])
    assert shares == {10: 34, 20: 34, 30: 33}
    assert sum(shares.values()) == 101
