import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO


class PayloadParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedMeasurementValue:
    measurement_type: str
    value: Decimal
    unit: str | None = None


@dataclass(frozen=True)
class ParserConfig:
    measurement_types: set[str]
    default_unit: str | None = "mm"
    decimal_comma: bool = True


def parse_measurement_payload(
    content: str,
    config: ParserConfig,
) -> list[ParsedMeasurementValue]:
    normalized_content = content.strip()
    if not normalized_content:
        raise PayloadParseError("Payload is empty.")

    pairs = _parse_key_value_payload(normalized_content)
    if not pairs:
        pairs = _parse_csv_payload(normalized_content)

    values = []
    unknown_types = sorted(set(pairs) - config.measurement_types)
    if unknown_types:
        raise PayloadParseError(f"Unsupported measurement types: {', '.join(unknown_types)}.")

    for measurement_type, raw_value in pairs.items():
        values.append(
            ParsedMeasurementValue(
                measurement_type=measurement_type,
                value=_parse_decimal(raw_value, decimal_comma=config.decimal_comma),
                unit=config.default_unit,
            )
        )

    if not values:
        raise PayloadParseError("Payload did not contain measurement values.")

    return values


def _parse_key_value_payload(content: str) -> dict[str, str]:
    separators = [";", "\n"]
    tokens = [content]
    for separator in separators:
        if separator in content:
            tokens = [token for token in content.replace("\n", separator).split(separator)]
            break

    pairs = {}
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
        elif ":" in token:
            key, value = token.split(":", 1)
        else:
            return {}
        key = key.strip()
        value = value.strip()
        if key and value:
            pairs[key] = value
    return pairs


def _parse_csv_payload(content: str) -> dict[str, str]:
    stream = StringIO(content)
    try:
        rows = list(csv.DictReader(stream))
    except csv.Error as exc:
        raise PayloadParseError(str(exc)) from exc

    if len(rows) != 1:
        return {}

    return {
        key.strip(): str(value).strip()
        for key, value in rows[0].items()
        if key and value is not None and str(value).strip()
    }


def _parse_decimal(raw_value: str, *, decimal_comma: bool) -> Decimal:
    value = raw_value.strip()
    if decimal_comma:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PayloadParseError(f"Invalid decimal value: {raw_value!r}.") from exc
