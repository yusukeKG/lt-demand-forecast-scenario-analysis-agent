"""Forecast runs: scenario drivers -> features -> DataRobot -> postprocess -> store."""

import logging
import secrets
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from agent.forecast import data, overrides, predictor, scenarios
from agent.forecast.postprocess import postprocess
from agent.forecast.scoring_data import build_score_frame
from agent.forecast.store import ForecastStore, get_store, now_iso

logger = logging.getLogger(__name__)

SUMMARY_YEARS = (2030, 2040, 2050)
WORLD = "世界"
ALL_CATEGORIES = "全機種"


def base_run_id(scenario_id: str) -> str:
    return f"base-{scenario_id}"


def new_run_id() -> str:
    return f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def scenario_label(scenario_id: str) -> str:
    s = data.scenario_definitions().set_index("scenario_id")
    return (
        str(s.loc[scenario_id, "scenario_ja"])
        if scenario_id in s.index
        else scenario_id
    )


def normalize_scenario(scenario_id: str) -> str:
    """Accept S1_BASE / ベース / 脱炭素加速 etc."""
    s = str(scenario_id).strip()
    if s in data.SCENARIO_IDS:
        return s
    defs = data.scenario_definitions()
    hit = defs[(defs.scenario_ja == s) | (defs.scenario_id.str.upper() == s.upper())]
    if len(hit):
        return str(hit.scenario_id.iloc[0])
    for sid in data.SCENARIO_IDS:
        if s.upper() in sid:
            return sid
    raise ValueError(
        f"未知のシナリオです: {scenario_id}（{', '.join(data.SCENARIO_IDS)}）"
    )


def normalize_category(category: str | None) -> str | None:
    """general / mini / mining, Japanese names, or None for all categories."""
    if category is None or str(category).strip() in (
        "",
        "all",
        "全機種",
        "全体",
        "合計",
    ):
        return None
    c = str(category).strip()
    if c in data.CATEGORIES:
        return c
    if c in data.CATEGORY_BY_JA:
        return data.CATEGORY_BY_JA[c]
    raise ValueError(f"未知の機種です: {category}（general / mini / mining）")


def normalize_region(region: str | None) -> str | None:
    if region is None or str(region).strip() in ("", "world", "世界", "全世界", "全体"):
        return None
    r = str(region).strip()
    if r not in data.REGIONS:
        raise ValueError(f"未知の地域です: {region}（{'、'.join(data.REGIONS)}）")
    return r


# ---------------------------------------------------------------- drivers
def future_drivers_for(run: dict[str, Any]) -> pd.DataFrame:
    """Rebuild the future drivers a run was computed from (deterministic)."""
    scn, levers = run["scenario_id"], run["levers"]
    if scenarios.uses_default_structural_levers(scn, levers):
        fut = data.future_drivers()
        fut = fut[fut.scenario_id == scn].reset_index(drop=True)
    else:
        fut = scenarios.generate_future_drivers(scn, levers)
    return overrides.apply_driver_overrides(fut, run.get("driver_overrides") or [])


def score_frames_for(
    run: dict[str, Any], slugs: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    fut = future_drivers_for(run)
    return {s: build_score_frame(fut, s) for s in (slugs or list(data.CATEGORIES))}


def _postprocess(
    slug: str,
    score: pd.DataFrame,
    pred_per_mn: pd.Series,
    levers: dict[str, Any],
    adjustments: list[dict[str, Any]],
) -> pd.DataFrame:
    d = score.copy()
    d["pred_per_mn"] = pred_per_mn.to_numpy()
    out = postprocess(  # type: ignore[no-untyped-call]
        d,
        "pred_per_mn",
        slug,
        jumpoff=data.jumpoff_units(slug),
        automation_rate=float(levers["L1_automation"]),
        adjustments=[a for a in adjustments if a.get("category") == slug],
    )
    out["category"] = slug
    out["units"] = out.units_pred
    return out[
        ["category", "iso3", "region", "year", "population", "pred_per_mn", "units"]
    ]


# ---------------------------------------------------------------- summaries
def history_region_year() -> pd.DataFrame:
    """Actual demand by region x category(slug) x year (file 05)."""
    h = data.demand_region_year().copy()
    h["category"] = h.category.map(data.CATEGORY_BY_JA)
    return h[["region", "category", "year", "units"]]


def actual_2025(region: str | None = None, category: str | None = None) -> float:
    h = history_region_year()
    h = h[h.year == data.BASE_YEAR]
    if region:
        h = h[h.region == region]
    if category:
        h = h[h.category == category]
    return float(h.units.sum())


def build_summary(run: dict[str, Any], results: pd.DataFrame) -> dict[str, Any]:
    totals = results.groupby(["year", "category"], as_index=False).units.sum()
    by_region = []
    reg = results.groupby(["region", "category", "year"]).units.sum()
    for region in data.REGIONS:
        for slug in data.CATEGORIES:
            if (region, slug, 2050) not in reg.index:
                continue
            u25 = actual_2025(region, slug)
            row: dict[str, Any] = {
                "region": region,
                "category": slug,
                "units_2025": round(u25),
            }
            for y in SUMMARY_YEARS:
                row[f"units_{y}"] = round(float(reg.loc[(region, slug, y)]))
            row["growth_2050_vs_2025"] = (
                round(row["units_2050"] / u25, 2) if u25 else None
            )
            by_region.append(row)
    world = []
    for slug in sorted(results.category.unique()):
        u25 = actual_2025(None, slug)
        t = totals[totals.category == slug].set_index("year").units
        world.append({"category": slug, "units_2025": round(u25),
                      **{f"units_{y}": round(float(t[y])) for y in SUMMARY_YEARS},
                      **{f"growth_{y}_vs_2025": round(float(t[y]) / u25, 2) for y in SUMMARY_YEARS}})  # fmt: skip
    missing = [
        data.CATEGORIES[s] for s in data.CATEGORIES if s not in set(results.category)
    ]
    return {
        "run_id": run["run_id"],
        "scenario_id": run["scenario_id"],
        "label": run["label"],
        "totals_by_year": [
            {
                "year": int(r.year),
                "category": r.category,
                "units": round(float(r.units)),
            }
            for r in totals.itertuples()
        ],
        "world": world,
        "by_region": by_region,
        "applied_overrides": run.get("applied_overrides", []),
        "levers": run["levers"],
        "unavailable_categories": missing,
        "source": run["source"],
        "units_note": "units は台数。2025年は実績（ダミー）、2026年以降は予測",
    }


def compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Tool-facing summary: drops the per-year series to keep the LLM context small."""
    s = {k: v for k, v in summary.items() if k != "totals_by_year"}
    s["totals_by_year"] = [
        r for r in summary["totals_by_year"] if r["year"] in (2026, *SUMMARY_YEARS)
    ]
    return s


# ---------------------------------------------------------------- runs
def _describe_levers(scenario_id: str, levers: dict[str, Any]) -> list[str]:
    d = data.lever_defaults(scenario_id)
    names = data.scenario_levers().set_index("lever_id").lever_ja
    return [f"{names[k]}：{d[k]} → {v}" for k, v in levers.items() if v != d[k]]


def _save(
    store: ForecastStore, run: dict[str, Any], results: pd.DataFrame
) -> dict[str, Any]:
    from agent.forecast import analysis  # local import: analysis depends on engine

    run["categories"] = sorted(results.category.unique())
    run["summary"] = build_summary(run, results)
    store.save_run(run, results)
    try:
        store.put(f"issues:{run['run_id']}", analysis.detect_issues(run, results))
        store.put(f"bands:{run['run_id']}", analysis.all_bands(run, results, store))
    except Exception:  # noqa: BLE001 - derived views must not block the run
        logger.exception("failed to compute derived views for %s", run["run_id"])
    return run


def run_forecast(
    scenario_id: str,
    driver_overrides: list[dict[str, Any]] | None = None,
    lever_overrides: dict[str, Any] | None = None,
    label: str | None = None,
    store: ForecastStore | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Run (or reuse) a forecast and return the stored run record."""
    store = store or get_store()
    scn = normalize_scenario(scenario_id)
    levers = scenarios.resolve_levers(scn, lever_overrides)
    drivers = overrides.validate(driver_overrides)
    is_base = not drivers and levers == data.lever_defaults(scn)
    run_id = base_run_id(scn) if is_base else new_run_id()
    if is_base and not refresh:
        cached = store.get_run(run_id)
        if cached:
            return cached

    applied = [overrides.describe(o) for o in drivers] + _describe_levers(scn, levers)
    run: dict[str, Any] = {
        "run_id": run_id,
        "created_at": now_iso(),
        "scenario_id": scn,
        "label": label
        or (scenario_label(scn) if is_base else f"{scenario_label(scn)}（what-if）"),
        "kind": "base" if is_base else "whatif",
        "base_run_id": None if is_base else base_run_id(scn),
        "levers": levers,
        "lever_overrides": {
            k: v for k, v in (lever_overrides or {}).items() if v is not None
        },
        "driver_overrides": drivers,
        "adjustments": [],
        "applied_overrides": applied,
        "source": "datarobot",
    }
    deps = data.load_deployments()
    slugs = [s for s in data.CATEGORIES if s in deps]
    try:
        frames = score_frames_for(run, slugs)
        preds = predictor.predict_many(frames)
    except predictor.PredictionError as e:
        return _fallback(store, scn, run, str(e))
    results = pd.concat(
        [_postprocess(s, frames[s], preds[s], levers, []) for s in slugs],
        ignore_index=True,
    )
    return _save(store, run, results)


def _fallback(
    store: ForecastStore, scn: str, run: dict[str, Any], reason: str
) -> dict[str, Any]:
    """Prediction failed: fall back to the cached base run of the same scenario."""
    cached = store.get_run(base_run_id(scn)) or seed_base_run(store, scn)
    if not cached:
        raise predictor.PredictionError(
            f"{reason}。キャッシュもないため結果を表示できません"
        )
    out = dict(cached)
    out["source"] = "cache"
    out["summary"] = {**cached["summary"], "source": "cache"}
    notes = [
        f"DataRobot への予測リクエストに失敗したため、キャッシュ結果（{cached['label']}）を表示しています。理由: {reason}"
    ]
    if run["kind"] != "base":
        notes.append(
            "前提の変更（"
            + "、".join(run["applied_overrides"])
            + "）は反映されていません"
        )
    out["warnings"] = notes
    return out


# ---------------------------------------------------------------- seed cache
SEED_DIR = data.ASSETS_DIR / "cache"


def seed_path(scenario_id: str) -> Any:
    return SEED_DIR / f"base_{scenario_id}.csv"


def write_seed(store: ForecastStore, scenario_id: str) -> None:
    """Snapshot a base run into the bundled seed cache (last-resort fallback)."""
    res = store.run_results(base_run_id(scenario_id))
    if len(res):
        SEED_DIR.mkdir(parents=True, exist_ok=True)
        res.round(4).to_csv(seed_path(scenario_id), index=False, encoding="utf-8-sig")


def seed_base_run(store: ForecastStore, scenario_id: str) -> dict[str, Any] | None:
    """Load a base run from the bundled seed cache into the store."""
    path = seed_path(scenario_id)
    if not path.exists():
        return None
    results = pd.read_csv(path, encoding="utf-8-sig")
    run: dict[str, Any] = {
        "run_id": base_run_id(scenario_id),
        "created_at": now_iso(),
        "scenario_id": scenario_id,
        "label": scenario_label(scenario_id),
        "kind": "base",
        "base_run_id": None,
        "levers": data.lever_defaults(scenario_id),
        "lever_overrides": {},
        "driver_overrides": [],
        "adjustments": [],
        "applied_overrides": [],
        "source": "cache",
    }
    return _save(store, run, results)


# ---------------------------------------------------------------- adjustments
def adjust_run(
    base_run: dict[str, Any],
    adjustment: dict[str, Any],
    label: str,
    store: ForecastStore | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Re-run postprocess with an extra human adjustment. Returns (run, before, after)."""
    store = store or get_store()
    before = store.run_results(base_run["run_id"])
    adjustments = [*(base_run.get("adjustments") or []), adjustment]
    slugs = sorted(before.category.unique())
    frames = score_frames_for(base_run, slugs)
    parts = []
    for s in slugs:
        f = frames[s]
        raw = before[before.category == s].set_index(["iso3", "year"]).pred_per_mn
        pred = pd.Series(
            raw.reindex(pd.MultiIndex.from_frame(f[["iso3", "year"]])).to_numpy(),
            index=f.index,
        )
        parts.append(_postprocess(s, f, pred, base_run["levers"], adjustments))
    after = pd.concat(parts, ignore_index=True)
    run: dict[str, Any] = {
        **{
            k: base_run[k]
            for k in ("scenario_id", "levers", "lever_overrides", "driver_overrides")
        },
        "run_id": new_run_id(),
        "created_at": now_iso(),
        "label": label,
        "kind": "adjusted",
        "base_run_id": base_run["run_id"],
        "adjustments": adjustments,
        "applied_overrides": [*(base_run.get("applied_overrides") or []), label],
        "source": base_run.get("source", "datarobot"),
    }
    return _save(store, run, after), before, after


def series(
    results: pd.DataFrame, region: str | None, category: str | None
) -> pd.Series:
    """Yearly units for a region/category filter (None = all)."""
    d = results
    if region:
        d = d[d.region == region]
    if category:
        d = d[d.category == category]
    return d.groupby("year").units.sum().reindex(data.FORECAST_YEARS).fillna(0.0)


def growth(value: float, base: float) -> float | None:
    return round(value / base, 2) if base else None


def as_float_list(s: pd.Series, digits: int = 0) -> list[float]:
    return [round(float(v), digits) for v in np.asarray(s, dtype=float)]
