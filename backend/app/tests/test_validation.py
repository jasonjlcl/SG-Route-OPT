import pandas as pd
import pytest

from app.services.validation import validate_rows
from app.utils.errors import AppError


def test_validation_missing_required_columns():
    df = pd.DataFrame({"address": ["1 Test Road"]})
    with pytest.raises(AppError):
        validate_rows(df)


def test_validation_invalid_time_window():
    df = pd.DataFrame(
        {
            "stop_ref": ["S1"],
            "address": ["1 Test Road"],
            "tw_start": ["14:00"],
            "tw_end": ["10:00"],
        }
    )
    result = validate_rows(df)
    assert result.valid_rows_count == 0
    assert result.invalid_rows_count == 1
    assert "tw_start must be earlier than tw_end" in result.invalid_rows[0].reason


def test_validation_partial_valid_rows():
    df = pd.DataFrame(
        {
            "stop_ref": ["S1", "S2"],
            "address": ["1 Test Road", ""],
            "postal_code": ["", ""],
            "demand": [1, 2],
        }
    )
    result = validate_rows(df)
    assert result.valid_rows_count == 1
    assert result.invalid_rows_count == 1
    assert result.valid_rows[0]["stop_ref"] == "S1"
