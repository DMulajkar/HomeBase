from datetime import date

import pytest

from cogs import chores


def test_daily_period_index():
    start = date(2026, 1, 1)
    assert chores.current_period_index("daily", start, date(2026, 1, 1)) == 0
    assert chores.current_period_index("daily", start, date(2026, 1, 2)) == 1
    assert chores.current_period_index("daily", start, date(2026, 1, 11)) == 10


def test_weekly_period_index():
    start = date(2026, 1, 1)
    assert chores.current_period_index("weekly", start, date(2026, 1, 7)) == 0
    assert chores.current_period_index("weekly", start, date(2026, 1, 8)) == 1
    assert chores.current_period_index("weekly", start, date(2026, 1, 15)) == 2


def test_monthly_period_index():
    start = date(2026, 1, 15)
    assert chores.current_period_index("monthly", start, date(2026, 1, 31)) == 0
    assert chores.current_period_index("monthly", start, date(2026, 2, 1)) == 1
    assert chores.current_period_index("monthly", start, date(2027, 3, 1)) == 14


def test_period_index_before_start_clamps_to_zero():
    start = date(2026, 1, 10)
    assert chores.current_period_index("daily", start, date(2026, 1, 1)) == 0
    assert chores.current_period_index("monthly", start, date(2025, 12, 1)) == 0


def test_unknown_cadence_raises():
    with pytest.raises(ValueError):
        chores.current_period_index("hourly", date(2026, 1, 1), date(2026, 1, 2))


def test_assignee_rotation_wraps():
    members = [10, 20, 30]
    assert chores.assignee_for_period(members, 0) == 10
    assert chores.assignee_for_period(members, 1) == 20
    assert chores.assignee_for_period(members, 2) == 30
    assert chores.assignee_for_period(members, 3) == 10
    assert chores.assignee_for_period(members, 7) == 20


def test_assignee_with_no_members_is_none():
    assert chores.assignee_for_period([], 5) is None


def test_period_end_date_daily():
    start = date(2026, 1, 1)
    assert chores.period_end_date("daily", start, 0) == date(2026, 1, 1)
    assert chores.period_end_date("daily", start, 5) == date(2026, 1, 6)


def test_period_end_date_weekly():
    start = date(2026, 1, 1)
    assert chores.period_end_date("weekly", start, 0) == date(2026, 1, 7)
    assert chores.period_end_date("weekly", start, 1) == date(2026, 1, 14)


def test_period_end_date_monthly():
    start = date(2026, 1, 15)
    assert chores.period_end_date("monthly", start, 0) == date(2026, 1, 31)
    assert chores.period_end_date("monthly", start, 1) == date(2026, 2, 28)
    # crossing a year boundary
    assert chores.period_end_date("monthly", start, 11) == date(2026, 12, 31)
