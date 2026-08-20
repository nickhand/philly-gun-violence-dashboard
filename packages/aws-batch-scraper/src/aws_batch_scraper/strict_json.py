"""Strict JSON decoding helpers for persisted trust-boundary objects."""

import json


def decode_strict_json_object(body: str | bytes, *, label: str) -> dict[str, object]:
    """Decode one JSON object while rejecting duplicate keys at every depth."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains non-standard JSON constant {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError(f"{label} contains duplicate JSON field {key!r}")
            decoded[key] = value
        return decoded

    try:
        decoded: object = json.loads(
            body,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be a JSON object")
    return decoded
