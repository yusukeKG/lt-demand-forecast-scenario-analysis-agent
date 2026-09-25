"""2026-2050年 将来シナリオ前提データの生成
4シナリオ (SSP×IEAシナリオの考え方を参考にした設定値) × 38か国
"""
import numpy as np
import pandas as pd

import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
drv = pd.read_csv(f"{out}/02_drivers_country_year.csv")
master = pd.read_csv(f"{out}/01_country_master.csv")
prices = pd.read_csv(f"{out}/03_commodity_prices_real.csv")
FY = list(range(2026, 2051))
T = np.arange(1, len(FY) + 1)  # 2026=1 ... 2050=25

# ---------------------------------------------------------------- シナリオ定義
SCN = pd.DataFrame([
    ("S1_BASE", "ベース", "SSP2（中庸）", "IEA 現行政策シナリオ（STEPS）",
     "現在の延長線。新興国は緩やかに先進国へ収れん。石炭は2030年代から緩やかに減少、銅は電化で底堅い"),
    ("S2_NETZERO", "脱炭素加速", "SSP1（持続可能）", "IEA ネットゼロシナリオ（NZE）",
     "国際協調で成長と脱炭素を両立。銅需要が大きく伸び価格上昇、石炭は急減"),
    ("S3_FRAGMENT", "分断世界", "SSP3（地域対立）", "IEA 現行政策シナリオ（STEPS）",
     "ブロック化で新興国の収れんが停滞。資源は供給不安で価格が不安定、金は安全資産として上昇"),
    ("S4_FOSSIL", "高成長・化石依存", "SSP5（化石燃料依存の高成長）", "IEA 現行政策シナリオ（STEPS）以上の化石燃料需要",
     "技術進歩と化石燃料で高成長。石炭も長く残り、資源全般が底堅い"),
], columns=["scenario_id", "scenario_ja", "ssp_reference", "energy_reference", "narrative"])

# ---------------------------------------------------------------- 1) 人口
# 2050年人口: 国連人口推計(WPP 2024)中位推計の水準を参考にした近似値(百万人, 丸め)
POP2050 = {"JPN": 105, "USA": 380, "CAN": 45, "BRA": 217, "MEX": 143, "CHL": 20.5, "PER": 39,
           "COL": 55, "ARG": 49, "DEU": 80, "FRA": 66, "GBR": 73, "ITA": 52, "ESP": 46, "POL": 34,
           "SWE": 11.3, "RUS": 136, "KAZ": 25, "UZB": 48, "CHN": 1260, "IDN": 317, "IND": 1680,
           "THA": 67, "VNM": 107, "PHL": 140, "MYS": 41, "AUS": 33, "NZL": 6, "SAU": 45, "ARE": 13,
           "TUR": 92, "ZAF": 72, "NGA": 375, "EGY": 160, "KEN": 85, "GHA": 52, "COD": 215, "ZMB": 36}
# シナリオ別の2050年補正 (SSPの人口パターンを参考: SSP1/5 は途上国で低出生, SSP3 は途上国で高出生)
def pop_adj(scn, gdp_pc):
    dev = gdp_pc < 20000
    return {"S1_BASE": 1.0, "S2_NETZERO": 0.96 if dev else 1.00,
            "S3_FRAGMENT": 1.06 if dev else 0.97, "S4_FOSSIL": 0.95 if dev else 1.03}[scn]

# ---------------------------------------------------------------- 2) 1人当たりGDP (収れんモデル)
# 成長率 = フロンティア成長率 + 収れん係数 × ln(米国水準×0.8 / 自国水準) (差がない国はフロンティア成長率)
# 2026-2035 は各国の直近5年平均成長率から徐々に移行 (足元の勢いを反映)
GDP_PAR = {"S1_BASE": (0.012, 0.020), "S2_NETZERO": (0.014, 0.025),
           "S3_FRAGMENT": (0.008, 0.008), "S4_FOSSIL": (0.018, 0.028)}
SS_RATIO = 0.8  # 条件付き収れん: 米国水準の8割を各国の到達目安とする

# ---------------------------------------------------------------- 3) 石炭生産 (年率変化)
COAL = {  # (2026-2035, 2036-2050)
    "S1_BASE": (-0.005, -0.020), "S2_NETZERO": (-0.060, -0.090),
    "S3_FRAGMENT": (0.000, -0.012), "S4_FOSSIL": (0.010, 0.000)}
COAL_OVR = {("IND", "S1_BASE"): (0.030, -0.005), ("IND", "S3_FRAGMENT"): (0.035, 0.005),
            ("IND", "S4_FOSSIL"): (0.040, 0.010), ("IDN", "S1_BASE"): (-0.015, -0.025)}

# ---------------------------------------------------------------- 4) 資源価格 (実質, 年率変化)
PX = {  # 銅, 鉄鉱石, 豪州炭, 金
    "S1_BASE":     {"copper": 0.010, "ironore": -0.005, "coal": -0.015, "gold": 0.000},
    "S2_NETZERO":  {"copper": 0.025, "ironore": -0.003, "coal": -0.050, "gold": 0.000},
    "S3_FRAGMENT": {"copper": 0.005, "ironore": -0.010, "coal": -0.010, "gold": 0.015},
    "S4_FOSSIL":   {"copper": 0.012, "ironore": 0.000, "coal": 0.005, "gold": 0.000},
}
PCOL = {"copper": "copper_usd_t_real2010", "ironore": "ironore_usd_dmtu_real2010",
        "coal": "coal_aus_usd_t_real2010", "gold": "gold_usd_oz_real2010"}

# ---------------------------------------------------------------- 5) 自社固有の論点 (レバー)
LEVERS = pd.DataFrame([
    ("L1_automation", "自動化による必要台数の減少率", "年率",
     "自動化・遠隔化で1台あたりの生産性が上がり、同じ工事量に必要な台数が減る効果", 0.003, 0.006, 0.001, 0.004, "予測段階で需要に適用"),
    ("L2_china_peak", "中国の固定資本形成比の2050年水準", "%",
     "中国の投資主導経済からの転換の深さ。低いほど建設需要のピークアウトが深い", 30, 28, 32, 31, "本データの gfcf_pct_gdp に反映済み"),
    ("L3_emerging_timing", "インド・アフリカ立ち上がりの前倒し年数", "年",
     "正の値は成長の前倒し、負の値は後ずれ", 0, 2, -3, 1, "本データの gdp_pc_ppp に反映済み"),
    ("L4_idn_coal", "インドネシア石炭需要の回復", "区分",
     "回復あり/回復なし。石炭生産量の経路に反映", "回復なし", "回復なし", "回復なし", "回復あり", "本データの coal_prod_twh に反映済み"),
], columns=["lever_id", "lever_ja", "unit", "description", "S1_BASE", "S2_NETZERO", "S3_FRAGMENT",
            "S4_FOSSIL", "how_applied"])
lev = LEVERS.set_index("lever_id")

base = drv[drv.year == 2025].set_index("iso3")
hist = drv.set_index(["iso3", "year"])
us_gpc0 = base.loc["USA", "gdp_pc_ppp_const2021"]

rows = []
for scn in SCN.scenario_id:
    g_front, beta = GDP_PAR[scn]
    china_gfcf = float(lev.loc["L2_china_peak", scn])
    shift = int(lev.loc["L3_emerging_timing", scn])
    for iso in master.iso3:
        b = base.loc[iso]
        region = master.set_index("iso3").loc[iso, "region"]
        # --- 人口: 2025 → 2050目標へ幾何補間
        p0 = b.population
        p50 = POP2050[iso] * 1e6 * pop_adj(scn, b.gdp_pc_ppp_const2021)
        pop = p0 * (p50 / p0) ** (T / 25)
        # --- 都市化率: 上限へのロジスティック的な接近 (直近10年の伸びを初速に)
        u0 = b.urban_pct
        u10 = hist.loc[(iso, 2015), "urban_pct"]
        cap = 92 if u0 > 70 else 85
        speed = {"S1_BASE": 1.0, "S2_NETZERO": 1.15, "S3_FRAGMENT": 0.7, "S4_FOSSIL": 1.2}[scn]
        r = max((u0 - u10) / 10, 0.02) * 1.4 / max(cap - u0, 1) * speed
        urb = cap - (cap - u0) * np.exp(-r * T)
        # --- 1人当たりGDP
        g_hist = (hist.loc[(iso, 2025), "gdp_pc_ppp_const2021"] /
                  hist.loc[(iso, 2022), "gdp_pc_ppp_const2021"]) ** (1 / 3) - 1  # コロナ後3年平均
        g_hist = float(np.clip(g_hist, -0.01, 0.065))
        gpc = np.zeros(len(FY)); us = np.zeros(len(FY))
        g_prev, u_prev = b.gdp_pc_ppp_const2021, us_gpc0
        for i, y in enumerate(FY):
            u_prev *= 1 + g_front
            conv = g_front + beta * max(np.log(SS_RATIO * u_prev / g_prev), 0.0)
            conv = min(conv, g_front + 0.035)  # 低所得国の過大な収れんを抑制
            if region == "中国":           # 高齢化・投資転換で収れんを割り引く
                conv -= 0.004
            if region == "アフリカ":         # 制度・インフラ制約による収れんの割引
                conv -= 0.006 if scn == "S2_NETZERO" else 0.012
            if region == "CIS" and scn == "S3_FRAGMENT":
                conv -= 0.005
            w = max(0.0, 1 - (y - 2025) / 10)        # 足元の成長率の影響は10年で消える
            yy = y + (shift if iso in ("IND", "NGA", "KEN", "GHA", "COD", "ZMB", "EGY") else 0)
            w_em = max(0.0, 1 - (yy - 2025) / 10) if shift else w
            g = w_em * g_hist + (1 - w_em) * conv if iso in ("IND", "NGA", "KEN", "GHA", "COD", "ZMB", "EGY") else w * g_hist + (1 - w) * conv
            g_prev *= 1 + g
            gpc[i] = g_prev
        # --- 固定資本形成比: 23%へ半減期15年で収れん (中国はレバーL2の水準へ)
        k0 = b.gfcf_pct_gdp
        tgt = china_gfcf if iso == "CHN" else 23.0
        hl = 12 if iso == "CHN" else 15
        gfcf = tgt + (k0 - tgt) * 0.5 ** (T / hl)
        # --- 石炭生産
        c1, c2 = COAL_OVR.get((iso, scn), COAL[scn])
        if iso == "IDN" and lev.loc["L4_idn_coal", scn] == "回復あり":
            c1, c2 = 0.015, -0.005
        rate = np.where(np.array(FY) <= 2035, c1, c2)
        coal = b.coal_prod_twh * np.cumprod(1 + rate)
        for i, y in enumerate(FY):
            rows.append((scn, iso, region, y, pop[i], urb[i], gpc[i], gfcf[i], coal[i]))

fut = pd.DataFrame(rows, columns=["scenario_id", "iso3", "region", "year", "population", "urban_pct",
                                  "gdp_pc_ppp_const2021", "gfcf_pct_gdp", "coal_prod_twh"])
fut["urban_pop_mn"] = fut.urban_pct / 100 * fut.population / 1e6
fut["gdp_ppp_bn"] = fut.gdp_pc_ppp_const2021 * fut.population / 1e9
fut = fut.sort_values(["scenario_id", "iso3", "year"])
prev = fut.groupby(["scenario_id", "iso3"]).gdp_ppp_bn.shift(1)
b25 = fut.iso3.map(base.gdp_ppp_bn)
fut["gdp_growth_pct"] = ((fut.gdp_ppp_bn / prev.fillna(b25)) - 1) * 100
fut = fut.merge(master[["iso3", "sub_region"]], on="iso3")

# 資源価格
p25 = prices.set_index("year").loc[2025]
prow = []
for scn, rr in PX.items():
    for i, y in enumerate(FY):
        prow.append([scn, y] + [p25[PCOL[k]] * (1 + rr[k]) ** (i + 1) for k in PCOL])
pxf = pd.DataFrame(prow, columns=["scenario_id", "year"] + list(PCOL.values()))
fut = fut.merge(pxf, on=["scenario_id", "year"])

cols = ["scenario_id", "iso3", "region", "sub_region", "year", "population", "urban_pct", "urban_pop_mn",
        "gdp_pc_ppp_const2021", "gdp_ppp_bn", "gdp_growth_pct", "gfcf_pct_gdp", "coal_prod_twh"] + list(PCOL.values())
fut = fut[cols].round(4)

# ---------------------------------------------------------------- 外部予測 (比較用ダミー)
ext = pd.DataFrame([
    ("日本", -5, -10, -15), ("北米", 5, 10, 15), ("中南米", 10, 20, 30), ("欧州", 2, 4, 5),
    ("CIS", 3, 6, 10), ("中国", -10, -18, -25), ("アジア", 20, 45, 70), ("オセアニア", 4, 8, 10),
    ("中近東", 12, 25, 40), ("アフリカ", 25, 65, 120),
], columns=["region", "growth_2030_vs_2025_pct", "growth_2040_vs_2025_pct", "growth_2050_vs_2025_pct"])
ext["note"] = "外部長期予測の形式を模した架空の値。本番では自社保有の外部資料の値に置き換える想定"

SCN.to_csv(f"{out}/06_scenario_definition.csv", index=False, encoding="utf-8-sig")
LEVERS.to_csv(f"{out}/07_scenario_levers.csv", index=False, encoding="utf-8-sig")
fut.to_csv(f"{out}/08_future_drivers_country_year_scenario.csv", index=False, encoding="utf-8-sig")
pxf.round(2).to_csv(f"{out}/09_future_commodity_prices_real.csv", index=False, encoding="utf-8-sig")
ext.to_csv(f"{out}/10_external_forecast_dummy.csv", index=False, encoding="utf-8-sig")
print(fut.shape)
