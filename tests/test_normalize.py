import pytest

from vobeval.normalize import (
    number_to_words,
    parse_bool,
    parse_int,
    parse_money,
    parse_percent,
    parse_pos,
    values_equal,
    words_to_number,
)


@pytest.mark.parametrize("raw, expected", [
    ("$25", 25.0),
    ("25.00", 25.0),
    ("$25.00", 25.0),
    ("twenty-five dollars", 25.0),
    ("twenty five", 25.0),
    ("USD 1,500", 1500.0),
    ("$1,500.00", 1500.0),
    ("one thousand five hundred dollars", 1500.0),
    ("no charge", 0.0),
    ("$0", 0.0),
    (40, 40.0),
    ("n/a", None),
    (None, None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("20%", 20.0), ("20 percent", 20.0), ("0.2", 20.0), (0.2, 20.0), (20, 20.0), ("10", 10.0), ("", None),
])
def test_parse_percent(raw, expected):
    assert parse_percent(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Yes", True), ("PA required", True), ("Required", True), ("maybe", None), ("Not required", False),
    ("Not covered", False), ("Allowed", True), ("n/a", None), (False, False),
])
def test_parse_bool(raw, expected):
    if raw == "maybe":
        with pytest.raises(ValueError):
            parse_bool(raw)
    else:
        assert parse_bool(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("400 sessions/yr", 400), ("32", 32), ("None", None), ("twelve", 12), (24, 24),
])
def test_parse_int(raw, expected):
    assert parse_int(raw) == expected


def test_parse_pos_is_order_insensitive_and_zero_padded():
    assert parse_pos("12, 11, 2") == ["02", "11", "12"]
    assert parse_pos(["10", "11"]) == ["10", "11"]


@pytest.mark.parametrize("kind, a, b, equal", [
    ("money", "$25", "twenty-five dollars", True),
    ("money", "25.00", 25, True),
    ("money", "$25", "$30", False),
    ("money", None, None, True),
    ("money", None, 0, False),
    ("percent", "20%", 0.2, True),
    ("pos", "02, 11, 12", ["11", "12", "02"], True),
    ("pos", "10, 11, 12", ["02", "11", "12"], False),
    ("text", "Caregiver must be present.", "caregiver must be  present", True),
    ("money", "garbage", 25, False),
])
def test_values_equal(kind, a, b, equal):
    assert values_equal(kind, a, b) is equal


def test_number_words_roundtrip():
    for n in [0, 7, 15, 25, 40, 99, 100, 250, 1500, 8150]:
        assert words_to_number(number_to_words(n)) == n
