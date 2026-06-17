from datetime import date, datetime, timezone

import database
import scheduler


def _dt(year, month, day, hour):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def test_not_due_before_reminder_hour():
    assert scheduler.is_due(_dt(2026, 1, 1, 8), None, 9) is False


def test_due_after_hour_when_never_run():
    assert scheduler.is_due(_dt(2026, 1, 1, 9), None, 9) is True
    assert scheduler.is_due(_dt(2026, 1, 1, 23), None, 9) is True


def test_not_due_when_already_run_today():
    assert scheduler.is_due(_dt(2026, 1, 1, 10), date(2026, 1, 1), 9) is False


def test_due_on_a_new_day_after_hour():
    assert scheduler.is_due(_dt(2026, 1, 2, 9), date(2026, 1, 1), 9) is True


def test_not_due_on_new_day_before_hour():
    assert scheduler.is_due(_dt(2026, 1, 2, 8), date(2026, 1, 1), 9) is False


def test_last_run_roundtrip_and_upsert(conn):
    house_id = database.create_house(conn, "g1", "House")
    scheduler.init_tables(conn)

    assert scheduler.get_last_run_date(conn, house_id, "chores-reminder") is None

    scheduler.set_last_run(conn, house_id, "chores-reminder", date(2026, 1, 1))
    assert scheduler.get_last_run_date(conn, house_id, "chores-reminder") == date(2026, 1, 1)

    # second write for the same (house, job) overwrites, not duplicates
    scheduler.set_last_run(conn, house_id, "chores-reminder", date(2026, 1, 2))
    assert scheduler.get_last_run_date(conn, house_id, "chores-reminder") == date(2026, 1, 2)


def test_last_run_is_per_house_and_job(conn):
    h1 = database.create_house(conn, "g1", "H1")
    h2 = database.create_house(conn, "g2", "H2")
    scheduler.init_tables(conn)

    scheduler.set_last_run(conn, h1, "chores-reminder", date(2026, 1, 1))
    assert scheduler.get_last_run_date(conn, h2, "chores-reminder") is None
    assert scheduler.get_last_run_date(conn, h1, "other-job") is None
