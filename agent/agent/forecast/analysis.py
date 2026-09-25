"""Issue detection, uncertainty bands, explanations, comparisons and backtests."""

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from agent.forecast import data, engine, predictor
from agent.forecast.features import FEATURES
from agent.forecast.store import ForecastStore, get_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- thresholds (IMPLEMENTATION_NOTES 4.3)
EXTERNAL_GAP_ABS_MULTIPLE = 1.0  # |model - external| >= 1.0倍
EXTERNAL_GAP_RATIO = 2.0  # model / external (or inverse) >= 2倍
EXTREME_GROWTH_HIGH = 3.0  # 2050 multiple > 3倍
EXTREME_GROWTH_LOW = 0.5  # 2050 multiple < 0.5倍
OUT_OF_RANGE_MIN_SHARE = (
    0.05  # report a feature when >= 5% of a region's future rows exceed training range
)
OUT_OF_RANGE_FEATURES = [f for f in FEATURES if f != "region"]

# Uncertainty band fallback: relative error per 5 years (IMPLEMENTATION_NOTES 4.6)
DEFAULT_ERROR_PER_5Y = {"general": 0.25, "mini": 0.10, "mining": 0.22}
BAND_HORIZON_YEARS = 5

HISTORICAL_ANALOG_BAND = 0.15  # ±15% of target-year GDP per capita
HISTORICAL_ANALOG_COUNT = 5

FEATURE_JA = {
    "region": "地域",
    "gdp_pc_ppp": "1人当たりGDP",
    "gdp_pc_growth_5y_pct": "1人当たりGDPの5年平均成長率",
    "gdp_growth_pct": "実質GDP成長率",
    "gdp_growth_3y_avg_pct": "実質GDP成長率（3年平均）",
    "urban_pct": "都市化率",
    "urban_pct_change_5y": "都市化率の5年変化",
    "gfcf_pct_gdp": "投資比率（固定資本形成のGDP比）",
    "gfcf_pct_gdp_change_3y": "投資比率の3年変化",
    "coal_prod_kwh_per_capita": "1人当たり石炭生産量",
    "res_copper": "銅の資源依存度",
    "res_ironore": "鉄鉱石の資源依存度",
    "res_gold": "金の資源依存度",
    "copper_ratio_lag1": "銅価格の水準（前年、2005〜2015年平均比）",
    "ironore_ratio_lag1": "鉄鉱石価格の水準（前年、2005〜2015年平均比）",
    "coal_ratio_lag1": "石炭価格の水準（前年、2005〜2015年平均比）",
    "gold_ratio_lag1": "金価格の水準（前年、2005〜2015年平均比）",
    "copper_ratio_change_3y": "銅価格の3年変化",
}

FACTORS_NOT_IN_MODEL = {
    "アフリカ": [
        "先進国からの中古機の流入",
        "資金調達環境（金利・与信）",
        "政治の安定性",
        "インフラ投資の財源（援助・外国資本）",
    ],
    "中国": ["景気対策などの政策ショック", "不動産市場の調整"],
    "CIS": ["制裁・地政学リスク"],
    "中近東": ["大型国家プロジェクト", "原油価格"],
    "アジア": ["インドネシアの資源政策", "インドのインフラ予算"],
    "北米": ["インフラ投資法", "金利"],
    "日本": ["国土強靭化投資", "建設業の人手不足"],
}
COMMON_FACTORS = ["自動化・電動化の進展速度", "レンタル比率"]

BACKTEST_NOTE = (
    "前提（人口・GDPなど）に実際の値を使った検証であり、モデルの構造の妥当性を示すものです。"
    "将来の前提そのものの不確実性は含まれていません。"
)


def factors_not_in_model(region: str | None) -> list[str]:
    return [*FACTORS_NOT_IN_MODEL.get(region or "", []), *COMMON_FACTORS]


def category_ja(slug: str | None) -> str:
    return data.CATEGORIES.get(slug or "", engine.ALL_CATEGORIES)


def _fmt_x(v: float | None) -> str:
    return "—" if v is None else f"約{v:.1f}倍"


# ---------------------------------------------------------------- issues
def _external_multiples() -> dict[str, float]:
    ext = data.external_forecast().set_index("region")
    return {
        r: 1 + float(ext.loc[r, "growth_2050_vs_2025_pct"]) / 100 for r in ext.index
    }


def _driver_story(run: dict[str, Any], region: str) -> str:
    """Model-side reasons in plain words: how the main inputs move 2025 -> 2050."""
    fut = engine.future_drivers_for(run)
    hist = data.drivers_history()
    f = fut[(fut.region == region) & (fut.year == 2050)]
    h = hist[(hist.region == region) & (hist.year == data.BASE_YEAR)]
    if f.empty or h.empty:
        return ""

    def gpc(d: pd.DataFrame) -> float:
        return float((d.gdp_pc_ppp_const2021 * d.population).sum() / d.population.sum())

    def urb(d: pd.DataFrame) -> float:
        return float((d.urban_pct * d.population).sum() / d.population.sum())

    pop = float(f.population.sum() / h.population.sum())
    return (
        f"モデルの入力では、2025年→2050年に1人当たりGDPが約{gpc(f) / gpc(h):.1f}倍、"
        f"都市化率が{urb(h):.0f}%→{urb(f):.0f}%、人口が約{pop:.2f}倍になります"
    )


def _training_ranges() -> dict[str, pd.DataFrame]:
    return {
        s: data.train_data(s)[OUT_OF_RANGE_FEATURES].agg(["min", "max"])
        for s in data.CATEGORIES
    }


def detect_issues(run: dict[str, Any], results: pd.DataFrame) -> list[dict[str, Any]]:
    """Rule-based checks of a run (HILP trigger). Never modifies the run."""
    issues: list[dict[str, Any]] = []
    ext = _external_multiples()
    flagged: set[str] = set()
    stories: dict[str, str] = {}

    def story(region: str) -> str:
        if region not in stories:
            try:
                stories[region] = _driver_story(run, region)
            except Exception:  # noqa: BLE001
                stories[region] = ""
        return stories[region]

    def add(**kw: Any) -> None:
        kw["issue_id"] = f"{run['run_id']}-{len(issues) + 1:02d}"
        issues.append(kw)

    # external_gap: region total (all categories) vs external forecast
    for region in data.REGIONS:
        u25 = engine.actual_2025(region, None)
        m = engine.growth(float(engine.series(results, region, None)[2050]), u25)
        e = ext.get(region)
        if m is None or e is None:
            continue
        ratio = max(m / e, e / m) if m > 0 and e > 0 else math.inf
        if abs(m - e) >= EXTERNAL_GAP_ABS_MULTIPLE or ratio >= EXTERNAL_GAP_RATIO:
            flagged.add(region)
            direction = "上回って" if m > e else "下回って"
            missing = "、".join(FACTORS_NOT_IN_MODEL.get(region, COMMON_FACTORS))
            add(
                severity="high", region=region, category=engine.ALL_CATEGORIES, type="external_gap",
                message_ja=(
                    f"{region}の建機需要（3機種計）は2050年に2025年比 {_fmt_x(m)}の見通しです。"
                    f"外部予測（{_fmt_x(e)}）を大きく{direction}います。"
                    f"【モデルの根拠】{story(region)}。"
                    f"【モデルが考慮していない要因】{missing}。"
                ),
                model_growth_2050=m, external_growth_2050=round(e, 2),
                suggested_questions=[f"{region}の伸びの要因を分解して", f"{region}の外部予測との差はどう考えればいい？"],
            )  # fmt: skip

    # extreme_growth: region x category
    for region in data.REGIONS:
        for slug in sorted(results.category.unique()):
            u25 = engine.actual_2025(region, slug)
            if not u25:
                continue
            m = engine.growth(float(engine.series(results, region, slug)[2050]), u25)
            if m is None or EXTREME_GROWTH_LOW <= m <= EXTREME_GROWTH_HIGH:
                continue
            flagged.add(region)
            kind = "過去に例のない急成長" if m > EXTREME_GROWTH_HIGH else "大幅な縮小"
            add(
                severity="medium", region=region, category=slug, type="extreme_growth",
                message_ja=(
                    f"{region}の{category_ja(slug)}は2050年に2025年比 {_fmt_x(m)}（{kind}）の見通しです。"
                    f"【モデルの根拠】{story(region)}。"
                    f"【モデルが考慮していない要因】{'、'.join(factors_not_in_model(region))}。"
                ),
                model_growth_2050=m, external_growth_2050=round(ext.get(region, 0.0), 2) or None,
                suggested_questions=[f"{region}の{category_ja(slug)}の伸びはなぜこうなる？", f"{region}の{category_ja(slug)}を補正したらどうなる？"],
            )  # fmt: skip

    # out_of_range_input: future features beyond the training range
    try:
        frames = engine.score_frames_for(run, sorted(results.category.unique()))
        ranges = _training_ranges()
        for slug, f in frames.items():
            rng = ranges[slug]
            for feat in OUT_OF_RANGE_FEATURES:
                lo, hi = float(rng.loc["min", feat]), float(rng.loc["max", feat])
                over = f[(f[feat] > hi) | (f[feat] < lo)]
                if over.empty:
                    continue
                share = over.groupby("region").size() / f.groupby("region").size()
                regions = [
                    r for r in data.REGIONS if share.get(r, 0) >= OUT_OF_RANGE_MIN_SHARE
                ]
                if not regions:
                    continue
                first_year = int(over.year.min())
                worst = (
                    float(over[feat].max())
                    if (over[feat] > hi).any()
                    else float(over[feat].min())
                )
                flagged.update(regions)
                add(
                    severity="medium", region="、".join(regions), category=slug, type="out_of_range_input",
                    message_ja=(
                        f"{category_ja(slug)}の予測では、{FEATURE_JA.get(feat, feat)}が学習データの範囲"
                        f"（{lo:.2f}〜{hi:.2f}）を{first_year}年以降に超えます（最大 {worst:.2f}、対象: {'、'.join(regions)}）。"
                        "範囲外の値ではモデルの反応が頭打ちになりやすく、結果は参考値として扱ってください。"
                        + (
                            "鉱山機械では、学習範囲を超える資源価格の効果を後処理（弾性値による補正）で上乗せしています。"
                            if slug == "mining" and feat.endswith("_ratio_lag1")
                            else ""
                        )
                    ),
                    model_growth_2050=None, external_growth_2050=None,
                    suggested_questions=[f"{FEATURE_JA.get(feat, feat)}が範囲外だと何が起きる？"],
                )  # fmt: skip
    except Exception:  # noqa: BLE001 - range check is advisory
        logger.exception("out_of_range check failed")

    # missing_factor: regions flagged above that have known factors outside the model
    for region in data.REGIONS:
        if region in flagged and region in FACTORS_NOT_IN_MODEL:
            add(
                severity="low", region=region, category=engine.ALL_CATEGORIES, type="missing_factor",
                message_ja=f"{region}では、モデルに含まれていない次の要因が需要を左右しやすい地域です：{'、'.join(factors_not_in_model(region))}。補正するかどうかはご判断ください。",
                model_growth_2050=engine.growth(float(engine.series(results, region, None)[2050]), engine.actual_2025(region, None)),
                external_growth_2050=round(ext.get(region, 0.0), 2) or None,
                suggested_questions=[f"{region}を補正するならどう考えればいい？"],
            )  # fmt: skip
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(issues, key=lambda i: order[i["severity"]])


# ---------------------------------------------------------------- uncertainty
def error_per_5y(store: ForecastStore | None = None) -> dict[str, dict[str, Any]]:
    store = store or get_store()
    cached = store.get("holdout_error") or {}
    return {
        s: cached.get(s) or {"value": DEFAULT_ERROR_PER_5Y[s], "method": "default"}
        for s in data.CATEGORIES
    }


def band(
    results: pd.DataFrame,
    region: str | None,
    category: str | None,
    errors: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    years = np.array(data.FORECAST_YEARS)
    widen = np.sqrt((years - data.BASE_YEAR) / BAND_HORIZON_YEARS)
    slugs = [category] if category else sorted(results.category.unique())
    p50 = np.zeros(len(years))
    var = np.zeros(len(years))
    for s in slugs:
        v = engine.series(results, region, s).to_numpy()
        e = errors[s]["value"] * widen
        p50 += v
        var += (v * e) ** 2  # categories treated as independent
    half = np.sqrt(var)
    methods = {errors[s]["method"] for s in slugs}
    return {
        "years": [int(y) for y in years],
        "p10": [round(float(x)) for x in np.maximum(p50 - half, 0)],
        "p50": [round(float(x)) for x in p50],
        "p90": [round(float(x)) for x in p50 + half],
        "method": "holdout_error"
        if methods == {"holdout"}
        else "holdout_error(default)",
        "note": "P10〜P90は不確実性の目安であり、確率を保証するものではありません",
    }


def all_bands(
    run: dict[str, Any], results: pd.DataFrame, store: ForecastStore | None = None
) -> dict[str, Any]:
    errors = error_per_5y(store)
    out = {}
    for region in [None, *data.REGIONS]:
        for slug in [None, *sorted(results.category.unique())]:
            out[f"{region or engine.WORLD}|{slug or 'all'}"] = band(
                results, region, slug, errors
            )
    return out


# ---------------------------------------------------------------- explanation
def _targets(target: str) -> tuple[str, list[str], str | None]:
    master = data.country_master()
    t = str(target).strip()
    if t.lower() in ("world", "global") or t in ("世界", "全世界"):
        return engine.WORLD, list(master.iso3), None
    if t in data.REGIONS:
        return t, list(master[master.region == t].iso3), t
    hit = master[
        (master.iso3 == t.upper()) | (master.country_ja == t) | (master.country_en == t)
    ]
    if hit.empty:
        raise ValueError(f"対象が見つかりません: {target}（国コードまたは地域名）")
    row = hit.iloc[0]
    return str(row.country_ja), [str(row.iso3)], str(row.region)


def _weighted_mean(df: pd.DataFrame, col: str, w: pd.Series) -> float | None:
    v = pd.to_numeric(df[col], errors="coerce")
    ok = v.notna() & (w > 0)
    return float((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else None


def explain(
    run_id: str,
    target: str,
    category: str,
    year: int,
    store: ForecastStore | None = None,
) -> dict[str, Any]:
    store = store or get_store()
    run = store.get_run(run_id)
    if not run:
        raise ValueError(f"run が見つかりません: {run_id}")
    slug = engine.normalize_category(category)
    if slug is None:
        raise ValueError(
            "要因分解は機種を1つ指定してください（general / mini / mining）"
        )
    year = int(year)
    name, isos, region = _targets(target)
    results = store.run_results(run_id)
    res = results[(results.category == slug) & results.iso3.isin(isos)]
    isos = sorted(res.iso3.unique())
    if not isos:
        raise ValueError(f"{name}の{category_ja(slug)}は予測対象外です")
    units_t = float(res[res.year == year].units.sum())
    act = data.demand_country_year()
    act = act[
        (act.category == data.CATEGORIES[slug])
        & (act.year == data.BASE_YEAR)
        & act.iso3.isin(isos)
    ]
    units_25 = float(act.units.sum())

    score = engine.score_frames_for(run, [slug])[slug]
    rows_t = (
        score[(score.year == year) & score.iso3.isin(isos)]
        .sort_values("iso3")
        .reset_index(drop=True)
    )
    train = data.train_data(slug)
    rows_25 = (
        train[(train.year == data.BASE_YEAR) & train.iso3.isin(isos)]
        .sort_values("iso3")
        .reset_index(drop=True)
    )
    w_t = rows_t.iso3.map(res[res.year == year].set_index("iso3").units).fillna(0)
    w_25 = rows_25.iso3.map(act.set_index("iso3").units).fillna(0)

    waterfall: list[dict[str, Any]] | None = None
    try:
        ex_t = predictor.explain(slug, rows_t)
        ex_25 = predictor.explain(slug, rows_25)
        pop_t = rows_t.set_index("iso3").population / 1e6
        pop_25 = rows_25.set_index("iso3").population / 1e6
        pred_t = pd.Series([e["prediction"] for e in ex_t], index=rows_t.iso3)
        pred_25 = pd.Series([e["prediction"] for e in ex_25], index=rows_25.iso3)
        # per-feature change of explanation strength, in units at target-year population
        contrib: dict[str, float] = {}
        for iso, e in zip(rows_t.iso3, ex_t, strict=True):
            for x in e["explanations"]:
                contrib[x["feature"]] = (
                    contrib.get(x["feature"], 0.0) + float(x["strength"]) * pop_t[iso]
                )
        for iso, e in zip(rows_25.iso3, ex_25, strict=True):
            for x in e["explanations"]:
                contrib[x["feature"]] = contrib.get(x["feature"], 0.0) - float(
                    x["strength"]
                ) * pop_t.get(iso, pop_25[iso])
        contrib.pop(
            "region", None
        )  # constant per country; its XEMP strength shift is not a driver
        ranked = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:5]
        m25 = float((pred_25 * pop_25).sum())
        mt = float((pred_t * pop_t).sum())
        pop_effect = float((pred_25 * (pop_t.reindex(pred_25.index) - pop_25)).sum())
        feat_sum = sum(c for _, c in ranked)
        waterfall = [
            {"label": "2025年実績", "value": round(units_25), "kind": "start"},
            {"label": "人口の変化", "value": round(pop_effect), "kind": "delta"},
            *[
                {"label": FEATURE_JA.get(f, f), "value": round(c), "kind": "delta"}
                for f, c in ranked
            ],
            {
                "label": "その他のモデル要因",
                "value": round(mt - m25 - pop_effect - feat_sum),
                "kind": "delta",
            },
            {
                "label": "後処理（起点補正・自動化・人による補正）",
                "value": round((units_t - mt) - (units_25 - m25)),
                "kind": "delta",
            },
            {"label": f"{year}年予測", "value": round(units_t), "kind": "end"},
        ]
        method = "prediction_explanations"
        method_ja = (
            "予測の説明（上位5件）の強さを2025年と目標年で比べ、目標年の人口で台数に換算して寄与としています。"
            "近似のため「その他のモデル要因」に残差を計上しています"
        )
    except predictor.PredictionError as e:
        fi = predictor.feature_impact(slug)
        ranked = [(f["feature"], f["impact"]) for f in fi if f["feature"] != "region"][
            :5
        ]
        method = "feature_impact"
        method_ja = f"予測の説明を取得できなかったため（{e}）、特徴量のインパクト（正規化値）を示しています。寄与の符号は含みません"
    top = []
    for feat, c in ranked:
        num = feat != "region"
        top.append({
            "feature": feat,
            "feature_ja": FEATURE_JA.get(feat, feat),
            "value_2025": round(v, 3) if num and (v := _weighted_mean(rows_25, feat, w_25)) is not None else None,
            "value_target_year": round(v, 3) if num and (v := _weighted_mean(rows_t, feat, w_t)) is not None else None,
            "contribution": round(float(c), 2 if method == "feature_impact" else 0),
        })  # fmt: skip

    # historical analogs: other countries at a similar income level
    gpc_t = float(
        (rows_t.gdp_pc_ppp * rows_t.population).sum() / rows_t.population.sum()
    )
    lo, hi = gpc_t * (1 - HISTORICAL_ANALOG_BAND), gpc_t * (1 + HISTORICAL_ANALOG_BAND)
    cand = train[~train.iso3.isin(isos) & train.gdp_pc_ppp.between(lo, hi)].copy()
    cand["dist"] = (cand.gdp_pc_ppp - gpc_t).abs()
    cand = (
        cand.sort_values("dist").drop_duplicates("iso3").head(HISTORICAL_ANALOG_COUNT)
    )
    names = data.country_master().set_index("iso3").country_ja
    analogs = [
        {"iso3": r.iso3, "country_ja": str(names.get(r.iso3, r.iso3)), "year": int(r.year),
         "gdp_pc_ppp": round(float(r.gdp_pc_ppp)), "units_per_mn_pop": round(float(r.units_per_mn_pop), 1)}
        for r in cand.itertuples()
    ]  # fmt: skip
    per_mn_t = units_t / (rows_t.population.sum() / 1e6) if len(rows_t) else None
    out = {
        "run_id": run_id,
        "target": name,
        "category": slug,
        "year": year,
        "units": round(units_t),
        "units_2025": round(units_25),
        "growth_vs_2025": engine.growth(units_t, units_25),
        "units_per_mn_pop_target_year": round(per_mn_t, 1) if per_mn_t else None,
        "gdp_pc_ppp_target_year": round(gpc_t),
        "top_drivers": top,
        "waterfall": waterfall,
        "historical_analogs": analogs,
        "factors_not_in_model": factors_not_in_model(region),
        "method": method,
        "method_ja": method_ja,
    }
    store.put(f"explanation:{run_id}|{name}|{slug}|{year}", out)
    store.put("explanation:latest", out)
    return out


# ---------------------------------------------------------------- comparison
def compare(
    run_ids: list[str],
    region: str | None,
    category: str | None,
    store: ForecastStore | None = None,
) -> dict[str, Any]:
    store = store or get_store()
    region = engine.normalize_region(region)
    category = engine.normalize_category(category)
    runs = []
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            raise ValueError(f"run が見つかりません: {rid}")
        runs.append((run, store.run_results(rid)))
    years = [data.BASE_YEAR, *data.FORECAST_YEARS]
    base_25 = engine.actual_2025(region, category)
    series_out = []
    for run, res in runs:
        s = engine.series(res, region, category)
        series_out.append({"run_id": run["run_id"], "label": run["label"],
                           "values": [round(base_25), *engine.as_float_list(s)],
                           "growth_2050_vs_2025": engine.growth(float(s[2050]), base_25)})  # fmt: skip
    table = []
    regions = [region] if region else data.REGIONS
    cats = [category] if category else list(data.CATEGORIES)
    for r in regions:
        for c in cats:
            first = None
            for run, res in runs:
                v = float(engine.series(res, r, c)[2050])
                if first is None:
                    first = v
                table.append({"region": r, "category": c, "run_id": run["run_id"], "units_2050": round(v),
                              "diff_vs_first_pct": round((v / first - 1) * 100, 1) if first else None})  # fmt: skip
    out = {"region": region or engine.WORLD, "category": category or "all", "years": years,
           "series": series_out, "table": table}  # fmt: skip
    store.put("comparison:latest", {**out, "run_ids": run_ids})
    return out


# ---------------------------------------------------------------- backtest / external
def backtest(category: str | None, region: str | None) -> dict[str, Any]:
    slug = engine.normalize_category(category)
    region = engine.normalize_region(region)
    slugs = [slug] if slug else list(data.CATEGORIES)
    frames = [(s, data.backtest_predictions(s)) for s in slugs]
    missing = [data.CATEGORIES[s] for s, f in frames if f is None]
    if missing:
        return {
            "status": "not_run",
            "train_period": "1995〜2005年",
            "years": [], "actual": [], "predicted": [], "mape_pct": None,
            "notes_ja": (
                f"過去検証は未実行です（{'、'.join(missing)}）。agent/demo_assets/run_backtest.py を実行すると "
                f"data/backtest_predictions_*.csv が作成され、ここに表示されます。{BACKTEST_NOTE}"
            ),
        }  # fmt: skip
    d = pd.concat([f for _, f in frames if f is not None])
    if region:
        d = d[d.region == region]
    g = d.groupby("year")[["units_actual", "units_pred"]].sum()
    mape = float(((g.units_pred - g.units_actual).abs() / g.units_actual).mean() * 100)
    return {
        "status": "ok",
        "train_period": "1995〜2005年",
        "years": [int(y) for y in g.index],
        "actual": engine.as_float_list(g.units_actual),
        "predicted": engine.as_float_list(g.units_pred),
        "mape_pct": round(mape, 1),
        "notes_ja": BACKTEST_NOTE,
    }


def external(region: str | None) -> list[dict[str, Any]]:
    ext = data.external_forecast()
    r = engine.normalize_region(region)
    if r:
        ext = ext[ext.region == r]
    return [
        {"region": x.region, "growth_2030_vs_2025_pct": float(x.growth_2030_vs_2025_pct),
         "growth_2040_vs_2025_pct": float(x.growth_2040_vs_2025_pct),
         "growth_2050_vs_2025_pct": float(x.growth_2050_vs_2025_pct), "note": x.note}
        for x in ext.itertuples()
    ]  # fmt: skip
