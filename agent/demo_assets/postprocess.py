"""DataRobotの予測値(人口100万人あたり台数)を台数に戻し、長期予測向けの補正をかける後処理。
エージェントアプリ側で、予測リクエストの結果に対して適用する。
 1) 台数への換算         : 予測値 × 人口 / 100万
 2) 起点補正(jump-off)   : 2025年実績 / 2026年のモデル予測 の比を掛け、半減期10年で1に戻す
                            (足元の水準から滑らかにつなぎ、長期では構造要因に委ねる)
 3) 資源価格の範囲外補正 : 学習範囲を超える価格の効果を弾性値で上乗せ (鉱山機械のみ)
 4) 自動化レバー         : 必要台数を年率 L1 だけ減少
 5) 人による補正(HILP)   : 地域×機種ごとの補正係数。start_year から ramp_years かけて係数まで移行
"""
import numpy as np, pandas as pd

HIST_MAX_RATIO = {"copper": 1.30, "ironore": 1.45, "gold": 2.82}   # 1995-2025年の最大値(基準比)
ELASTICITY = {"copper": 0.9, "ironore": 0.8, "gold": 0.6}          # 需要の価格弾性値(デモ用の設定値)
RES_COL = {"copper": "res_copper", "ironore": "res_ironore", "gold": "res_gold"}

def postprocess(pred_df, prediction_col, category, jumpoff=None, automation_rate=0.0,
                half_life=10, base_year=2025, adjustments=None):
    """adjustments: [{"region": "アフリカ", "category": "general", "factor": 0.7,
                      "start_year": 2026, "ramp_years": 5}, ...]  category は general/mini/mining"""
    d = pred_df.copy()
    d["units_pred"] = d[prediction_col] * d.population / 1e6
    if jumpoff is not None:   # jumpoff: iso3 -> 2025年の販売台数実績
        first = d[d.year == base_year + 1].set_index("iso3").units_pred
        f = d.iso3.map(pd.Series(jumpoff) / first).fillna(1.0).clip(0.3, 3.0)
        decay = 0.5 ** ((d.year - base_year - 1) / half_life)
        d["units_pred"] *= f ** decay
    if category == "mining":
        w_total = sum(d[c] for c in RES_COL.values()).replace(0, np.nan)
        adj = 1.0
        for k, c in RES_COL.items():
            r = d[f"{k}_ratio_lag1"]
            over = np.maximum(r / HIST_MAX_RATIO[k], 1.0) ** ELASTICITY[k]
            adj = adj * over ** (d[c] / w_total).fillna(0)
        d["units_pred"] *= adj
    d["units_pred"] *= (1 - automation_rate) ** (d.year - base_year)
    for a in adjustments or []:
        if a.get("category", category) != category:
            continue
        m = d.region == a["region"]
        start, ramp = a.get("start_year", base_year + 1), max(a.get("ramp_years", 1), 1)
        w = ((d.year - start + 1) / ramp).clip(0, 1)
        d.loc[m, "units_pred"] *= (1 + (a["factor"] - 1) * w[m])
    return d
