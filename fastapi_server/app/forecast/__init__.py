"""Read-only access to the forecast agent's shared store.

The agent writes runs, results, issues, bands, explanations, the adjustment log
and reference data into a SQLite file (see agent/agent/forecast/store.py). The
backend only reads it, so it never needs the forecast engine.

- Local (``dr run dev``): ``FORECAST_STORE_PATH`` or ``<repo>/.data/forecast_store.sqlite``.
- Deployed (``dr run deploy``): a mirror of the file the agent publishes to
  DataRobot (see ``remote``). Selected automatically.
"""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

RUN_JSON_FIELDS = (
    "levers",
    "lever_overrides",
    "driver_overrides",
    "adjustments",
    "categories",
    "summary",
)


def store_path() -> Path:
    env = os.environ.get("FORECAST_STORE_PATH", "").strip()
    if env:
        return Path(env)
    # <repo>/fastapi_server/app/forecast/__init__.py -> <repo>/.data
    repo = Path(__file__).resolve().parents[3]
    if (repo / "agent").is_dir():
        return repo / ".data" / "forecast_store.sqlite"
    return Path.home() / ".forecast_agent" / "forecast_store.sqlite"


class ForecastStoreReader:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or store_path()

    @property
    def available(self) -> bool:
        return self.path.exists()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get(self, key: str, default: Any = None) -> Any:
        if not self.available:
            return default
        with self._conn() as c:
            r = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def _decode_run(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in RUN_JSON_FIELDS:
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.available:
            return []
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        return [self._decode_run(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        with self._conn() as c:
            r = c.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._decode_run(r) if r else None

    def aggregates(self, run_id: str) -> list[dict[str, Any]]:
        """Units by region x category x year for one run."""
        if not self.available:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT region, category, year, SUM(units) AS units FROM run_results "
                "WHERE run_id = ? GROUP BY region, category, year ORDER BY year",
                (run_id,),
            ).fetchall()
        return [{**dict(r), "units": round(r["units"])} for r in rows]

    def country_results(self, run_id: str, category: str) -> list[dict[str, Any]]:
        if not self.available:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT iso3, region, year, units FROM run_results "
                "WHERE run_id = ? AND category = ? ORDER BY iso3, year",
                (run_id, category),
            ).fetchall()
        return [{**dict(r), "units": round(r["units"])} for r in rows]

    def adjustment_log(self) -> list[dict[str, Any]]:
        if not self.available:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM adjustment_log ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_reader() -> ForecastStoreReader:
    from app.forecast.remote import remote_store_path

    if os.environ.get("FORECAST_STORE_PATH", "").strip():
        return ForecastStoreReader()
    return ForecastStoreReader(remote_store_path())
