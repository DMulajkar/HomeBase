from datetime import date

import database
from cogs import chores, groceries, leaderboard


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    sarah = database.add_member(conn, house_id, "u1", "Sarah")
    dhruv = database.add_member(conn, house_id, "u2", "Dhruv")
    ryan = database.add_member(conn, house_id, "u3", "Ryan")
    chores.init_tables(conn)
    groceries.init_tables(conn)
    return house_id, sarah, dhruv, ryan


def _chore_at(conn, chore_id, period_index, member_id, when_iso):
    conn.execute(
        "INSERT INTO chore_completions (chore_id, period_index, member_id, completed_at) "
        "VALUES (?, ?, ?, ?)",
        (chore_id, period_index, member_id, when_iso),
    )
    conn.commit()


def _run(conn, house_id, member_id, amount_cents, run_at_iso):
    conn.execute(
        "INSERT INTO grocery_runs (house_id, member_id, amount_cents, expense_id, run_at) "
        "VALUES (?, ?, ?, NULL, ?)",
        (house_id, member_id, amount_cents, run_at_iso),
    )
    conn.commit()


# --- pure: compute_scores ---


def test_compute_scores_chores_and_runs():
    # Sarah: 3 chores (3 pts) + 1 run (2 pts) = 5
    # Dhruv: 2 chores (2 pts) = 2
    # Ryan: 0 — excluded
    chore_counts = [(1, "Sarah", 3), (2, "Dhruv", 2), (3, "Ryan", 0)]
    run_counts = {1: 1}
    ranked = leaderboard.compute_scores(chore_counts, run_counts)
    assert ranked == [(1, "Sarah", 5), (2, "Dhruv", 2)]


def test_compute_scores_tie_shares_rank():
    chore_counts = [(1, "Sarah", 2), (2, "Dhruv", 2), (3, "Ryan", 1)]
    ranked = leaderboard.compute_scores(chore_counts, {})
    assert ranked[0] == (1, "Sarah", 2)
    assert ranked[1] == (1, "Dhruv", 2)
    assert ranked[2] == (3, "Ryan", 1)


def test_compute_scores_all_zero_is_empty():
    assert leaderboard.compute_scores([(1, "Sarah", 0)], {}) == []


def test_compute_scores_grocery_run_only():
    # Member with runs but no chores still scores.
    chore_counts = [(1, "Sarah", 0), (2, "Dhruv", 0)]
    run_counts = {2: 1}
    ranked = leaderboard.compute_scores(chore_counts, run_counts)
    assert ranked == [(1, "Dhruv", 2)]


# --- pure: format_leaderboard ---


def test_format_leaderboard_medals_and_points():
    ranked = [(1, "Sarah", 5), (2, "Dhruv", 2), (3, "Ryan", 1)]
    msg = leaderboard.format_leaderboard("June 2026", ranked)
    assert "🏆 **June 2026 Rankings**" in msg
    assert "🥇 Sarah — 5 pts" in msg
    assert "🥈 Dhruv — 2 pts" in msg
    assert "🥉 Ryan — 1 pts" in msg
    assert "pt per chore" in msg


def test_format_leaderboard_empty():
    msg = leaderboard.format_leaderboard("June 2026", [])
    assert "No contributions" in msg


# --- DB: grocery_run_counts_for_month ---


def test_grocery_run_counts_for_month(conn):
    house_id, sarah, dhruv, _ryan = _house(conn)
    _run(conn, house_id, sarah, 5000, "2026-06-05T12:00:00+00:00")
    _run(conn, house_id, sarah, 3000, "2026-06-20T12:00:00+00:00")
    _run(conn, house_id, dhruv, 4000, "2026-06-15T12:00:00+00:00")
    _run(conn, house_id, sarah, 2000, "2026-07-01T12:00:00+00:00")  # excluded

    counts = leaderboard.grocery_run_counts_for_month(conn, house_id, 2026, 6)
    assert counts[sarah] == 2
    assert counts[dhruv] == 1
    assert len(counts) == 2


# --- integration: render_monthly_leaderboard ---


def test_render_monthly_leaderboard_off_day_is_none(conn):
    house_id, sarah, *_ = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())
    _chore_at(conn, cid, 0, sarah, "2026-06-05T12:00:00+00:00")
    assert leaderboard.render_monthly_leaderboard(conn, house_id, date(2026, 7, 2)) is None


def test_render_monthly_leaderboard_combines_chores_and_runs(conn):
    house_id, sarah, dhruv, ryan = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())

    # June: Sarah 2 chores + 1 run = 4pts; Dhruv 1 chore = 1pt; Ryan nothing
    _chore_at(conn, cid, 0, sarah, "2026-06-05T12:00:00+00:00")
    _chore_at(conn, cid, 1, sarah, "2026-06-10T12:00:00+00:00")
    _chore_at(conn, cid, 2, dhruv, "2026-06-15T12:00:00+00:00")
    _run(conn, house_id, sarah, 5000, "2026-06-20T12:00:00+00:00")

    msg = leaderboard.render_monthly_leaderboard(conn, house_id, date(2026, 7, 1))
    assert msg is not None
    assert "June 2026" in msg
    assert "🥇 Sarah — 4 pts" in msg
    assert "🥈 Dhruv — 1 pts" in msg
    assert "Ryan" not in msg


def test_render_monthly_leaderboard_none_when_no_activity(conn):
    house_id, *_ = _house(conn)
    assert leaderboard.render_monthly_leaderboard(conn, house_id, date(2026, 7, 1)) is None
