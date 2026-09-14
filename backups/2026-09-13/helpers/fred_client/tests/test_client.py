"""Unit tests for FredClient parsing, alignment, and configuration."""
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from fred_client import FredClient
from fred_client.utils import clean_and_align


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_OBSERVATIONS = {
    "observations": [
        {"date": "2023-01-01", "value": "26.0"},
        {"date": "2023-02-01", "value": "26.5"},
        {"date": "2023-03-01", "value": "."},   # FRED uses "." for missing
        {"date": "2023-04-01", "value": "27.1"},
    ]
}

_FAKE_CATEGORIES = {
    "categories": [
        {"id": 1, "name": "Production & Business Activity", "parent_id": 0},
        {"id": 2, "name": "Population, Employment, & Labor Markets", "parent_id": 0},
    ]
}


def _mock_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.from_cache = False
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key-123")
    return FredClient()


# ---------------------------------------------------------------------------
# FredClient instantiation
# ---------------------------------------------------------------------------

def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="FRED API key"):
        FredClient()


def test_accepts_explicit_key():
    client = FredClient(api_key="explicit-key")
    assert client._api_key == "explicit-key"


# ---------------------------------------------------------------------------
# get_series
# ---------------------------------------------------------------------------

def test_get_series_returns_dataframe(client):
    with patch.object(client._session, "get", return_value=_mock_response(_FAKE_OBSERVATIONS)):
        df = client.get_series("GDP", freq="MS")

    assert isinstance(df, pd.DataFrame)
    assert "GDP" in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)


def test_get_series_numeric_dtype(client):
    with patch.object(client._session, "get", return_value=_mock_response(_FAKE_OBSERVATIONS)):
        df = client.get_series("GDP", freq="MS")

    assert pd.api.types.is_float_dtype(df["GDP"])


def test_get_series_missing_value_coerced_to_nan(client):
    with patch.object(client._session, "get", return_value=_mock_response(_FAKE_OBSERVATIONS)):
        df = client.get_series("GDP", freq="MS")

    # "." (FRED missing sentinel) should become NaN, not raise
    assert df["GDP"].isna().any()


def test_get_series_frequency_alignment(client):
    with patch.object(client._session, "get", return_value=_mock_response(_FAKE_OBSERVATIONS)):
        df = client.get_series("GDP", freq="QS")

    # 4 monthly obs → 2 quarters
    assert len(df) == 2


# ---------------------------------------------------------------------------
# get_categories
# ---------------------------------------------------------------------------

def test_get_categories_returns_dataframe(client):
    with patch.object(client._session, "get", return_value=_mock_response(_FAKE_CATEGORIES)):
        df = client.get_categories(category_id=0)

    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) >= {"id", "name", "parent_id"}
    assert len(df) == 2


# ---------------------------------------------------------------------------
# clean_and_align (unit)
# ---------------------------------------------------------------------------

def test_clean_and_align_converts_index():
    df = pd.DataFrame({"val": ["1.0", "2.0"]}, index=["2023-01-01", "2023-02-01"])
    result = clean_and_align(df, freq="MS")
    assert isinstance(result.index, pd.DatetimeIndex)


def test_clean_and_align_coerces_strings():
    df = pd.DataFrame({"val": ["3.5", ".", "bad", "4.0"]}, index=pd.date_range("2023-01", periods=4, freq="MS"))
    result = clean_and_align(df, freq="MS")
    assert pd.api.types.is_float_dtype(result["val"])
    assert result["val"].isna().sum() == 2


def test_clean_and_align_drops_bad_dates():
    df = pd.DataFrame({"val": ["1.0", "2.0", "3.0"]}, index=["2023-01-01", "not-a-date", "2023-03-01"])
    result = clean_and_align(df, freq="MS")
    # bad date dropped; resample fills Jan→Mar gap → 3 rows, Feb is NaN
    assert len(result) == 3
    assert result.loc["2023-02-01", "val"] is pd.NA or pd.isna(result.loc["2023-02-01", "val"])
