import pytest
from cryptography.fernet import Fernet, InvalidToken

import database
from cogs import subscriptions


TEST_KEY = Fernet.generate_key()
TEST_FERNET = Fernet(TEST_KEY)


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    alice = database.add_member(conn, house_id, "u1", "Alice")
    subscriptions.init_tables(conn)
    return house_id, alice


# --- pure: encrypt / decrypt ---


def test_round_trip():
    token = subscriptions.encrypt_password(TEST_FERNET, "s3cr3t!")
    assert subscriptions.decrypt_password(TEST_FERNET, token) == "s3cr3t!"


def test_encrypt_produces_different_tokens():
    # Fernet includes a random IV; same plaintext ≠ same ciphertext.
    t1 = subscriptions.encrypt_password(TEST_FERNET, "pass")
    t2 = subscriptions.encrypt_password(TEST_FERNET, "pass")
    assert t1 != t2


def test_decrypt_wrong_key_raises():
    other = Fernet(Fernet.generate_key())
    token = subscriptions.encrypt_password(TEST_FERNET, "pass")
    with pytest.raises(InvalidToken):
        subscriptions.decrypt_password(other, token)


# --- pure: format_sub_list ---


def test_format_sub_list_empty():
    msg = subscriptions.format_sub_list([])
    assert "No subscriptions" in msg and "/sub-add" in msg


def test_format_sub_list_shows_name_and_email():
    msg = subscriptions.format_sub_list([("Netflix", "house@email.com"), ("Spotify", "house@email.com")])
    assert "Netflix" in msg and "Spotify" in msg
    assert "house@email.com" in msg
    assert "password" not in msg.lower()


# --- DB ---


def test_add_and_list(conn):
    house_id, _alice = _house(conn)
    token = subscriptions.encrypt_password(TEST_FERNET, "abc")
    subscriptions.add_subscription(conn, house_id, "Netflix", "h@e.com", token)
    rows = subscriptions.list_subscriptions(conn, house_id)
    assert len(rows) == 1 and rows[0]["name"] == "Netflix"


def test_add_duplicate_raises(conn):
    house_id, _alice = _house(conn)
    token = subscriptions.encrypt_password(TEST_FERNET, "abc")
    subscriptions.add_subscription(conn, house_id, "Netflix", "h@e.com", token)
    with pytest.raises(ValueError):
        subscriptions.add_subscription(conn, house_id, "Netflix", "other@e.com", token)


def test_get_subscription(conn):
    house_id, _alice = _house(conn)
    token = subscriptions.encrypt_password(TEST_FERNET, "pass123")
    subscriptions.add_subscription(conn, house_id, "Spotify", "h@e.com", token)
    sub = subscriptions.get_subscription(conn, house_id, "Spotify")
    assert sub is not None
    assert subscriptions.decrypt_password(TEST_FERNET, sub["password_token"]) == "pass123"


def test_remove_subscription(conn):
    house_id, _alice = _house(conn)
    token = subscriptions.encrypt_password(TEST_FERNET, "abc")
    subscriptions.add_subscription(conn, house_id, "Netflix", "h@e.com", token)
    assert subscriptions.remove_subscription(conn, house_id, "Netflix") is True
    assert subscriptions.remove_subscription(conn, house_id, "Netflix") is False


def test_update_subscription(conn):
    house_id, _alice = _house(conn)
    old_token = subscriptions.encrypt_password(TEST_FERNET, "old")
    subscriptions.add_subscription(conn, house_id, "Netflix", "old@e.com", old_token)

    new_token = subscriptions.encrypt_password(TEST_FERNET, "new")
    assert subscriptions.update_subscription(conn, house_id, "Netflix", "new@e.com", new_token)

    sub = subscriptions.get_subscription(conn, house_id, "Netflix")
    assert sub["email"] == "new@e.com"
    assert subscriptions.decrypt_password(TEST_FERNET, sub["password_token"]) == "new"


def test_update_nonexistent_returns_false(conn):
    house_id, _alice = _house(conn)
    assert subscriptions.update_subscription(conn, house_id, "Ghost", None, None) is False


def test_subs_are_house_scoped(conn):
    house_id, _alice = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    other_alice = database.add_member(conn, other, "u1", "Alice")
    token = subscriptions.encrypt_password(TEST_FERNET, "abc")
    subscriptions.add_subscription(conn, other, "Netflix", "h@e.com", token)
    assert subscriptions.list_subscriptions(conn, house_id) == []
