"""Tests for shooting-record domain model invariants."""

import pytest

from dashboard_utils.models.shootings import ShootingVictimsSchema


def _valid_record() -> dict[str, object]:
    return {
        "dc_key": "202612345678",
        "race": "B",
        "sex": "M",
        "fatal": False,
        "date": "2026-08-01 12:30:00",
        "age_group": "18 to 30",
        "has_court_case": None,
        "age": 25,
        "street_name": None,
        "block_number": None,
        "zip_code": None,
        "council_district": None,
        "police_district": None,
        "neighborhood": None,
        "school_name": None,
        "house_district": None,
        "senate_district": None,
        "segment_id": None,
    }


@pytest.mark.parametrize("value", [None, float("nan"), 123, "", "   ", "123.0"])
def test_dc_key_rejects_invalid_or_ambiguous_values(value: object) -> None:
    """Incident IDs must never be inferred from missing or numeric values."""
    with pytest.raises(ValueError):
        ShootingVictimsSchema.verify_dc_key(value)


def test_dc_key_normalizes_surrounding_whitespace() -> None:
    """Benign surrounding whitespace is removed at the model boundary."""
    assert ShootingVictimsSchema.verify_dc_key("  202612345678  ") == "202612345678"


def test_model_normalizes_dc_key_surrounding_whitespace() -> None:
    record = _valid_record()
    record["dc_key"] = "  202612345678  "

    assert ShootingVictimsSchema.model_validate(record).dc_key == "202612345678"


def test_unknown_fields_are_rejected() -> None:
    record = _valid_record()
    record["unexpected"] = "schema drift"

    with pytest.raises(ValueError, match="extra_forbidden"):
        ShootingVictimsSchema.model_validate(record)


@pytest.mark.parametrize(
    ("field", "value"),
    [("fatal", 0), ("fatal", "false"), ("age", "25"), ("block_number", "1200")],
)
def test_model_rejects_coercive_values(field: str, value: object) -> None:
    record = _valid_record()
    record[field] = value

    with pytest.raises(ValueError):
        ShootingVictimsSchema.model_validate(record)


@pytest.mark.parametrize("value", [True, False, None])
def test_court_search_result_preserves_three_states(value: bool | None) -> None:
    """The domain model must distinguish explicit no-results from unknown."""
    record = _valid_record()
    record["has_court_case"] = value

    assert ShootingVictimsSchema.model_validate(record).has_court_case is value


@pytest.mark.parametrize("value", [0, 1, "0", "1", "false", "true"])
def test_court_search_result_rejects_coercive_values(value: object) -> None:
    """Wire and dataframe inputs must use a real boolean or null."""
    record = _valid_record()
    record["has_court_case"] = value

    with pytest.raises(ValueError):
        ShootingVictimsSchema.model_validate(record)
