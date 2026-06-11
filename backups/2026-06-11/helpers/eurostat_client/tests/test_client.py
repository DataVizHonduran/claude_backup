"""Tests for EurostatClient. Integration tests hit the real API — mark slow."""
import json
import os

import pandas as pd
import pytest

from eurostat_client import EurostatClient
from eurostat_client.utils import jsonstat_to_df, _parse_time_period


# --------------------------------------------------------------------------
# Unit tests — no network
# --------------------------------------------------------------------------

FIXTURE_JSONSTAT = {
    "id": ["unit", "geo", "TIME_PERIOD"],
    "size": [1, 2, 3],
    "dimension": {
        "unit": {"label": "Unit", "category": {"index": {"EUR": 0}, "label": {"EUR": "Euro"}}},
        "geo": {"label": "Geo", "category": {"index": {"DE": 0, "FR": 1}, "label": {"DE": "Germany", "FR": "France"}}},
        "TIME_PERIOD": {
            "label": "Period",
            "category": {
                "index": {"2020-Q1": 0, "2020-Q2": 1, "2020-Q3": 2},
                "label": {"2020-Q1": "2020-Q1", "2020-Q2": "2020-Q2", "2020-Q3": "2020-Q3"},
            },
        },
    },
    "value": [100.0, 101.0, 102.0, 200.0, None, 202.0],
}


def test_jsonstat_to_df_shape():
    df = jsonstat_to_df(FIXTURE_JSONSTAT)
    # 6 combinations, 1 None → 5 rows
    assert len(df) == 5


def test_jsonstat_to_df_no_nan_rows():
    df = jsonstat_to_df(FIXTURE_JSONSTAT)
    assert df["value"].notna().all()


def test_jsonstat_to_df_datetime_index():
    df = jsonstat_to_df(FIXTURE_JSONSTAT)
    assert isinstance(df.index, pd.DatetimeIndex)


def test_jsonstat_to_df_sorted():
    df = jsonstat_to_df(FIXTURE_JSONSTAT)
    assert df.index.is_monotonic_increasing


# --------------------------------------------------------------------------
# Integration tests — require network, marked slow
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_search_catalog_returns_dataframe():
    c = EurostatClient()
    result = c.search_catalog("GDP", top_n=5)
    assert isinstance(result, pd.DataFrame)
    assert "code" in result.columns
    assert len(result) <= 5
    assert result["score"].iloc[0] >= result["score"].iloc[-1]


@pytest.mark.slow
def test_get_dimensions_caches_to_json():
    cache_path = os.path.join(os.path.dirname(__file__), "..", "metadata_cache.json")
    c = EurostatClient()
    dims = c.get_dimensions("namq_10_gdp")
    assert isinstance(dims, dict)
    assert "geo" in dims or "TIME_PERIOD" in dims

    with open(cache_path) as f:
        cache = json.load(f)
    assert "namq_10_gdp" in cache
    assert "fetched" in cache["namq_10_gdp"]


@pytest.mark.slow
def test_get_data_returns_datetime_index():
    c = EurostatClient()
    df = c.get_data(
        "namq_10_gdp",
        unit="CLV_I10",
        s_adj="SA",
        na_item="B1GQ",
        geo="EA20",
    )
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) > 10
    assert df.index.is_monotonic_increasing
