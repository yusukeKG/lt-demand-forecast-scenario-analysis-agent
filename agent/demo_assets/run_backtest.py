"""過去検証: 1995-2005年だけで学習したモデルで 2006-2025年を予測し、実績と比較できる形で保存する
(デプロイは不要。リーダーボード上の推奨モデルで予測する)
  python run_backtest.py general   → data/backtest_predictions_general.csv
出力列: iso3, region, year, units_actual, units_pred
"""
import os
import sys

import datarobot as dr
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from features import FEATURES

DIR = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(DIR, "data")
dr.Client(token=os.environ["DATAROBOT_API_TOKEN"],
          endpoint=os.environ.get("DATAROBOT_ENDPOINT", "https://app.datarobot.com/api/v2"))


def run(slug):
    p = dr.Project.create(sourcedata=os.path.join(D, f"backtest_train_{slug}_1995_2005.csv"),
                          project_name=f"[Demo] 建機長期需要 過去検証 {slug}")
    fl = p.create_featurelist(name="構造ドライバー18", features=FEATURES)
    part = dr.UserTVH(user_partition_col="partition", training_level="train",
                      validation_level="validation")
    p.analyze_and_model(target="units_per_mn_pop", mode=dr.AUTOPILOT_MODE.QUICK,
                        partitioning_method=part, featurelist_id=fl.id,
                        advanced_options=dr.AdvancedOptions(weights="weight"), worker_count=-1)
    p.wait_for_autopilot(verbosity=0)
    model = dr.ModelRecommendation.get(p.id).get_model()
    score_path = os.path.join(D, f"backtest_score_{slug}_2006_2025.csv")
    ds = p.upload_dataset(score_path)
    job = model.request_predictions(ds.id)
    pred = job.get_result_when_complete()
    score = pd.read_csv(score_path)
    score["units_pred"] = pred["prediction"].values * score.population / 1e6
    train = pd.read_csv(os.path.join(D, f"train_{slug}.csv"))[["iso3", "year", "units"]]
    out = score[["iso3", "region", "year", "units_pred"]].merge(train, on=["iso3", "year"])
    out = out.rename(columns={"units": "units_actual"})
    out.to_csv(os.path.join(D, f"backtest_predictions_{slug}.csv"), index=False, encoding="utf-8-sig")
    print(out.groupby("year")[["units_actual", "units_pred"]].sum().round(0))


if __name__ == "__main__":
    for s in sys.argv[1:] or ["general", "mini", "mining"]:
        run(s)
