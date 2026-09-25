"""Offline tests for the forecast engine (DataRobot calls are mocked)."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from agent.forecast import analysis, data, engine, overrides, predictor, scenarios
from agent.forecast.scoring_data import build_score_frame
from agent.forecast.store import ForecastStore

ASSETS = Path(__file__).resolve().parents[1] / "demo_assets"


def fake_predict_many(scores: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """Deterministic stand-in for the deployments: per-capita demand grows with income."""
    out = {}
    for slug, s in scores.items():
        base = data.train_data(slug)
        per_mn = base[base.year == data.BASE_YEAR].set_index("iso3").units_per_mn_pop
        gpc = base[base.year == data.BASE_YEAR].set_index("iso3").gdp_pc_ppp
        v = s.iso3.map(per_mn) * (s.gdp_pc_ppp / s.iso3.map(gpc)) ** 0.8
        out[slug] = pd.Series(v.to_numpy(), index=s.index)
    return out


@pytest.fixture(autouse=True)
def isolated_store_path(tmp_path: Path, monkeypatch):
    """Never touch the real <repo>/.data store from tests."""
    monkeypatch.setenv("FORECAST_STORE_PATH", str(tmp_path / "default.sqlite"))


@pytest.fixture
def store(tmp_path: Path) -> ForecastStore:
    return ForecastStore(tmp_path / "store.sqlite")


@pytest.fixture
def mocked_dr():
    with (
        patch(
            "agent.forecast.engine.predictor.predict_many",
            side_effect=fake_predict_many,
        ),
        patch(
            "agent.forecast.engine.data.load_deployments",
            return_value={s: {"deployment_id": "x"} for s in data.CATEGORIES},
        ),
    ):
        yield


# ---------------------------------------------------------------- data layer
def test_features_and_postprocess_are_unchanged_copies():
    """Training-time logic must be reused verbatim."""
    pkg = Path(__file__).resolve().parents[1] / "agent" / "forecast"
    for name in ("features.py", "postprocess.py"):
        assert (pkg / name).read_text(encoding="utf-8") == (ASSETS / name).read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize("scenario_id", data.SCENARIO_IDS)
def test_generator_reproduces_file_08(scenario_id):
    ref = data.future_drivers()
    ref = (
        ref[ref.scenario_id == scenario_id]
        .sort_values(["iso3", "year"])
        .reset_index(drop=True)
    )
    got = (
        scenarios.generate_future_drivers(scenario_id)
        .round(4)
        .sort_values(["iso3", "year"])
        .reset_index(drop=True)
    )
    num = [c for c in ref.columns if ref[c].dtype.kind == "f"]
    assert (got[num] - ref[num]).abs().max().max() == 0
    assert list(got.columns) == list(ref.columns)


@pytest.mark.parametrize("slug", list(data.CATEGORIES))
def test_score_frames_match_precomputed(slug):
    ref = data.precomputed_score(slug)
    ref = (
        ref[ref.scenario_id == "S1_BASE"]
        .sort_values(["iso3", "year"])
        .reset_index(drop=True)
    )
    got = build_score_frame(scenarios.generate_future_drivers("S1_BASE").round(4), slug)
    got = got.sort_values(["iso3", "year"]).reset_index(drop=True)
    num = [c for c in ref.columns if ref[c].dtype.kind in "fi"]
    assert (got[num] - ref[num]).abs().max().max() == 0


def test_levers_change_structural_drivers():
    base = scenarios.generate_future_drivers("S1_BASE")
    lev = scenarios.resolve_levers(
        "S1_BASE", {"L2_china_peak": 25, "L4_idn_coal": "回復あり"}
    )
    alt = scenarios.generate_future_drivers("S1_BASE", lev)
    chn = lambda d: d[(d.iso3 == "CHN") & (d.year == 2050)].gfcf_pct_gdp.iloc[0]  # noqa: E731
    idn = lambda d: d[(d.iso3 == "IDN") & (d.year == 2050)].coal_prod_twh.iloc[0]  # noqa: E731
    assert chn(alt) < chn(base)
    assert idn(alt) > idn(base)
    with pytest.raises(ValueError):
        scenarios.resolve_levers("S1_BASE", {"L9": 1})


def test_price_override_window_and_derived_columns():
    fut = scenarios.generate_future_drivers("S1_BASE")
    o = [
        {
            "target": "world",
            "driver": "copper_price_change_rate",
            "value": 0.03,
            "from_year": 2026,
            "to_year": 2035,
        }
    ]
    new = overrides.apply_driver_overrides(fut, o)
    c = new[new.iso3 == "USA"].set_index("year").copper_usd_t_real2010
    assert c[2035] / c[2034] == pytest.approx(1.03)
    b = fut[fut.iso3 == "USA"].set_index("year").copper_usd_t_real2010
    assert c[2040] / c[2039] == pytest.approx(
        b[2040] / b[2039]
    )  # base path resumes after to_year


def test_gdp_shift_recomputes_derived():
    fut = scenarios.generate_future_drivers("S1_BASE")
    new = overrides.apply_driver_overrides(
        fut,
        [
            {
                "target": "NGA",
                "driver": "gdp_growth_shift_pt",
                "value": 1.0,
                "from_year": 2030,
            }
        ],
    )
    n = new[new.iso3 == "NGA"].set_index("year")
    f = fut[fut.iso3 == "NGA"].set_index("year")
    assert n.gdp_growth_pct[2029] == pytest.approx(f.gdp_growth_pct[2029])
    assert n.gdp_growth_pct[2030] == pytest.approx(
        f.gdp_growth_pct[2030] + 1.0, abs=0.05
    )
    assert n.gdp_ppp_bn[2050] == pytest.approx(
        n.gdp_pc_ppp_const2021[2050] * n.population[2050] / 1e9
    )
    other = new[new.iso3 == "USA"].gdp_pc_ppp_const2021.to_numpy()
    assert (
        other
        == fut[fut.iso3 == "USA"].sort_values("year").gdp_pc_ppp_const2021.to_numpy()
    ).all()


def test_urban_shift_is_capped():
    fut = scenarios.generate_future_drivers("S1_BASE")
    new = overrides.apply_driver_overrides(
        fut,
        [
            {
                "target": "日本",
                "driver": "urban_pct_shift_pt",
                "value": 50,
                "from_year": 2026,
            }
        ],
    )
    assert new[new.iso3 == "JPN"].urban_pct.max() <= overrides.URBAN_CAP_PCT


def test_invalid_overrides_rejected():
    with pytest.raises(ValueError):
        overrides.validate(
            [
                {
                    "target": "アフリカ",
                    "driver": "copper_price_change_rate",
                    "value": 0.03,
                }
            ]
        )
    with pytest.raises(ValueError):
        overrides.validate(
            [{"target": "Atlantis", "driver": "gdp_growth_shift_pt", "value": 1}]
        )


# ---------------------------------------------------------------- engine
def test_base_run_is_cached_and_continuous(store, mocked_dr):
    run = engine.run_forecast("ベース", store=store)
    assert run["run_id"] == "base-S1_BASE" and run["source"] == "datarobot"
    res = store.run_results(run["run_id"])
    for slug in data.CATEGORIES:
        # jump-off correction: no step between 2025 actual and the 2026 forecast
        ratio = float(engine.series(res, None, slug)[2026]) / engine.actual_2025(
            None, slug
        )
        assert 0.9 < ratio < 1.1
    with patch("agent.forecast.engine.predictor.predict_many") as p:
        again = engine.run_forecast("S1_BASE", store=store)
        p.assert_not_called()
    assert again["run_id"] == run["run_id"]
    assert store.get(f"issues:{run['run_id']}") is not None
    assert "世界|all" in store.get(f"bands:{run['run_id']}")


def test_whatif_gets_new_run_id(store, mocked_dr):
    engine.run_forecast("S1_BASE", store=store)
    w = engine.run_forecast(
        "S1_BASE", lever_overrides={"L1_automation": 0.01}, store=store
    )
    assert w["run_id"].startswith("run-") and w["kind"] == "whatif"
    assert w["summary"]["applied_overrides"]
    base_50 = store.get_run("base-S1_BASE")["summary"]["world"][0]["units_2050"]
    assert w["summary"]["world"][0]["units_2050"] < base_50


def test_prediction_failure_falls_back_to_cache(store, mocked_dr):
    engine.run_forecast("S1_BASE", store=store)
    with patch(
        "agent.forecast.engine.predictor.predict_many",
        side_effect=predictor.PredictionError("HTTP 503"),
    ):
        out = engine.run_forecast(
            "S1_BASE",
            driver_overrides=[
                {"target": "world", "driver": "gold_price_change_rate", "value": 0.02}
            ],
            store=store,
        )
    assert out["source"] == "cache" and out["summary"]["source"] == "cache"
    assert any("反映されていません" in w for w in out["warnings"])


def test_missing_deployment_shown_as_unavailable(store):
    with (
        patch(
            "agent.forecast.engine.predictor.predict_many",
            side_effect=fake_predict_many,
        ),
        patch(
            "agent.forecast.engine.data.load_deployments",
            return_value={"general": {"deployment_id": "x"}},
        ),
    ):
        run = engine.run_forecast("S2_NETZERO", store=store)
    assert set(run["summary"]["unavailable_categories"]) == {"ミニショベル", "鉱山機械"}


def test_human_adjustment_keeps_original_run(store, mocked_dr):
    base = engine.run_forecast("S1_BASE", store=store)
    adj = {
        "region": "アフリカ",
        "category": "general",
        "factor": 0.7,
        "start_year": 2026,
        "ramp_years": 5,
    }
    new, before, after = engine.adjust_run(base, adj, "補正", store)
    b, a = (
        engine.series(before, "アフリカ", "general"),
        engine.series(after, "アフリカ", "general"),
    )
    assert a[2050] == pytest.approx(b[2050] * 0.7)
    assert a[2026] == pytest.approx(b[2026] * (1 - 0.3 / 5))
    other_b, other_a = (
        engine.series(before, "中国", "general"),
        engine.series(after, "中国", "general"),
    )
    assert (other_a == other_b).all()
    assert (
        store.get_run(base["run_id"]) is not None
        and new["base_run_id"] == base["run_id"]
    )


# ---------------------------------------------------------------- analysis
def test_issue_detection_separates_basis_and_missing_factors(store, mocked_dr):
    run = engine.run_forecast("S1_BASE", store=store)
    issues = analysis.detect_issues(run, store.run_results(run["run_id"]))
    assert issues, "expected at least one issue"
    assert {i["severity"] for i in issues} <= {"high", "medium", "low"}
    for i in issues:
        if i["type"] in ("external_gap", "extreme_growth"):
            assert (
                "【モデルの根拠】" in i["message_ja"]
                and "【モデルが考慮していない要因】" in i["message_ja"]
            )


def test_band_widens_with_horizon(store, mocked_dr):
    run = engine.run_forecast("S1_BASE", store=store)
    b = analysis.band(
        store.run_results(run["run_id"]), None, "general", analysis.error_per_5y(store)
    )
    w = [
        (hi - lo) / mid
        for lo, mid, hi in zip(b["p10"], b["p50"], b["p90"], strict=True)
    ]
    assert w[0] < w[-1]
    assert b["method"].startswith("holdout_error")


def test_backtest_not_run_message():
    out = analysis.backtest("general", None)
    if out["status"] == "not_run":
        assert "未実行" in out["notes_ja"]
    assert "モデルの構造の妥当性" in out["notes_ja"]


def test_sanitize_removes_token(monkeypatch):
    monkeypatch.setenv("DATAROBOT_API_TOKEN", "secret-token-value-1234567890")
    msg = predictor.sanitize(
        'provided token of "secret-token-value-1234567890" and endpoint'
    )
    assert "secret-token-value" not in msg


# ---------------------------------------------------------------- tools
def test_adjustment_tool_requires_rationale(store, mocked_dr, monkeypatch):
    from agent import tools

    monkeypatch.setattr(tools, "get_store", lambda: store)
    engine.run_forecast("S1_BASE", store=store)
    out = json.loads(tools.apply_human_adjustment.invoke(
        {"base_run_id": "base-S1_BASE", "region": "アフリカ", "category": "general", "factor": 0.7}
    ))  # fmt: skip
    assert out["status"] == "needs_input"
    assert store.adjustment_log() == []
    out = json.loads(tools.apply_human_adjustment.invoke({
        "base_run_id": "base-S1_BASE", "region": "アフリカ", "category": "general", "factor": 0.7,
        "rationale": "中古機輸入比率の高さ", "adjusted_by": "経営管理部",
    }))  # fmt: skip
    assert out["new_run_id"].startswith("run-")
    log = store.adjustment_log()
    assert len(log) == 1 and log[0]["rationale"] == "中古機輸入比率の高さ"
    # persisted: a fresh store object on the same file still sees the log
    assert len(ForecastStore(store.path).adjustment_log()) == 1


def test_tool_errors_are_json(store, monkeypatch):
    from agent import tools

    monkeypatch.setattr(tools, "get_store", lambda: store)
    out = json.loads(tools.detect_forecast_issues.invoke({"run_id": "nope"}))
    assert "error" in out


def test_deployments_files_parse(tmp_path, monkeypatch):
    """_comment is ignored; placeholder IDs count as 「準備中」; only 3 keys are needed."""
    example = json.loads(
        (ASSETS / "deployments.example.json").read_text(encoding="utf-8")
    )
    assert "_comment" in example
    for slug in data.CATEGORIES:
        assert set(example[slug]) == {"project_id", "model_id", "deployment_id"}
    fake = tmp_path / "demo_assets"
    fake.mkdir()
    (fake / "deployments.json").write_text(
        json.dumps(
            {
                **example,
                "mini": {"project_id": "p", "model_id": "m", "deployment_id": "d1"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(data, "ASSETS_DIR", fake)
    monkeypatch.delenv("DEPLOYMENT_ID_GENERAL", raising=False)
    deps = data.load_deployments()
    assert list(deps) == ["mini"] and deps["mini"]["deployment_id"] == "d1"
    monkeypatch.setenv("DEPLOYMENT_ID_GENERAL", "env-id")
    assert data.load_deployments()["general"]["deployment_id"] == "env-id"


# ---------------------------------------------------------------- DataRobot-hosted store (deployed mode)
class FakeDataRobot:
    """Minimal stand-in for the Files API + Key-Value API used by remote_store."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.kv: dict[tuple[str, str], "FakeDataRobot.KV"] = {}
        outer = self

        class KV:
            def __init__(self, entity_id, name, value):
                self.entity_id, self.name, self.value = entity_id, name, value

            def update(self, value=None, **_):
                self.value = value

            @staticmethod
            def find(entity_id, entity_type, name):
                return outer.kv.get((entity_id, name))

            @staticmethod
            def create(
                entity_id,
                entity_type,
                name,
                category,
                value_type,
                value,
                description=None,
            ):
                outer.kv[(entity_id, name)] = KV(entity_id, name, value)
                return outer.kv[(entity_id, name)]

        self.KV = KV

    # client API
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, files=None, data=None, timeout=None):
        cid = f"cat{len(self.files) + 1}"
        self.files[cid] = files["file"][1].read()
        return type("R", (), {"json": lambda _self: {"catalogId": cid}})()

    def get(self, url, timeout=None):
        cid = url.split("/")[1]
        return type("R", (), {"content": self.files[cid]})()

    def delete(self, url):
        self.files.pop(url.split("/")[1], None)


@pytest.fixture
def fake_dr(monkeypatch):
    import datarobot as dr

    from agent.forecast import remote_store

    fake = FakeDataRobot()
    monkeypatch.setattr(remote_store, "_client", lambda: fake)
    monkeypatch.setattr(dr, "KeyValue", fake.KV)
    return fake


def test_remote_sync_push_and_pull(tmp_path, fake_dr, mocked_dr):
    from agent.forecast.remote_store import DataRobotStoreSync

    local = tmp_path / "a" / "forecast_store.sqlite"
    sync = DataRobotStoreSync("dep-agent", local, background=False)
    st = ForecastStore(local, sync=sync)
    engine.run_forecast("S1_BASE", store=st)
    st.add_adjustment({"log_id": "adj-1", "timestamp": "t", "adjusted_by": "経営管理部", "region": "アフリカ",
                       "category": "general", "factor": 0.7, "start_year": 2026, "ramp_years": 5,
                       "rationale": "理由", "base_run_id": "base-S1_BASE", "new_run_id": "run-x"})  # fmt: skip
    assert sync.flush()
    assert len(fake_dr.files) == 1, "old store files are deleted after each push"
    # a new container (fresh working copy) restores everything from DataRobot
    other = tmp_path / "b" / "forecast_store.sqlite"
    restored = ForecastStore(
        other, sync=DataRobotStoreSync("dep-agent", other, background=False)
    )
    assert restored.get_run("base-S1_BASE") is not None
    assert restored.adjustment_log()[0]["rationale"] == "理由"


def test_store_mode_switches_on_deployment_env(monkeypatch, tmp_path, fake_dr):
    from agent.forecast import remote_store, store

    monkeypatch.delenv("FORECAST_STORE_PATH", raising=False)
    monkeypatch.delenv("MLOPS_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("FORECAST_STORE_DEPLOYMENT_ID", raising=False)
    assert store.default_store_path().name == "forecast_store.sqlite"
    assert ".data" in str(store.default_store_path())  # local checkout
    monkeypatch.setenv("MLOPS_DEPLOYMENT_ID", "dep-agent")
    monkeypatch.setattr(
        remote_store,
        "remote_local_path",
        lambda: tmp_path / "rt" / "forecast_store.sqlite",
    )
    monkeypatch.setattr(
        store, "remote_local_path", lambda: tmp_path / "rt" / "forecast_store.sqlite"
    )
    monkeypatch.setattr(store, "_store", None)
    s = store.get_store()
    assert s.sync is not None and s.sync.deployment_id == "dep-agent"
    s.sync.background = False  # never let a test thread reach the real DataRobot
    assert s.path == tmp_path / "rt" / "forecast_store.sqlite"


def test_runtime_param_deployment_ids(monkeypatch):
    monkeypatch.setenv(
        "MLOPS_RUNTIME_PARAM_DEPLOYMENT_ID_MINING",
        json.dumps({"type": "string", "payload": "rt-mining"}),
    )
    assert data.load_deployments()["mining"]["deployment_id"] == "rt-mining"
