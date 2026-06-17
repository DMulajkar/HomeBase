from datetime import date

import database
from cogs import chores


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    sarah = database.add_member(conn, house_id, "u1", "Sarah")
    dhruv = database.add_member(conn, house_id, "u2", "Dhruv")
    ryan = database.add_member(conn, house_id, "u3", "Ryan")
    chores.init_tables(conn)
    return house_id, sarah, dhruv, ryan


def _complete_at(conn, chore_id, period_index, member_id, when_iso):
    """Insert a completion with an explicit completed_at so month filters bite."""
    conn.execute(
        "INSERT INTO chore_completions (chore_id, period_index, member_id, completed_at) "
        "VALUES (?, ?, ?, ?)",
        (chore_id, period_index, member_id, when_iso),
    )
    conn.commit()


# --- pure: previous_month / is_rankings_day ---


def test_previous_month_wraps_january():
    assert chores.previous_month(date(2026, 1, 15)) == (2025, 12)


def test_previous_month_normal():
    assert chores.previous_month(date(2026, 7, 1)) == (2026, 6)


def test_is_rankings_day():
    assert chores.is_rankings_day(date(2026, 7, 1), 1)
    assert not chores.is_rankings_day(date(2026, 7, 2), 1)


# --- pure: rank_members ---


def test_rank_members_orders_and_drops_zeros():
    counts = [(1, "Sarah", 7), (2, "Dhruv", 5), (3, "Ryan", 0)]
    assert chores.rank_members(counts) == [(1, "Sarah", 7), (2, "Dhruv", 5)]


def test_rank_members_competition_ties():
    counts = [(1, "Sarah", 5), (2, "Dhruv", 5), (3, "Ryan", 2)]
    # Two tied at the top share rank 1; the next is rank 3 (not 2).
    assert chores.rank_members(counts) == [(1, "Sarah", 5), (1, "Dhruv", 5), (3, "Ryan", 2)]


def test_rank_members_all_zero_is_empty():
    assert chores.rank_members([(1, "Sarah", 0), (2, "Dhruv", 0)]) == []


# --- pure: monthly_streak ---


def test_monthly_streak_counts_consecutive():
    months = {"2026-04", "2026-05", "2026-06"}
    assert chores.monthly_streak(months, 2026, 6) == 3


def test_monthly_streak_breaks_on_gap():
    months = {"2026-03", "2026-05", "2026-06"}
    assert chores.monthly_streak(months, 2026, 6) == 2  # June, May, then March is a gap


def test_monthly_streak_wraps_year():
    months = {"2025-12", "2026-01"}
    assert chores.monthly_streak(months, 2026, 1) == 2


def test_monthly_streak_zero_when_end_absent():
    assert chores.monthly_streak({"2026-04"}, 2026, 6) == 0


# --- pure: format_rankings ---


def test_format_rankings_medals_and_streaks():
    ranked = [(1, "Sarah", 7), (2, "Dhruv", 5), (3, "Ryan", 3)]
    streaks = [("Sarah", 3), ("Dhruv", 2)]
    msg = chores.format_rankings("June 2026", ranked, streaks)
    assert "🏆 **June 2026 Rankings**" in msg
    assert "🥇 Sarah — 7" in msg
    assert "🥈 Dhruv — 5" in msg
    assert "🥉 Ryan — 3" in msg
    assert "🔥 **Streaks**: Sarah (3 months), Dhruv (2 months)" in msg


def test_format_rankings_no_streak_section_when_empty():
    msg = chores.format_rankings("June 2026", [(1, "Sarah", 1)], [])
    assert "Streaks" not in msg


# --- integration: render_rankings ---


def test_render_rankings_off_day_is_none(conn):
    house_id, sarah, *_ = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())
    _complete_at(conn, cid, 0, sarah, "2026-06-10T12:00:00+00:00")
    assert chores.render_rankings(conn, house_id, date(2026, 7, 2)) is None


def test_render_rankings_summarizes_previous_month(conn):
    house_id, sarah, dhruv, ryan = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())
    # June: Sarah x2, Dhruv x1. A July completion must NOT count toward June.
    _complete_at(conn, cid, 0, sarah, "2026-06-05T12:00:00+00:00")
    _complete_at(conn, cid, 1, sarah, "2026-06-06T12:00:00+00:00")
    _complete_at(conn, cid, 2, dhruv, "2026-06-07T12:00:00+00:00")
    _complete_at(conn, cid, 3, ryan, "2026-07-01T12:00:00+00:00")

    msg = chores.render_rankings(conn, house_id, date(2026, 7, 1))
    assert msg is not None
    assert "🏆 **June 2026 Rankings**" in msg
    assert "🥇 Sarah — 2" in msg
    assert "🥈 Dhruv — 1" in msg
    assert "Ryan" not in msg  # Ryan only completed in July


def test_render_rankings_none_when_month_empty(conn):
    house_id, sarah, *_ = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 6, 1).isoformat())
    _complete_at(conn, cid, 0, sarah, "2026-07-04T12:00:00+00:00")  # only July activity
    # Summarizing June (posting July 1) finds nothing.
    assert chores.render_rankings(conn, house_id, date(2026, 7, 1)) is None


def test_render_rankings_includes_streak(conn):
    house_id, sarah, *_ = _house(conn)
    cid = chores.add_chore(conn, house_id, "Dishes", "daily", date(2026, 5, 1).isoformat())
    # Sarah completed in May and June -> a 2-month streak ending at June.
    _complete_at(conn, cid, 0, sarah, "2026-05-10T12:00:00+00:00")
    _complete_at(conn, cid, 1, sarah, "2026-06-10T12:00:00+00:00")

    msg = chores.render_rankings(conn, house_id, date(2026, 7, 1))
    assert "🔥 **Streaks**: Sarah (2 months)" in msg
