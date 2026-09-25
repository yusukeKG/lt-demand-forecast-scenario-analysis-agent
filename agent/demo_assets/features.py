"""学習用・予測用で共通の特徴量作成ロジック (エージェントアプリの What-if でも同じ関数を使う)"""
import numpy as np
import pandas as pd

PRICE_COLS = {"copper_usd_t_real2010": "copper", "ironore_usd_dmtu_real2010": "ironore",
              "coal_aus_usd_t_real2010": "coal", "gold_usd_oz_real2010": "gold"}
# 価格の基準値 = 2005-2015年の実質価格平均 (比率に変換して学習範囲外の値の影響を抑える)
PRICE_BASE = {"copper": 6599.2, "ironore": 108.9, "coal": 79.4, "gold": 1050.9}

FEATURES = ["region", "gdp_pc_ppp", "gdp_pc_growth_5y_pct", "gdp_growth_pct", "gdp_growth_3y_avg_pct",
            "urban_pct", "urban_pct_change_5y", "gfcf_pct_gdp", "gfcf_pct_gdp_change_3y",
            "coal_prod_kwh_per_capita", "res_copper", "res_ironore", "res_gold",
            "copper_ratio_lag1", "ironore_ratio_lag1", "coal_ratio_lag1", "gold_ratio_lag1",
            "copper_ratio_change_3y"]

def build_features(df, master, group_cols=("iso3",)):
    """df: iso3, year, population, urban_pct, gdp_pc_ppp_const2021, gdp_growth_pct, gfcf_pct_gdp,
    coal_prod_twh, 4つの価格列。ラグ計算のため、予測対象年の5年前からの行を含めて渡すこと。"""
    g = list(group_cols)
    d = df.sort_values(g + ["year"]).copy()
    d = d.merge(master[["iso3", "region", "res_copper", "res_ironore", "res_gold"]], on="iso3", how="left")
    grp = d.groupby(g)
    d["gdp_pc_ppp"] = d.gdp_pc_ppp_const2021
    d["gdp_pc_growth_5y_pct"] = ((d.gdp_pc_ppp / grp.gdp_pc_ppp_const2021.shift(5)) ** 0.2 - 1) * 100
    d["gdp_growth_3y_avg_pct"] = grp.gdp_growth_pct.transform(lambda s: s.rolling(3, min_periods=1).mean())
    d["urban_pct_change_5y"] = d.urban_pct - grp.urban_pct.shift(5)
    d["gfcf_pct_gdp_change_3y"] = d.gfcf_pct_gdp - grp.gfcf_pct_gdp.shift(3)
    d["coal_prod_kwh_per_capita"] = d.coal_prod_twh * 1e9 / d.population
    for col, k in PRICE_COLS.items():
        d[f"{k}_ratio"] = d[col] / PRICE_BASE[k]
        d[f"{k}_ratio_lag1"] = d.groupby(g)[f"{k}_ratio"].shift(1)
    d["copper_ratio_change_3y"] = d.copper_ratio_lag1 - d.groupby(g).copper_ratio_lag1.shift(3)
    return d
