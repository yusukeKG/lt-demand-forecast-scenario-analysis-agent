"""Startup work: base forecasts for the 4 scenarios, reference data, holdout errors.

Runs once per process in a background thread so the agent starts immediately.
On prediction failure the previous store contents (or the bundled seed cache)
stay in place and are served with ``source: "cache"``.
"""

import logging
import os
import threading
from typing import Any

from agent.forecast import analysis, data, engine, predictor
from agent.forecast.store import ForecastStore, get_store, now_iso

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()
_done = threading.Event()


def reference_payload() -> dict[str, Any]:
    """Static tables the frontend needs (read by the backend from the store)."""
    defs = data.scenario_definitions()
    levers = data.scenario_levers()
    deps = data.load_deployments()
    hist = engine.history_region_year()
    return {
        "scenarios": [
            {**r, "levers": data.lever_defaults(r["scenario_id"])}
            for r in defs.to_dict(orient="records")
        ],
        "levers": levers.to_dict(orient="records"),
        "regions": data.REGIONS,
        "categories": [
            {"slug": s, "name_ja": ja, "available": s in deps}
            for s, ja in data.CATEGORIES.items()
        ],
        "history": hist.to_dict(orient="records"),
        "external": analysis.external(None),
        "countries": data.country_master()[["iso3", "country_ja", "region"]].to_dict(
            orient="records"
        ),
        "feature_ja": analysis.FEATURE_JA,
        "factors_not_in_model": {
            r: analysis.factors_not_in_model(r) for r in data.REGIONS
        },
        "source_note_ja": data.SOURCE_NOTE_JA,
        "base_year": data.BASE_YEAR,
    }


def refresh_reference(store: ForecastStore) -> None:
    store.put("reference", reference_payload())
    store.put("backtest", {
        f"{r or engine.WORLD}|{c or 'all'}": analysis.backtest(c, r)
        for r in [None, *data.REGIONS] for c in [None, *data.CATEGORIES]
    })  # fmt: skip


def refresh_holdout_errors(store: ForecastStore) -> None:
    cached = store.get("holdout_error") or {}
    for slug in data.load_deployments():
        if cached.get(slug, {}).get("method") == "holdout":
            continue
        try:
            cached[slug] = {
                "value": round(predictor.holdout_relative_error(slug), 4),
                "method": "holdout",
            }
        except predictor.PredictionError as e:
            logger.warning("holdout error for %s unavailable: %s", slug, e)
    store.put("holdout_error", cached)


def run_base_forecasts(store: ForecastStore) -> dict[str, str]:
    status: dict[str, str] = {}
    for scn in data.SCENARIO_IDS:
        try:
            run = engine.run_forecast(scn, store=store, refresh=True)
            status[scn] = run["source"]
            if run["source"] == "datarobot" and not engine.seed_path(scn).exists():
                engine.write_seed(store, scn)
        except Exception as e:  # noqa: BLE001 - keep serving whatever is cached
            status[scn] = "unavailable"
            logger.warning(
                "base forecast %s failed: %s", scn, predictor.sanitize(str(e))
            )
    return status


def warmup(store: ForecastStore | None = None) -> None:
    store = store or get_store()
    store.put("status", {"state": "warming_up", "updated_at": now_iso()})
    refresh_reference(store)
    status = run_base_forecasts(store)
    # bands depend on holdout errors: compute them, then refresh the base runs' bands
    refresh_holdout_errors(store)
    for scn in data.SCENARIO_IDS:
        run = store.get_run(engine.base_run_id(scn))
        if run:
            store.put(
                f"bands:{run['run_id']}",
                analysis.all_bands(run, store.run_results(run["run_id"]), store),
            )
    store.put(
        "status", {"state": "ready", "base_runs": status, "updated_at": now_iso()}
    )


def start_background_warmup() -> None:
    """Idempotent: starts the warmup thread once per process.

    Set ``FORECAST_DISABLE_WARMUP=1`` to skip it (tests, offline tooling).
    """
    global _started
    if os.environ.get("FORECAST_DISABLE_WARMUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    with _lock:
        if _started:
            return
        _started = True

    def _run() -> None:
        try:
            warmup()
        except Exception as e:  # noqa: BLE001
            logger.error("forecast warmup failed: %s", predictor.sanitize(str(e)))
        finally:
            _done.set()

    threading.Thread(target=_run, name="forecast-warmup", daemon=True).start()


def wait_until_ready(timeout: float = 60.0) -> bool:
    return _done.wait(timeout)
