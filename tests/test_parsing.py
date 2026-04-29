from decimal import Decimal

import pytest

from slf_trace.parsing import ParserConfig, PayloadParseError, parse_measurement_payload


def _config() -> ParserConfig:
    return ParserConfig(
        measurement_types={"aussenring", "innenring", "breite", "ueberstand"},
        default_unit="mm",
    )


def test_parse_semicolon_key_value_payload() -> None:
    values = parse_measurement_payload(
        "aussenring=1.1;innenring=2.2;breite=3.3;ueberstand=4.4",
        _config(),
    )

    assert [(value.measurement_type, value.value) for value in values] == [
        ("aussenring", Decimal("1.1")),
        ("innenring", Decimal("2.2")),
        ("breite", Decimal("3.3")),
        ("ueberstand", Decimal("4.4")),
    ]


def test_parse_decimal_comma_payload() -> None:
    values = parse_measurement_payload("breite=7,7", _config())

    assert values[0].measurement_type == "breite"
    assert values[0].value == Decimal("7.7")


def test_parse_csv_payload() -> None:
    values = parse_measurement_payload("breite,ueberstand\n3.3,4.4", _config())

    assert [(value.measurement_type, value.value) for value in values] == [
        ("breite", Decimal("3.3")),
        ("ueberstand", Decimal("4.4")),
    ]


def test_parse_rejects_unknown_measurement_type() -> None:
    with pytest.raises(PayloadParseError, match="Unsupported measurement types"):
        parse_measurement_payload("typo=1.0", _config())


def test_parse_rejects_invalid_decimal() -> None:
    with pytest.raises(PayloadParseError, match="Invalid decimal"):
        parse_measurement_payload("breite=abc", _config())
