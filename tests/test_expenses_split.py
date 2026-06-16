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


def test_dollars_to_cents_exact():
    assert expenses.dollars_to_cents(42.50) == 4250


def test_dollars_to_cents_avoids_float_rounding_error():
    # 2.675 * 100 == 267.49999999999997 in binary float; round() on that
    # truncates to 267 instead of 268. Decimal-based conversion must not.
    assert expenses.dollars_to_cents(2.675) == 268


def test_dollars_to_cents_whole_dollar():
    assert expenses.dollars_to_cents(10.0) == 1000
