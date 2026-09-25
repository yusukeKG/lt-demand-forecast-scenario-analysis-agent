"""Future driver generation, refactored from demo_assets/generate_future_scenarios.py.

The original script builds all four scenarios top to bottom with levers L2-L4 read
from a fixed table. Here the same logic is a function of (scenario_id, levers) so a
what-if run can rebuild one scenario with different lever values. With the default
levers the output matches 08_future_drivers_country_year_scenario.csv.
"""

from typing import Any

import numpy as np
import pandas as pd

from agent.forecast import data

FY = data.FORECAST_YEARS
T = np.arange(1, len(FY) + 1)  # 2026=1 ... 2050=25

# ---------------------------------------------------------------- 1) 人口
# 2050年人口: 国連人口推計(WPP 2024)中位推計の水準を参考にした近似値(百万人, 丸め)
POP2050 = {
    "JPN": 105, "USA": 380, "CAN": 45, "BRA": 217, "MEX": 143, "CHL": 20.5, "PER": 39,
    "COL": 55, "ARG": 49, "DEU": 80, "FRA": 66, "GBR": 73, "ITA": 52, "ESP": 46, "POL": 34,
    "SWE": 11.3, "RUS": 136, "KAZ": 25, "UZB": 48, "CHN": 1260, "IDN": 317, "IND": 1680,
    "THA": 67, "VNM": 107, "PHL": 140, "MYS": 41, "AUS": 33, "NZL": 6, "SAU": 45, "ARE": 13,
    "TUR": 92, "ZAF": 72, "NGA": 375, "EGY": 160, "KEN": 85, "GHA": 52, "COD": 215, "ZMB": 36,
}  # fmt: skip


def pop_adj(scn: str, gdp_pc: float) -> float:
    """シナリオ別の2050年補正 (SSP1/5 は途上国で低出生, SSP3 は途上国で高出生)"""
    dev = gdp_pc < 20000
    return {
        "S1_BASE": 1.0,
        "S2_NETZERO": 0.96 if dev else 1.00,
        "S3_FRAGMENT": 1.06 if dev else 0.97,
        "S4_FOSSIL": 0.95 if dev else 1.03,
    }[scn]


# ---------------------------------------------------------------- 2) 1人当たりGDP (収れんモデル)
GDP_PAR = {
    "S1_BASE": (0.012, 0.020),
    "S2_NETZERO": (0.014, 0.025),
    "S3_FRAGMENT": (0.008, 0.008),
    "S4_FOSSIL": (0.018, 0.028),
}
SS_RATIO = 0.8  # 条件付き収れん: 米国水準の8割を各国の到達目安とする
URBAN_SPEED = {"S1_BASE": 1.0, "S2_NETZERO": 1.15, "S3_FRAGMENT": 0.7, "S4_FOSSIL": 1.2}
# レバーL3 (立ち上がりの前倒し) の対象国
EMERGING = ("IND", "NGA", "KEN", "GHA", "COD", "ZMB", "EGY")

# ---------------------------------------------------------------- 3) 石炭生産 (年率変化)
COAL = {  # (2026-2035, 2036-2050)
    "S1_BASE": (-0.005, -0.020),
    "S2_NETZERO": (-0.060, -0.090),
    "S3_FRAGMENT": (0.000, -0.012),
    "S4_FOSSIL": (0.010, 0.000),
}
COAL_OVR = {
    ("IND", "S1_BASE"): (0.030, -0.005),
    ("IND", "S3_FRAGMENT"): (0.035, 0.005),
    ("IND", "S4_FOSSIL"): (0.040, 0.010),
    ("IDN", "S1_BASE"): (-0.015, -0.025),
}
IDN_COAL_RECOVERY = (0.015, -0.005)  # レバーL4 = 回復あり

# ---------------------------------------------------------------- 4) 資源価格 (実質, 年率変化)
PX = {  # 銅, 鉄鉱石, 豪州炭, 金
    "S1_BASE": {"copper": 0.010, "ironore": -0.005, "coal": -0.015, "gold": 0.000},
    "S2_NETZERO": {"copper": 0.025, "ironore": -0.003, "coal": -0.050, "gold": 0.000},
    "S3_FRAGMENT": {"copper": 0.005, "ironore": -0.010, "coal": -0.010, "gold": 0.015},
    "S4_FOSSIL": {"copper": 0.012, "ironore": 0.000, "coal": 0.005, "gold": 0.000},
}
PCOL = {
    "copper": "copper_usd_t_real2010",
    "ironore": "ironore_usd_dmtu_real2010",
    "coal": "coal_aus_usd_t_real2010",
    "gold": "gold_usd_oz_real2010",
}

OUTPUT_COLS = [
    "scenario_id", "iso3", "region", "sub_region", "year", "population", "urban_pct",
    "urban_pop_mn", "gdp_pc_ppp_const2021", "gdp_ppp_bn", "gdp_growth_pct", "gfcf_pct_gdp",
    "coal_prod_twh", *PCOL.values(),
]  # fmt: skip


def resolve_levers(
    scenario_id: str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Scenario default levers with user overrides applied (unknown keys rejected)."""
    levers = data.lever_defaults(scenario_id)
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key not in levers:
            raise ValueError(
                f"未知のレバーです: {key}（L1_automation / L2_china_peak / L3_emerging_timing / L4_idn_coal）"
            )
        if key == "L4_idn_coal":
            if value not in ("回復あり", "回復なし"):
                raise ValueError(
                    "L4_idn_coal は「回復あり」か「回復なし」を指定してください"
                )
            levers[key] = value
        elif key == "L3_emerging_timing":
            levers[key] = int(value)
        else:
            levers[key] = float(value)
    return levers


def generate_country_drivers(
    scenario_id: str, levers: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Country x year drivers (2026-2050) for one scenario, before prices are merged."""
    lev = levers or data.lever_defaults(scenario_id)
    drv = data.drivers_history()
    master = data.country_master()
    region_of = master.set_index("iso3").region
    base = drv[drv.year == data.BASE_YEAR].set_index("iso3")
    hist = drv.set_index(["iso3", "year"])
    us_gpc0 = base.loc["USA", "gdp_pc_ppp_const2021"]

    scn = scenario_id
    g_front, beta = GDP_PAR[scn]
    china_gfcf = float(lev["L2_china_peak"])
    shift = int(lev["L3_emerging_timing"])
    rows = []
    for iso in master.iso3:
        b = base.loc[iso]
        region = region_of[iso]
        # --- 人口: 2025 → 2050目標へ幾何補間
        p0 = b.population
        p50 = POP2050[iso] * 1e6 * pop_adj(scn, b.gdp_pc_ppp_const2021)
        pop = p0 * (p50 / p0) ** (T / 25)
        # --- 都市化率: 上限へのロジスティック的な接近 (直近10年の伸びを初速に)
        u0 = b.urban_pct
        u10 = hist.loc[(iso, 2015), "urban_pct"]
        cap = 92 if u0 > 70 else 85
        r = max((u0 - u10) / 10, 0.02) * 1.4 / max(cap - u0, 1) * URBAN_SPEED[scn]
        urb = cap - (cap - u0) * np.exp(-r * T)
        # --- 1人当たりGDP
        g_hist = (
            hist.loc[(iso, 2025), "gdp_pc_ppp_const2021"]
            / hist.loc[(iso, 2022), "gdp_pc_ppp_const2021"]
        ) ** (1 / 3) - 1  # コロナ後3年平均
        g_hist = float(np.clip(g_hist, -0.01, 0.065))
        gpc = np.zeros(len(FY))
        g_prev, u_prev = b.gdp_pc_ppp_const2021, us_gpc0
        for i, y in enumerate(FY):
            u_prev *= 1 + g_front
            conv = g_front + beta * max(np.log(SS_RATIO * u_prev / g_prev), 0.0)
            conv = min(conv, g_front + 0.035)  # 低所得国の過大な収れんを抑制
            if region == "中国":  # 高齢化・投資転換で収れんを割り引く
                conv -= 0.004
            if region == "アフリカ":  # 制度・インフラ制約による収れんの割引
                conv -= 0.006 if scn == "S2_NETZERO" else 0.012
            if region == "CIS" and scn == "S3_FRAGMENT":
                conv -= 0.005
            w = max(0.0, 1 - (y - 2025) / 10)  # 足元の成長率の影響は10年で消える
            if iso in EMERGING:
                yy = y + shift
                w_em = max(0.0, 1 - (yy - 2025) / 10) if shift else w
                g = w_em * g_hist + (1 - w_em) * conv
            else:
                g = w * g_hist + (1 - w) * conv
            g_prev *= 1 + g
            gpc[i] = g_prev
        # --- 固定資本形成比: 23%へ半減期15年で収れん (中国はレバーL2の水準へ)
        k0 = b.gfcf_pct_gdp
        tgt = china_gfcf if iso == "CHN" else 23.0
        hl = 12 if iso == "CHN" else 15
        gfcf = tgt + (k0 - tgt) * 0.5 ** (T / hl)
        # --- 石炭生産
        c1, c2 = COAL_OVR.get((iso, scn), COAL[scn])
        if iso == "IDN" and lev["L4_idn_coal"] == "回復あり":
            c1, c2 = IDN_COAL_RECOVERY
        rate = np.where(np.array(FY) <= 2035, c1, c2)
        coal = b.coal_prod_twh * np.cumprod(1 + rate)
        for i, y in enumerate(FY):
            rows.append((scn, iso, region, y, pop[i], urb[i], gpc[i], gfcf[i], coal[i]))

    fut = pd.DataFrame(
        rows,
        columns=["scenario_id", "iso3", "region", "year", "population", "urban_pct",
                 "gdp_pc_ppp_const2021", "gfcf_pct_gdp", "coal_prod_twh"],
    )  # fmt: skip
    fut = recompute_derived(fut)
    return fut.merge(master[["iso3", "sub_region"]], on="iso3")


def recompute_derived(fut: pd.DataFrame) -> pd.DataFrame:
    """Recompute urban_pop_mn / gdp_ppp_bn / gdp_growth_pct from the base drivers."""
    base = data.drivers_history()
    b25 = base[base.year == data.BASE_YEAR].set_index("iso3").gdp_ppp_bn
    fut = fut.sort_values(["scenario_id", "iso3", "year"]).copy()
    fut["urban_pop_mn"] = fut.urban_pct / 100 * fut.population / 1e6
    fut["gdp_ppp_bn"] = fut.gdp_pc_ppp_const2021 * fut.population / 1e9
    prev = fut.groupby(["scenario_id", "iso3"]).gdp_ppp_bn.shift(1)
    fut["gdp_growth_pct"] = (
        (fut.gdp_ppp_bn / prev.fillna(fut.iso3.map(b25))) - 1
    ) * 100
    return fut


def generate_prices(scenario_id: str) -> pd.DataFrame:
    """World commodity prices (real) for 2026-2050."""
    p25 = data.commodity_prices_history().set_index("year").loc[data.BASE_YEAR]
    rr = PX[scenario_id]
    rows = [
        [scenario_id, y] + [p25[PCOL[k]] * (1 + rr[k]) ** (i + 1) for k in PCOL]
        for i, y in enumerate(FY)
    ]
    return pd.DataFrame(rows, columns=["scenario_id", "year", *PCOL.values()])


def generate_future_drivers(
    scenario_id: str, levers: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Full future driver table for one scenario (same layout as file 08)."""
    if scenario_id not in PX:
        raise ValueError(f"未知のシナリオです: {scenario_id}")
    fut = generate_country_drivers(scenario_id, levers)
    fut = fut.merge(generate_prices(scenario_id), on=["scenario_id", "year"])
    return fut[OUTPUT_COLS].reset_index(drop=True)


def uses_default_structural_levers(scenario_id: str, levers: dict[str, Any]) -> bool:
    """True when L2-L4 equal the scenario defaults (the precomputed file 08 applies)."""
    d = data.lever_defaults(scenario_id)
    return all(
        levers[k] == d[k]
        for k in ("L2_china_peak", "L3_emerging_timing", "L4_idn_coal")
    )
