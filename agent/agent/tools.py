"""LangChain tools for the long-term demand forecast / scenario analysis agent.

Every tool returns a JSON string. Errors are returned as ``{"error": ...}`` with a
sanitised, user-safe message (never a raw exception: DataRobot SDK errors can
contain the API token).
"""

import functools
import json
import logging
import secrets
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.forecast import analysis, data, engine, predictor
from agent.forecast.store import get_store, now_iso
from agent.forecast.warmup import start_background_warmup, wait_until_ready

logger = logging.getLogger(__name__)

DriverName = Literal[
    "gdp_growth_shift_pt",
    "urban_pct_shift_pt",
    "gfcf_pct_gdp",
    "coal_growth_rate",
    "copper_price_change_rate",
    "ironore_price_change_rate",
    "coal_price_change_rate",
    "gold_price_change_rate",
]


class DriverOverride(BaseModel):
    target: str = Field(
        description="国コード(iso3)、地域名（例: アフリカ）、または world。資源価格は world のみ"
    )
    driver: DriverName = Field(
        description=(
            "gdp_growth_shift_pt=実質GDP成長率の上乗せ(ポイント) / urban_pct_shift_pt=都市化率の上乗せ(ポイント) / "
            "gfcf_pct_gdp=投資比率を value(%) へ5年で移行 / coal_growth_rate=石炭生産量の年率 / "
            "*_price_change_rate=資源価格(実質)の年率"
        )
    )
    value: float = Field(
        description="年率は小数（0.03=年3%）、_pt はポイント、gfcf_pct_gdp は%水準"
    )
    from_year: int = Field(default=2026, description="適用開始年")
    to_year: int | None = Field(
        default=None,
        description="適用終了年（例: 今後10年なら2035）。省略時は2050年まで",
    )


class LeverOverrides(BaseModel):
    L1_automation: float | None = Field(
        default=None, description="自動化による必要台数の年率減少（0.003=0.3%）"
    )
    L2_china_peak: float | None = Field(
        default=None, description="中国の固定資本形成比の2050年水準(%)"
    )
    L3_emerging_timing: int | None = Field(
        default=None, description="インド・アフリカ立ち上がりの前倒し年数（負は後ずれ）"
    )
    L4_idn_coal: Literal["回復あり", "回復なし"] | None = Field(
        default=None, description="インドネシア石炭需要の回復"
    )


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=float)


def _safe(fn: Callable[..., Any]) -> Callable[..., str]:
    """Wrap a tool body: JSON result, user-safe error messages."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return _json(fn(*args, **kwargs))
        except (ValueError, predictor.PredictionError) as e:
            return _json({"error": predictor.sanitize(str(e))})
        except Exception as e:  # noqa: BLE001
            logger.exception("tool %s failed", fn.__name__)
            return _json(
                {"error": f"処理中にエラーが発生しました（{type(e).__name__}）"}
            )

    return wrapper


def _dump(x: Any) -> Any:
    return x.model_dump() if isinstance(x, BaseModel) else x


def _ensure_ready() -> None:
    start_background_warmup()
    store = get_store()
    if not store.get_run(engine.base_run_id("S1_BASE")):
        wait_until_ready(timeout=90)


def _run_brief(run: dict[str, Any]) -> dict[str, Any]:
    return {
        k: run.get(k)
        for k in (
            "run_id",
            "label",
            "scenario_id",
            "kind",
            "base_run_id",
            "source",
            "created_at",
        )
    }


# ---------------------------------------------------------------------- tools
@tool
@_safe
def list_scenarios() -> Any:
    """4つのシナリオ（ベース・脱炭素加速・分断世界・高成長・化石依存）の定義とレバーL1〜L4の既定値、
    これまでに作成済みの run 一覧を返す。scenario_id や run_id が分からないときに最初に使う。"""
    _ensure_ready()
    defs = data.scenario_definitions()
    scenarios = [
        {
            "scenario_id": r.scenario_id,
            "scenario_ja": r.scenario_ja,
            "ssp_reference": r.ssp_reference,
            "energy_reference": r.energy_reference,
            "narrative": r.narrative,
            "levers": data.lever_defaults(r.scenario_id),
        }
        for r in defs.itertuples()
    ]
    return {
        "scenarios": scenarios,
        "existing_runs": [_run_brief(r) for r in get_store().list_runs()],
        "available_categories": {
            s: data.CATEGORIES[s] for s in data.load_deployments()
        },
    }


@tool
@_safe
def run_forecast(
    scenario_id: str,
    driver_overrides: list[DriverOverride] | None = None,
    lever_overrides: LeverOverrides | None = None,
    label: str | None = None,
) -> Any:
    """シナリオの需要予測（2026〜2050年、国×年×機種）を実行し、run_id と要約を返す。
    前提を変えない場合はキャッシュ済みのベース予測を即座に返す。driver_overrides / lever_overrides で
    what-if を作ると新しい run_id が発行され、画面の run 選択肢にも反映される。
    summary.world は世界合計、summary.by_region は地域×機種（台数と2025年比の倍率）。"""
    _ensure_ready()
    run = engine.run_forecast(
        scenario_id,
        driver_overrides=[_dump(o) for o in driver_overrides or []],
        lever_overrides=_dump(lever_overrides) if lever_overrides else None,
        label=label,
    )
    out: dict[str, Any] = {
        "run_id": run["run_id"],
        "summary": engine.compact_summary(run["summary"]),
    }
    if run.get("warnings"):
        out["warnings"] = run["warnings"]
    return out


@tool
@_safe
def compare_scenarios(
    run_ids: list[str], region: str | None = None, category: str | None = None
) -> Any:
    """複数の run を比較する。region（地域名、省略で世界）と category（general/mini/mining、省略で全機種）で
    絞り込んだ年次の台数推移と、2050年の地域×機種の差分表（先頭の run との差 %）を返す。"""
    return analysis.compare(run_ids, region, category)


@tool
@_safe
def explain_forecast(run_id: str, target: str, category: str, year: int = 2050) -> Any:
    """予測の要因分解。target は国コード・地域名・world（世界全体）、category は general/mini/mining。
    2025年→目標年の変化を主要ドライバーの寄与（台数）に分解した waterfall、上位ドライバーの値、
    同じ所得水準に達した他国の過去事例（historical_analogs）、モデルに含まれていない要因を返す。"""
    return analysis.explain(run_id, target, category, year)


@tool
@_safe
def detect_forecast_issues(run_id: str) -> Any:
    """run の結果を点検し、違和感（外部予測との乖離、急成長・急減、学習範囲外の入力、モデル外の要因）を返す。
    結果を示すたびに使う。指摘するだけで、補正は実行しない。"""
    store = get_store()
    run = store.get_run(run_id)
    if not run:
        raise ValueError(f"run が見つかりません: {run_id}")
    issues = analysis.detect_issues(run, store.run_results(run_id))
    store.put(f"issues:{run_id}", issues)
    return {"run_id": run_id, "issues": issues}


@tool
@_safe
def apply_human_adjustment(
    base_run_id: str,
    region: str,
    category: str,
    factor: float,
    start_year: int = 2026,
    ramp_years: int = 5,
    rationale: str = "",
    adjusted_by: str = "",
) -> Any:
    """人（利用者）が指示した前提補正を記録して再計算する。利用者が補正を明示的に指示したときだけ使う。
    factor は補正係数（0.7=3割減）、start_year から ramp_years かけて係数まで移行する。
    rationale（理由）と adjusted_by（補正者）が空の場合は実行せず、利用者に尋ねる。元の run は残る。"""
    if not rationale.strip() or not adjusted_by.strip():
        missing = [
            n
            for n, v in (
                ("理由（rationale）", rationale),
                ("補正者（adjusted_by）", adjusted_by),
            )
            if not v.strip()
        ]
        return {
            "status": "needs_input",
            "message_ja": f"判断履歴に残すため、{'と'.join(missing)}を教えてください。補正はまだ実行していません。",
        }
    store = get_store()
    base = store.get_run(base_run_id)
    if not base:
        raise ValueError(f"run が見つかりません: {base_run_id}")
    reg = engine.normalize_region(region)
    slug = engine.normalize_category(category)
    if not reg or not slug:
        raise ValueError("補正は地域と機種を1つずつ指定してください")
    if not 0 < factor <= 3:
        raise ValueError(
            "factor は 0 より大きく 3 以下で指定してください（0.7 = 3割減）"
        )
    adj = {"region": reg, "category": slug, "factor": float(factor),
           "start_year": int(start_year), "ramp_years": max(int(ramp_years), 1)}  # fmt: skip
    label = f"{base['label']}＋補正（{reg} {data.CATEGORIES[slug]} ×{factor:g}）"
    new_run, before, after = engine.adjust_run(base, adj, label, store)
    b = engine.series(before, reg, slug)
    a = engine.series(after, reg, slug)
    entry = {
        "log_id": f"adj-{secrets.token_hex(4)}",
        "timestamp": now_iso(),
        "adjusted_by": adjusted_by.strip(),
        "rationale": rationale.strip(),
        "base_run_id": base_run_id,
        "new_run_id": new_run["run_id"],
        **adj,
    }
    store.add_adjustment(entry)
    return {
        "new_run_id": new_run["run_id"],
        "before_after": {
            "region": reg,
            "category": slug,
            "before": [
                {"year": y, "units": round(float(b[y]))} for y in data.FORECAST_YEARS
            ],
            "after": [
                {"year": y, "units": round(float(a[y]))} for y in data.FORECAST_YEARS
            ],
            "world_total_2050_before": round(
                float(engine.series(before, None, slug)[2050])
            ),
            "world_total_2050_after": round(
                float(engine.series(after, None, slug)[2050])
            ),
        },
        "log_entry": entry,
    }


@tool
@_safe
def get_adjustment_log() -> Any:
    """これまでの人による補正の履歴（誰が・いつ・どの地域／機種を・どれだけ・なぜ）を返す。"""
    return {"log": get_store().adjustment_log()}


@tool
@_safe
def get_uncertainty_band(
    run_id: str, region: str | None = None, category: str | None = None
) -> Any:
    """予測の幅（P10/P50/P90）を返す。各機種のホールドアウト期間（2021〜2025年）の相対誤差を
    予測年数の平方根に比例して広げる方法。確率を保証するものではない。"""
    store = get_store()
    if not store.get_run(run_id):
        raise ValueError(f"run が見つかりません: {run_id}")
    reg, slug = engine.normalize_region(region), engine.normalize_category(category)
    return analysis.band(
        store.run_results(run_id), reg, slug, analysis.error_per_5y(store)
    )


@tool
@_safe
def get_backtest_result(category: str | None = None, region: str | None = None) -> Any:
    """過去検証：1995〜2005年のデータだけで学習したモデルで2006〜2025年を予測した結果と実績の比較。
    未実行の場合は status=not_run を返す。説明時は notes_ja の注意書きを必ず添える。"""
    return analysis.backtest(category, region)


@tool
@_safe
def get_external_forecast(region: str | None = None) -> Any:
    """外部の長期需要予測（比較用のダミー値）の地域別成長率（2025年比 %）を返す。"""
    return {"external": analysis.external(region)}


SUMMARY_SYSTEM = (
    "あなたは建設機械メーカーの経営企画担当です。与えられた数値だけを使い、経営会議向けに簡潔な日本語で書きます。"
    "数値を創作しないこと。投資判断を断定的に推奨しないこと。需要実績は架空のダミーデータであることを前提にしてください。"
)


def _summary_facts(run_ids: list[str]) -> dict[str, Any]:
    store = get_store()
    runs = []
    for rid in run_ids:
        run = store.get_run(rid)
        if not run:
            raise ValueError(f"run が見つかりません: {rid}")
        runs.append(run)
    table = []
    for run in runs:
        world = {w["category"]: w for w in run["summary"]["world"]}
        res = store.run_results(run["run_id"])
        total_25 = engine.actual_2025(None, None)
        total_50 = float(engine.series(res, None, None)[2050])
        by_region = sorted(
            (
                (
                    r,
                    engine.growth(
                        float(engine.series(res, r, None)[2050]),
                        engine.actual_2025(r, None),
                    ),
                )
                for r in data.REGIONS
            ),
            key=lambda x: -(x[1] or 0),
        )
        table.append({
            "run_id": run["run_id"], "label": run["label"],
            "world_units_2050": round(total_50), "world_growth_2050": engine.growth(total_50, total_25),
            "growth_2050_by_category": {data.CATEGORIES[c]: w["growth_2050_vs_2025"] for c, w in world.items()},
            "fastest_region": by_region[0], "slowest_region": by_region[-1],
            "applied_overrides": run.get("applied_overrides") or [],
        })  # fmt: skip
    issues = store.get(f"issues:{runs[0]['run_id']}") or []
    log = [
        e
        for e in store.adjustment_log()
        if e["new_run_id"] in run_ids or e["base_run_id"] in run_ids
    ]
    return {
        "runs": table,
        "issues": [i for i in issues if i["severity"] != "low"][:6],
        "adjustments": log,
    }


def _markdown(facts: dict[str, Any], llm_text: dict[str, str], audience: str) -> str:
    lines = [f"# 建機 長期需要見通し（2050年）— {audience}向けサマリー", ""]
    lines += ["## 結論", llm_text.get("conclusion", "").strip(), ""]
    lines += ["## シナリオ別の2050年見通し", "", "倍率はいずれも2025年実績比。", "",
              "| シナリオ | 世界計 | 一般建機 | ミニショベル | 鉱山機械 | 伸び最大／最小の地域 |",
              "|---|---|---|---|---|---|"]  # fmt: skip
    for r in facts["runs"]:
        g = r["growth_2050_by_category"]

        def cell(k: str, g: dict[str, Any] = g) -> str:
            return f"{g[k]:.2f}倍" if g.get(k) else "準備中"

        lines.append(
            f"| {r['label']} | {r['world_units_2050'] / 1000:,.0f}千台（{r['world_growth_2050']:.2f}倍） | "
            f"{cell('一般建機')} | {cell('ミニショベル')} | {cell('鉱山機械')} | "
            f"{r['fastest_region'][0]} {r['fastest_region'][1]:.1f}倍／{r['slowest_region'][0]} {r['slowest_region'][1]:.1f}倍 |"
        )
    lines += ["", "## 主要な要因", llm_text.get("drivers", "").strip(), ""]
    lines += ["## 人による補正とその理由"]
    if facts["adjustments"]:
        lines += [
            "",
            "| 日時 | 補正者 | 地域 | 機種 | 係数 | 開始年／移行年数 | 理由 |",
            "|---|---|---|---|---|---|---|",
        ]
        for e in facts["adjustments"]:
            lines.append(
                f"| {e['timestamp'][:16].replace('T', ' ')} | {e['adjusted_by']} | {e['region']} | "
                f"{data.CATEGORIES.get(e['category'], e['category'])} | ×{e['factor']:g} | "
                f"{e['start_year']}年／{e['ramp_years']}年 | {e['rationale']} |"
            )
    else:
        lines.append("本日の議論では、人による補正は行っていません。")
    lines += ["", "## 前提と限界",
              "- 需要の実績値はデモ用の架空データです。人口・GDPなどのドライバーは公開データ（世界銀行、Our World in Data）、将来前提は公開の長期シナリオを参考にした設定値です。",
              "- モデルに含まれていない主な要因：" + "、".join(analysis.COMMON_FACTORS) + "、および地域固有の要因（中古機の流入、政策ショック、制裁・地政学リスクなど）。",
              "- 予測の幅（P10〜P90）は不確実性の目安であり、確率を保証するものではありません。",
              "- 過去検証は前提に実際の値を使った検証であり、モデルの構造の妥当性を示すものです。",
              "", "## 次のアクション", llm_text.get("next_actions", "").strip(), ""]  # fmt: skip
    return "\n".join(lines)


def make_executive_summary_tool(llm: BaseChatModel) -> BaseTool:
    """The summary tool needs the NAT-provided LLM (DataRobot LLM Gateway) for its prose."""

    @tool
    @_safe
    def generate_executive_summary(
        run_ids: list[str], audience: str = "経営会議"
    ) -> Any:
        """選んだ run（シナリオや補正後の run）と補正履歴をもとに、経営会議向けの1枚サマリーを Markdown で作成する。
        構成は 結論（3行）／シナリオ別の2050年見通し（表）／主要な要因／人による補正とその理由／前提と限界／次のアクション。
        画面「経営会議サマリー」でプレビューと PDF ダウンロードができる。"""
        facts = _summary_facts(run_ids)
        prompt = (
            f"読み手: {audience}\n次の事実（JSON）だけを使って、3つのセクションの本文を書いてください。\n"
            '出力は JSON で {"conclusion": "3行の箇条書き（各行は「- 」で始める）", '
            '"drivers": "主要な要因の箇条書き3〜5行", "next_actions": "次のアクションの箇条書き3行"} のみ。\n'
            f"事実: {_json(facts)}"
        )
        text: dict[str, str] = {}
        try:
            # "nostream" keeps this internal drafting call out of the chat stream
            resp = llm.with_config(tags=["nostream"]).invoke(
                [SystemMessage(content=SUMMARY_SYSTEM), HumanMessage(content=prompt)]
            )
            raw = str(resp.content if isinstance(resp.content, str) else "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in resp.content))  # fmt: skip
            text = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001 - fall back to a data-only summary
            logger.warning("summary LLM step failed: %s", type(e).__name__)
            r0 = facts["runs"][0]
            text = {
                "conclusion": f"- {r0['label']}では、2050年の世界需要は2025年比 {r0['world_growth_2050']:.2f}倍の見通しです。",
                "drivers": "- 詳細はチャットで要因分解を確認してください。",
                "next_actions": "- 違和感の指摘された地域について、前提補正の要否を確認する。",
            }
        md = _markdown(facts, text, audience)
        summary_id = f"sum-{secrets.token_hex(4)}"
        store = get_store()
        record = {
            "summary_id": summary_id,
            "created_at": now_iso(),
            "run_ids": run_ids,
            "audience": audience,
            "markdown": md,
        }
        store.put(f"summary:{summary_id}", record)
        store.put("summary:latest", record)
        return {"summary_markdown": md, "download_path": f"/summary?id={summary_id}"}

    return generate_executive_summary


def build_tools(llm: BaseChatModel) -> list[BaseTool]:
    start_background_warmup()
    return [
        list_scenarios,
        run_forecast,
        compare_scenarios,
        explain_forecast,
        detect_forecast_issues,
        apply_human_adjustment,
        get_adjustment_log,
        get_uncertainty_band,
        get_backtest_result,
        get_external_forecast,
        make_executive_summary_tool(llm),
    ]
