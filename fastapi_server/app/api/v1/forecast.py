"""Read-only forecast endpoints for the dashboard pages.

All data is produced by the agent (tools and startup warmup) and read from the
shared store; see app/forecast.
"""

from typing import Any, cast

from datarobot.auth.session import AuthCtx
from datarobot.auth.typing import Metadata
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.ctx import must_get_auth_ctx
from app.forecast import ForecastStoreReader, get_reader

forecast_router = APIRouter(prefix="/forecast", tags=["Forecast"])

RUN_BRIEF_FIELDS = (
    "run_id",
    "created_at",
    "scenario_id",
    "label",
    "kind",
    "base_run_id",
    "source",
    "categories",
    "levers",
    "driver_overrides",
    "lever_overrides",
    "adjustments",
)


def _run_or_404(reader: ForecastStoreReader, run_id: str) -> dict[str, Any]:
    run = reader.get_run(run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@forecast_router.get("/status")
def get_status(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    status_ = reader.get("status") or {"state": "not_started"}
    return {**status_, "store_available": reader.available}


@forecast_router.get("/reference")
def get_reference(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    ref = reader.get("reference")
    if not ref:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="forecast data is not ready yet (agent warmup pending)",
        )
    return cast(dict[str, Any], ref)


@forecast_router.get("/runs")
def list_runs(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> list[dict[str, Any]]:
    out = []
    for run in reader.list_runs():
        brief = {k: run.get(k) for k in RUN_BRIEF_FIELDS}
        summary = run.get("summary") or {}
        brief["applied_overrides"] = summary.get("applied_overrides", [])
        brief["world"] = summary.get("world", [])
        brief["unavailable_categories"] = summary.get("unavailable_categories", [])
        out.append(brief)
    return out


@forecast_router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    return _run_or_404(reader, run_id)


@forecast_router.get("/runs/{run_id}/aggregates")
def get_run_aggregates(
    run_id: str,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> list[dict[str, Any]]:
    _run_or_404(reader, run_id)
    return reader.aggregates(run_id)


@forecast_router.get("/runs/{run_id}/countries")
def get_run_countries(
    run_id: str,
    category: str = Query(..., pattern="^(general|mini|mining)$"),
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> list[dict[str, Any]]:
    _run_or_404(reader, run_id)
    return reader.country_results(run_id, category)


@forecast_router.get("/runs/{run_id}/bands")
def get_run_bands(
    run_id: str,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    _run_or_404(reader, run_id)
    return cast(dict[str, Any], reader.get(f"bands:{run_id}") or {})


@forecast_router.get("/runs/{run_id}/issues")
def get_run_issues(
    run_id: str,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> list[dict[str, Any]]:
    _run_or_404(reader, run_id)
    return cast(list[dict[str, Any]], reader.get(f"issues:{run_id}") or [])


@forecast_router.get("/explanations")
def get_explanation(
    run_id: str | None = None,
    target: str | None = None,
    category: str | None = None,
    year: int | None = None,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any] | None:
    """A stored explanation, or the latest one when no key is given."""
    if run_id and target and category and year:
        return cast(
            dict[str, Any] | None,
            reader.get(f"explanation:{run_id}|{target}|{category}|{year}"),
        )
    return cast(dict[str, Any] | None, reader.get("explanation:latest"))


@forecast_router.get("/comparison/latest")
def get_latest_comparison(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any] | None:
    return cast(dict[str, Any] | None, reader.get("comparison:latest"))


@forecast_router.get("/adjustments")
def get_adjustments(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> list[dict[str, Any]]:
    return reader.adjustment_log()


@forecast_router.get("/backtest")
def get_backtest(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    return cast(dict[str, Any], reader.get("backtest") or {})


@forecast_router.get("/summaries/latest")
def get_latest_summary(
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any] | None:
    return cast(dict[str, Any] | None, reader.get("summary:latest"))


@forecast_router.get("/summaries/{summary_id}")
def get_summary(
    summary_id: str,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
    reader: ForecastStoreReader = Depends(get_reader),
) -> dict[str, Any]:
    s = reader.get(f"summary:{summary_id}")
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="summary not found")
    return cast(dict[str, Any], s)
