from datetime import date

from cogs import finance


def test_due_date_normal_day():
    assert finance.due_date_for_month(2026, 6, 15) == date(2026, 6, 15)
    assert finance.due_date_for_month(2026, 6, 1) == date(2026, 6, 1)


def test_due_date_clamps_to_month_length():
    # February (non-leap) clamps 31 -> 28
    assert finance.due_date_for_month(2026, 2, 31) == date(2026, 2, 28)
    # February (leap) clamps 31 -> 29
    assert finance.due_date_for_month(2024, 2, 31) == date(2024, 2, 29)
    # 30-day month clamps 31 -> 30
    assert finance.due_date_for_month(2026, 4, 31) == date(2026, 4, 30)
    # 31-day month keeps 31
    assert finance.due_date_for_month(2026, 1, 31) == date(2026, 1, 31)


def test_period_key_format():
    assert finance.period_key(date(2026, 6, 17)) == "2026-06"
    assert finance.period_key(date(2026, 12, 1)) == "2026-12"


def test_fixed_bill_not_due_before_due_date():
    start = date(2026, 1, 1)
    assert finance.fixed_bill_period_to_post(date(2026, 6, 14), 15, start) is None


def test_fixed_bill_due_on_and_after_due_date():
    start = date(2026, 1, 1)
    assert finance.fixed_bill_period_to_post(date(2026, 6, 15), 15, start) == "2026-06"
    assert finance.fixed_bill_period_to_post(date(2026, 6, 20), 15, start) == "2026-06"


def test_fixed_bill_not_back_billed_before_start_date():
    # Bill created June 20; June's due date (the 1st) is before start -> skip June.
    start = date(2026, 6, 20)
    assert finance.fixed_bill_period_to_post(date(2026, 6, 25), 1, start) is None
    # July's due date (the 1st) is after start -> due.
    assert finance.fixed_bill_period_to_post(date(2026, 7, 1), 1, start) == "2026-07"


def test_fixed_bill_due_day_clamped_when_checking():
    # due_day 31 in a 30-day month resolves to the 30th.
    start = date(2026, 1, 1)
    assert finance.fixed_bill_period_to_post(date(2026, 4, 29), 31, start) is None
    assert finance.fixed_bill_period_to_post(date(2026, 4, 30), 31, start) == "2026-04"
