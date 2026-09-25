"""Forecast API tests: the backend reads the store the agent writes."""

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.forecast import ForecastStoreReader, get_reader

# Mirrors the agent's schema (agent/agent/forecast/store.py); the backend cannot import it.
SCHEMA = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, created_at TEXT, scenario_id TEXT, label TEXT, kind TEXT,
  base_run_id TEXT, levers TEXT, lever_overrides TEXT, driver_overrides TEXT, adjustments TEXT,
  source TEXT, categories TEXT, summary TEXT);
CREATE TABLE run_results (run_id TEXT, category TEXT, iso3 TEXT, region TEXT, year INTEGER,
  population REAL, pred_per_mn REAL, units REAL);
CREATE TABLE adjustment_log (log_id TEXT PRIMARY KEY, timestamp TEXT, adjusted_by TEXT, region TEXT,
  category TEXT, factor REAL, start_year INTEGER, ramp_years INTEGER, rationale TEXT,
  base_run_id TEXT, new_run_id TEXT);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
"""


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    def j(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)

    summary: dict[str, Any] = {
        "world": [{"category": "general", "units_2050": 100}],
        "applied_overrides": [],
    }
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("base-S1_BASE", "2026-09-24T10:00:00+09:00", "S1_BASE", "ベース", "base", None,
         j({"L1_automation": 0.003}), j({}), j([]), j([]), "datarobot", j(["general"]), j(summary)),
    )  # fmt: skip
    rows = [
        ("base-S1_BASE", "general", iso, "アフリカ", y, 1e6, 10.0, 5.0)
        for iso in ("NGA", "KEN")
        for y in (2026, 2050)
    ]
    conn.executemany("INSERT INTO run_results VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.execute(
        "INSERT INTO adjustment_log VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("adj-1", "2026-09-24T10:05:00+09:00", "経営管理部", "アフリカ", "general", 0.7, 2026, 5,
         "中古機輸入比率の高さ", "base-S1_BASE", "run-x"),
    )  # fmt: skip
    for key, value in {
        "reference": {
            "regions": ["アフリカ"],
            "source_note_ja": "需要はデモ用の架空データ",
        },
        "status": {"state": "ready"},
        "issues:base-S1_BASE": [{"issue_id": "i1", "severity": "high"}],
        "bands:base-S1_BASE": {"世界|all": {"p10": [1], "p50": [2], "p90": [3]}},
        "explanation:latest": {"target": "アフリカ"},
    }.items():
        conn.execute("INSERT INTO kv VALUES (?,?,?)", (key, j(value), "now"))
    conn.commit()
    conn.close()


@pytest.fixture
def forecast_client(authenticated_client: TestClient, tmp_path: Path) -> TestClient:
    path = tmp_path / "forecast_store.sqlite"
    _seed(path)
    app = cast(FastAPI, authenticated_client.app)
    app.dependency_overrides[get_reader] = lambda: ForecastStoreReader(path)
    return authenticated_client


def test_reference_and_status(forecast_client: TestClient) -> None:
    assert forecast_client.get("/api/v1/forecast/reference").json()["regions"] == [
        "アフリカ"
    ]
    status = forecast_client.get("/api/v1/forecast/status").json()
    assert status["state"] == "ready" and status["store_available"] is True


def test_runs_and_aggregates(forecast_client: TestClient) -> None:
    runs = forecast_client.get("/api/v1/forecast/runs").json()
    assert [r["run_id"] for r in runs] == ["base-S1_BASE"]
    agg = forecast_client.get("/api/v1/forecast/runs/base-S1_BASE/aggregates").json()
    assert {
        "region": "アフリカ",
        "category": "general",
        "year": 2050,
        "units": 10,
    } in agg
    countries = forecast_client.get(
        "/api/v1/forecast/runs/base-S1_BASE/countries?category=general"
    ).json()
    assert len(countries) == 4


def test_derived_views(forecast_client: TestClient) -> None:
    assert (
        forecast_client.get("/api/v1/forecast/runs/base-S1_BASE/issues").json()[0][
            "severity"
        ]
        == "high"
    )
    assert (
        "世界|all"
        in forecast_client.get("/api/v1/forecast/runs/base-S1_BASE/bands").json()
    )
    assert (
        forecast_client.get("/api/v1/forecast/explanations").json()["target"]
        == "アフリカ"
    )
    log = forecast_client.get("/api/v1/forecast/adjustments").json()
    assert log[0]["rationale"] == "中古機輸入比率の高さ"


def test_unknown_run_is_404(forecast_client: TestClient) -> None:
    assert forecast_client.get("/api/v1/forecast/runs/nope").status_code == 404


def test_reference_not_ready(authenticated_client: TestClient, tmp_path: Path) -> None:
    missing = ForecastStoreReader(tmp_path / "missing.sqlite")
    cast(FastAPI, authenticated_client.app).dependency_overrides[get_reader] = lambda: (
        missing
    )
    assert authenticated_client.get("/api/v1/forecast/reference").status_code == 503
    assert authenticated_client.get("/api/v1/forecast/runs").json() == []


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/forecast/runs").status_code in (401, 403)
