import database
from cogs import meals


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    bob = database.add_member(conn, house_id, "u2", "Bob")
    carol = database.add_member(conn, house_id, "u3", "Carol")
    meals.init_tables(conn)
    return house_id, alice, bob, carol


# --- pure: tally_votes ---


def test_tally_votes_sorts_by_count_desc():
    assert meals.tally_votes([("Tacos", 1), ("Pizza", 3), ("Pasta", 2)]) == [
        ("Pizza", 3), ("Pasta", 2), ("Tacos", 1)
    ]


def test_tally_votes_stable_tie_by_name():
    result = meals.tally_votes([("Tacos", 2), ("Pizza", 2)])
    assert result == [("Pizza", 2), ("Tacos", 2)]


# --- pure: format_poll_results ---


def test_format_poll_results_open():
    msg = meals.format_poll_results([("Pizza", 2), ("Tacos", 1)])
    assert "current standings" in msg
    assert "Pizza" in msg and "2 votes" in msg


def test_format_poll_results_closed():
    msg = meals.format_poll_results([("Pizza", 3)], closed=True)
    assert "final results" in msg


def test_format_poll_results_empty():
    msg = meals.format_poll_results([])
    assert "No meals" in msg


# --- pure: format_winner ---


def test_format_winner_includes_name_and_pct():
    msg = meals.format_winner("Pizza", 3, 4)
    assert "Pizza" in msg and "3/4" in msg and "75%" in msg
    assert "grocery list" in msg


# --- DB: poll lifecycle ---


def test_create_and_get_open_poll(conn):
    house_id, alice, *_ = _house(conn)
    assert meals.get_open_poll(conn, house_id) is None
    poll_id = meals.create_poll(conn, house_id, alice)
    poll = meals.get_open_poll(conn, house_id)
    assert poll is not None and poll["poll_id"] == poll_id


def test_add_option_and_get_option(conn):
    house_id, alice, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    meals.add_option(conn, poll_id, "Tacos", alice)
    opt = meals.get_option(conn, poll_id, "Tacos")
    assert opt is not None and opt["name"] == "Tacos"


def test_add_duplicate_option_raises(conn):
    house_id, alice, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    meals.add_option(conn, poll_id, "Tacos", alice)
    try:
        meals.add_option(conn, poll_id, "Tacos", alice)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_vote_and_get_vote(conn):
    house_id, alice, bob, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    opt_id = meals.add_option(conn, poll_id, "Pizza", alice)
    meals.record_vote(conn, poll_id, bob, opt_id)
    vote = meals.get_vote(conn, poll_id, bob)
    assert vote is not None and vote["name"] == "Pizza"


def test_vote_can_be_changed(conn):
    house_id, alice, bob, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    opt1 = meals.add_option(conn, poll_id, "Pizza", alice)
    opt2 = meals.add_option(conn, poll_id, "Tacos", alice)
    meals.record_vote(conn, poll_id, bob, opt1)
    meals.record_vote(conn, poll_id, bob, opt2)  # change
    assert meals.get_vote(conn, poll_id, bob)["name"] == "Tacos"


def test_poll_results_counts_correctly(conn):
    house_id, alice, bob, carol = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    opt_pizza = meals.add_option(conn, poll_id, "Pizza", alice)
    opt_tacos = meals.add_option(conn, poll_id, "Tacos", alice)
    meals.record_vote(conn, poll_id, alice, opt_pizza)
    meals.record_vote(conn, poll_id, bob, opt_pizza)
    meals.record_vote(conn, poll_id, carol, opt_tacos)
    results = meals.poll_results(conn, poll_id)
    assert results[0] == ("Pizza", 2)
    assert results[1] == ("Tacos", 1)


def test_get_winner_option_id(conn):
    house_id, alice, bob, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    opt1 = meals.add_option(conn, poll_id, "Pizza", alice)
    opt2 = meals.add_option(conn, poll_id, "Tacos", alice)
    meals.record_vote(conn, poll_id, alice, opt1)
    meals.record_vote(conn, poll_id, bob, opt2)
    # opt1 was proposed first, so it wins in a tie — but here pizza has same votes
    # Give pizza one more vote to make it unambiguous.
    carol = database.add_member(conn, house_id, "u4", "Carol")
    meals.record_vote(conn, poll_id, carol, opt1)
    assert meals.get_winner_option_id(conn, poll_id) == opt1


def test_get_winner_none_when_no_votes(conn):
    house_id, alice, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    meals.add_option(conn, poll_id, "Pizza", alice)
    assert meals.get_winner_option_id(conn, poll_id) is None


def test_close_poll(conn):
    house_id, alice, bob, *_ = _house(conn)
    poll_id = meals.create_poll(conn, house_id, alice)
    opt = meals.add_option(conn, poll_id, "Pizza", alice)
    meals.record_vote(conn, poll_id, bob, opt)
    winner_id = meals.get_winner_option_id(conn, poll_id)
    meals.close_poll(conn, poll_id, winner_id)
    assert meals.get_open_poll(conn, house_id) is None  # no open poll after close


def test_polls_are_house_scoped(conn):
    house_id, alice, *_ = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    meals.create_poll(conn, other, other_alice)
    assert meals.get_open_poll(conn, house_id) is None
