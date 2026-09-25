"""デプロイ済みモデルに将来シナリオを送り、2050年までの需要予測(台数)を作るスクリプト
エージェントアプリの予測処理の見本。 deployments.json と data/ を使う。
  python predict_scenarios.py   → forecast_2026_2050.csv を出力
"""
import json
import os
import datarobot as dr

try:  # .env ファイルがあれば読み込む (APIトークンをコードやチャットに書かないため)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass
import pandas as pd
from postprocess import postprocess

DIR = os.path.dirname(__file__)
dr.Client(token=os.environ["DATAROBOT_API_TOKEN"],
          endpoint=os.environ.get("DATAROBOT_ENDPOINT", "https://app.datarobot.com/api/v2"))
deps = json.load(open(os.path.join(DIR, "deployments.json"), encoding="utf-8"))
levers = pd.read_csv(os.path.join(DIR, "data", "07_scenario_levers.csv")).set_index("lever_id")

outs = []
CATS = {"general": "一般建機", "mini": "ミニショベル", "mining": "鉱山機械"}
for slug, info in deps.items():
    if slug.startswith("_"):  # "_comment" などの説明用キー
        continue
    score = pd.read_csv(os.path.join(DIR, "data", f"score_{slug}_2026_2050_all_scenarios.csv"))
    _, pred = dr.BatchPredictionJob.score_pandas(info["deployment_id"], score)
    pcol = [c for c in pred.columns if c.endswith("_PREDICTION")][0]
    train = pd.read_csv(os.path.join(DIR, "data", f"train_{slug}.csv"))
    actual_2025 = train[train.year == 2025].set_index("iso3").units
    for scn, g in pred.groupby("scenario_id"):
        auto = float(levers.loc["L1_automation", scn])
        o = postprocess(g, pcol, slug, jumpoff=actual_2025, automation_rate=auto)
        o["category"] = CATS[slug]
        outs.append(o[["scenario_id", "category", "iso3", "region", "year", "units_pred"]])
res = pd.concat(outs)
res.to_csv(os.path.join(DIR, "forecast_2026_2050.csv"), index=False, encoding="utf-8-sig")
print(res.groupby(["scenario_id", "year"]).units_pred.sum().unstack(0).loc[[2030, 2040, 2050]].round(0))
