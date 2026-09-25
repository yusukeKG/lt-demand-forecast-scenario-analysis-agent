"""Persistent store for runs, run results, the adjustment log and reference data.

The store is the contract between the agent (writer) and the FastAPI backend
(reader): the backend never imports agent code, it reads this SQLite file.
Location: ``FORECAST_STORE_PATH`` or ``<repo>/.data/forecast_store.sqlite``.
Keep all access behind ``ForecastStore`` so a DataRobot-hosted backend can
replace SQLite for deployments.
"""

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,              -- base | whatif | adjusted
    base_run_id TEXT,
    levers TEXT NOT NULL,            -- JSON: resolved L1-L4
    lever_overrides TEXT NOT NULL,   -- JSON
    driver_overrides TEXT NOT NULL,  -- JSON
    adjustments TEXT NOT NULL,       -- JSON: human adjustments applied in postprocess
    source TEXT NOT NULL,            -- datarobot | cache
    categories TEXT NOT NULL,        -- JSON: categories with results
    summary TEXT NOT NULL            -- JSON: run_forecast summary
);
CREATE TABLE IF NOT EXISTS run_results (
    run_id TEXT NOT NULL,
    category TEXT NOT NULL,
    iso3 TEXT NOT NULL,
    region TEXT NOT NULL,
    year INTEGER NOT NULL,
    population REAL NOT NULL,
    pred_per_mn REAL NOT NULL,       -- raw model output (units per million people)
    units REAL NOT NULL,             -- after postprocess
    PRIMARY KEY (run_id, category, iso3, year)
);
CREATE TABLE IF NOT EXISTS adjustment_log (
    log_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    adjusted_by TEXT NOT NULL,
    region TEXT NOT NULL,
    category TEXT NOT NULL,
    factor REAL NOT NULL,
    start_year INTEGER NOT NULL,
    ramp_years INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    base_run_id TEXT NOT NULL,
    new_run_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

RUN_JSON_FIELDS = (
    "levers",
    "lever_overrides",
    "driver_overrides",
    "adjustments",
    "categories",
    "summary",
)


def default_store_path() -> Path:
    env = os.environ.get("FORECAST_STORE_PATH", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    # local checkout: <repo>/agent/agent/forecast/store.py -> <repo>/.data
    repo = here.parents[3]
    if (repo / "fastapi_server").is_dir():
        return repo / ".data" / "forecast_store.sqlite"
    return Path.home() / ".forecast_agent" / "forecast_store.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class ForecastStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ runs
    def save_run(self, run: dict[str, Any], results: pd.DataFrame) -> None:
        row = {
            k: (
                json.dumps(run.get(k), ensure_ascii=False)
                if k in RUN_JSON_FIELDS
                else run.get(k)
            )
            for k in (
                "run_id",
                "created_at",
                "scenario_id",
                "label",
                "kind",
                "base_run_id",
                *RUN_JSON_FIELDS,
                "source",
            )
        }
        cols = [
            "run_id",
            "category",
            "iso3",
            "region",
            "year",
            "population",
            "pred_per_mn",
            "units",
        ]
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM run_results WHERE run_id = ?", (run["run_id"],))
            c.execute(
                f"INSERT OR REPLACE INTO runs ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                list(row.values()),
            )
            c.executemany(
                f"INSERT INTO run_results ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                results.assign(run_id=run["run_id"])[cols].itertuples(
                    index=False, name=None
                ),
            )

    def _decode_run(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in RUN_JSON_FIELDS:
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._decode_run(r) if r else None

    def list_runs(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        return [self._decode_run(r) for r in rows]

    def run_results(self, run_id: str) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(
                "SELECT category, iso3, region, year, population, pred_per_mn, units "
                "FROM run_results WHERE run_id = ?",
                c,
                params=(run_id,),
            )

    # ------------------------------------------------------------ adjustments
    def add_adjustment(self, entry: dict[str, Any]) -> None:
        cols = ["log_id", "timestamp", "adjusted_by", "region", "category", "factor",
                "start_year", "ramp_years", "rationale", "base_run_id", "new_run_id"]  # fmt: skip
        with self._lock, self._conn() as c:
            c.execute(
                f"INSERT INTO adjustment_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [entry[k] for k in cols],
            )

    def adjustment_log(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM adjustment_log ORDER BY timestamp"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------- kv
    def put(self, key: str, value: Any) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False, default=float), now_iso()),
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._conn() as c:
            r = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default


_store: ForecastStore | None = None
_store_lock = threading.Lock()


def get_store() -> ForecastStore:
    global _store
    with _store_lock:
        if _store is None or _store.path != default_store_path():
            _store = ForecastStore()
        return _store
