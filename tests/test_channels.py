from cogs import channels

EXPECTED_NAMES = {
    "chores",
    "rent-and-utilities",
    "groceries",
    "wiki",
    "general",
    "food",
    "memories",
    "bot-commands",
    "welcome",
}


def test_catalog_has_expected_channels():
    names = {s.name for s in channels.CHANNEL_CATALOG}
    assert names == EXPECTED_NAMES


def test_catalog_has_exactly_one_welcome():
    welcome = [s for s in channels.CHANNEL_CATALOG if s.welcome]
    assert len(welcome) == 1
    assert welcome[0].name == "welcome"


def test_channel_names_are_valid_discord_form():
    for s in channels.CHANNEL_CATALOG:
        assert s.name == s.name.lower()
        assert " " not in s.name
        assert s.topic  # every channel has a non-empty topic


def test_every_channel_has_a_short_picker_description():
    for s in channels.CHANNEL_CATALOG:
        assert s.description  # shown in the select menu
        assert len(s.description) <= 100  # Discord SelectOption description limit


def _embed_text(embed):
    parts = [embed.title or "", embed.description or ""]
    for field in embed.fields:
        parts.append(field.name or "")
        parts.append(field.value or "")
    return " ".join(parts)


def test_welcome_message_includes_house_name_and_commands():
    text = _embed_text(channels.build_welcome_message("The Treehouse"))
    assert "The Treehouse" in text
    assert "/join-house" in text
    for cmd in ("/expense", "/pay", "/balances"):
        assert cmd in text


def test_welcome_message_has_rules_section():
    text = _embed_text(channels.build_welcome_message("The Treehouse")).lower()
    assert "rules" in text
