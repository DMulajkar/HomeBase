import pytest

import database
from cogs import settings


def _house(conn):
    house_id = database.create_house(conn, "g1", "House")
    settings.init_tables(conn)
    return house_id


# --- pure: validate_setting ---


def test_validate_reminder_hour_valid():
    assert settings.validate_setting("reminder_hour", "9") == "9"
    assert settings.validate_setting("reminder_hour", "0") == "0"
    assert settings.validate_setting("reminder_hour", "23") == "23"


def test_validate_reminder_hour_invalid():
    with pytest.raises(ValueError, match="Invalid value"):
        settings.validate_setting("reminder_hour", "24")


def test_validate_reminder_lead_days_valid():
    assert settings.validate_setting("reminder_lead_days", "3") == "3"
    assert settings.validate_setting("reminder_lead_days", "7") == "7"


def test_validate_reminder_lead_days_invalid():
    with pytest.raises(ValueError, match="Invalid value"):
        settings.validate_setting("reminder_lead_days", "0")
    with pytest.raises(ValueError, match="Invalid value"):
        settings.validate_setting("reminder_lead_days", "8")


def test_validate_summary_day_valid():
    assert settings.validate_setting("summary_day", "1") == "1"
    assert settings.validate_setting("summary_day", "28") == "28"


def test_validate_summary_day_invalid():
    with pytest.raises(ValueError, match="Invalid value"):
        settings.validate_setting("summary_day", "29")


def test_validate_toggle_on_off():
    assert settings.validate_setting("post.chores-reminder", "on") == "on"
    assert settings.validate_setting("post.chores-reminder", "off") == "off"
    assert settings.validate_setting("post.chores-reminder", "ON") == "on"


def test_validate_toggle_invalid():
    with pytest.raises(ValueError, match="Invalid value"):
        settings.validate_setting("post.chores-reminder", "yes")


def test_validate_unknown_key():
    with pytest.raises(ValueError, match="Unknown setting"):
        settings.validate_setting("not_a_key", "5")


# --- pure: format_settings ---


def test_format_settings_empty_shows_defaults():
    msg = settings.format_settings({})
    assert "reminder_hour" in msg
    assert "9" in msg
    assert "(default)" in msg


def test_format_settings_shows_overridden_value():
    msg = settings.format_settings({"reminder_hour": "12"})
    assert "12" in msg
    assert "(default)" not in msg.split("reminder_hour")[1].split("\n")[0]


def test_format_settings_shows_toggles():
    msg = settings.format_settings({})
    assert "post.chores-reminder" in msg
    assert "post.birthday-reminder" in msg


# --- DB ---


def test_get_setting_missing_returns_provided_default(conn):
    house_id = _house(conn)
    result = settings.get_setting(conn, house_id, "reminder_hour", "9")
    assert result == "9"


def test_get_setting_missing_uses_definition_default(conn):
    house_id = _house(conn)
    result = settings.get_setting(conn, house_id, "reminder_hour")
    assert result == "9"


def test_set_and_get_setting(conn):
    house_id = _house(conn)
    settings.set_setting(conn, house_id, "reminder_hour", "12")
    assert settings.get_setting(conn, house_id, "reminder_hour") == "12"


def test_set_setting_updates(conn):
    house_id = _house(conn)
    settings.set_setting(conn, house_id, "reminder_hour", "8")
    settings.set_setting(conn, house_id, "reminder_hour", "10")
    assert settings.get_setting(conn, house_id, "reminder_hour") == "10"


def test_get_all_settings_empty(conn):
    house_id = _house(conn)
    assert settings.get_all_settings(conn, house_id) == {}


def test_get_all_settings_returns_set_keys(conn):
    house_id = _house(conn)
    settings.set_setting(conn, house_id, "reminder_hour", "12")
    settings.set_setting(conn, house_id, "summary_day", "5")
    result = settings.get_all_settings(conn, house_id)
    assert result["reminder_hour"] == "12"
    assert result["summary_day"] == "5"


def test_settings_are_house_scoped(conn):
    house_id = _house(conn)
    other = database.create_house(conn, "g2", "Other")
    settings.set_setting(conn, other, "reminder_hour", "18")
    assert settings.get_setting(conn, house_id, "reminder_hour") == "9"


def test_get_setting_safe_without_init(conn):
    house_id = database.create_house(conn, "g1", "House")
    # Don't call init_tables — get_setting should handle it
    result = settings.get_setting(conn, house_id, "reminder_hour", "9")
    assert result == "9"
