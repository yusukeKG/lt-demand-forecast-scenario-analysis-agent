"""Static demo data: file locations, loaders, and domain constants.

All CSVs live in ``agent/demo_assets/data`` so they ship with the agent bundle.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

ASSETS_DIR = Path(__file__).resolve().parents[2] / "demo_assets"
DATA_DIR = ASSETS_DIR / "data"

BASE_YEAR = 2025
FORECAST_YEARS = list(range(BASE_YEAR + 1, 2051))
HISTORY_START_YEAR = 1995

# slug -> Japanese category name used in the demand CSVs
CATEGORIES: dict[str, str] = {
    "general": "一般建機",
    "mini": "ミニショベル",
    "mining": "鉱山機械",
}
CATEGORY_BY_JA = {v: k for k, v in CATEGORIES.items()}

REGIONS = [
    "日本",
    "北米",
    "中南米",
    "欧州",
    "CIS",
    "中国",
    "アジア",
    "オセアニア",
    "中近東",
    "アフリカ",
]

SCENARIO_IDS = ["S1_BASE", "S2_NETZERO", "S3_FRAGMENT", "S4_FOSSIL"]

# Driver columns needed by features.build_features()
BASE_COLS = [
    "iso3",
    "year",
    "population",
    "urban_pct",
    "gdp_pc_ppp_const2021",
    "gdp_growth_pct",
    "gfcf_pct_gdp",
    "coal_prod_twh",
    "copper_usd_t_real2010",
    "ironore_usd_dmtu_real2010",
    "coal_aus_usd_t_real2010",
    "gold_usd_oz_real2010",
]

SOURCE_NOTE_JA = (
    "需要はデモ用の架空データ。ドライバーは公開データ（世界銀行、Our World in Data）、"
    "将来前提は公開シナリオを参考にした設定値"
)


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, encoding="utf-8-sig")


@lru_cache(maxsize=None)
def country_master() -> pd.DataFrame:
    return _read("01_country_master.csv")


@lru_cache(maxsize=None)
def drivers_history() -> pd.DataFrame:
    return _read("02_drivers_country_year.csv")


@lru_cache(maxsize=None)
def commodity_prices_history() -> pd.DataFrame:
    return _read("03_commodity_prices_real.csv")


@lru_cache(maxsize=None)
def demand_country_year() -> pd.DataFrame:
    return _read("04_demand_dummy_country_year.csv")


@lru_cache(maxsize=None)
def demand_region_year() -> pd.DataFrame:
    return _read("05_demand_dummy_region_year.csv")


@lru_cache(maxsize=None)
def scenario_definitions() -> pd.DataFrame:
    return _read("06_scenario_definition.csv")


@lru_cache(maxsize=None)
def scenario_levers() -> pd.DataFrame:
    return _read("07_scenario_levers.csv")


@lru_cache(maxsize=None)
def future_drivers() -> pd.DataFrame:
    return _read("08_future_drivers_country_year_scenario.csv")


@lru_cache(maxsize=None)
def external_forecast() -> pd.DataFrame:
    return _read("10_external_forecast_dummy.csv")


@lru_cache(maxsize=None)
def train_data(slug: str) -> pd.DataFrame:
    return _read(f"train_{slug}.csv")


@lru_cache(maxsize=None)
def precomputed_score(slug: str) -> pd.DataFrame:
    return _read(f"score_{slug}_2026_2050_all_scenarios.csv")


def backtest_predictions(slug: str) -> pd.DataFrame | None:
    """Output of run_backtest.py; None until the user has run it."""
    path = DATA_DIR / f"backtest_predictions_{slug}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, encoding="utf-8-sig")


def jumpoff_units(slug: str) -> pd.Series:
    """2025 actual units per country, used for the jump-off correction."""
    t = train_data(slug)
    return t[t.year == BASE_YEAR].set_index("iso3").units


def category_countries(slug: str) -> list[str]:
    """Countries modelled for a category (mining covers only 26 countries)."""
    return sorted(train_data(slug).iso3.unique())


def lever_defaults(scenario_id: str) -> dict[str, Any]:
    """Lever values L1-L4 for a scenario, typed (float / int / str)."""
    lev = scenario_levers().set_index("lever_id")[scenario_id]
    return {
        "L1_automation": float(lev["L1_automation"]),
        "L2_china_peak": float(lev["L2_china_peak"]),
        "L3_emerging_timing": int(float(lev["L3_emerging_timing"])),
        "L4_idn_coal": str(lev["L4_idn_coal"]),
    }


def runtime_param(name: str) -> str | None:
    """Env var or DataRobot runtime parameter (``MLOPS_RUNTIME_PARAM_<name>``)."""
    from datarobot.core.config import getenv

    value = getenv(name)
    return None if value is None else str(value)


def load_deployments() -> dict[str, dict[str, Any]]:
    """Deployment info per category.

    ``DEPLOYMENT_ID_{GENERAL,MINI,MINING}`` (runtime parameters) take precedence
    over ``deployments.json``. Categories without an ID are left out so the UI
    can show them as 「準備中」.
    """
    path = ASSETS_DIR / "deployments.json"
    raw: dict[str, dict[str, Any]] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for slug in CATEGORIES:
        info = dict(raw.get(slug, {}))
        env_id = (runtime_param(f"DEPLOYMENT_ID_{slug.upper()}") or "").strip()
        if env_id and env_id != "SET_VIA_PULUMI_OR_MANUALLY":
            info["deployment_id"] = env_id
        dep_id = str(info.get("deployment_id", ""))
        if not dep_id or dep_id.startswith("<"):
            continue
        out[slug] = info
    return out
