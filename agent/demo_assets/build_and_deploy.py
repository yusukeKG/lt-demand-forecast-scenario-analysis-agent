"""DataRobot で 3機種のモデルを構築し、デプロイまで行うスクリプト (datarobot Python SDK 3.x 想定)

事前準備:
  pip install datarobot pandas python-dotenv
  環境変数を設定 (APIトークンはチャットに貼らないこと)
    DATAROBOT_API_TOKEN=...          # DataRobot の「APIキーとツール」で発行
    DATAROBOT_ENDPOINT=https://app.datarobot.com/api/v2   # 環境に合わせて変更 (例: app.jp.datarobot.com)
実行:
  python build_and_deploy.py            # 3機種すべて
  python build_and_deploy.py general    # 一般建機だけ
出力:
  deployments.json  (機種ごとのプロジェクトID・モデルID・デプロイID)

※ SDKのバージョンによって関数名が異なる場合があります。エラーが出たら、インストール済みの
  SDKバージョンのドキュメントに合わせて該当箇所を修正してください。
"""
import json
import os
import sys

import datarobot as dr

try:  # .env ファイルがあれば読み込む (APIトークンをコードやチャットに書かないため)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from features import FEATURES

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CATS = {"general": "一般建機", "mini": "ミニショベル", "mining": "鉱山機械"}
TARGET = "units_per_mn_pop"

dr.Client(token=os.environ["DATAROBOT_API_TOKEN"],
          endpoint=os.environ.get("DATAROBOT_ENDPOINT", "https://app.datarobot.com/api/v2"))


def build(slug):
    name = f"[Demo] 建機長期需要 {CATS[slug]}"
    print(f"--- {name}: データをアップロード中")
    project = dr.Project.create(sourcedata=os.path.join(DATA_DIR, f"train_{slug}.csv"),
                                project_name=name)
    fl = project.create_featurelist(name="構造ドライバー18", features=FEATURES)

    # 年でデータを分ける (1995-2015: 学習 / 2016-2020: 検証 / 2021-2025: ホールドアウト)
    partition = dr.UserTVH(user_partition_col="partition", training_level="train",
                           validation_level="validation", holdout_level="holdout")
    opts = dr.AdvancedOptions(weights="weight")
    print("    オートパイロット開始 (クイック)")
    project.analyze_and_model(target=TARGET, mode=dr.AUTOPILOT_MODE.QUICK,
                              partitioning_method=partition, featurelist_id=fl.id,
                              advanced_options=opts, worker_count=-1)
    project.wait_for_autopilot(verbosity=0)

    rec = dr.ModelRecommendation.get(project.id)
    model = rec.get_model()
    print(f"    推奨モデル: {model.model_type} (id={model.id})")

    # 登録 → デプロイ
    reg = dr.RegisteredModelVersion.create_for_leaderboard_item(
        model_id=model.id, name=f"{name} v1", registered_model_name=name)
    servers = dr.PredictionServer.list()
    kwargs = {"default_prediction_server_id": servers[0].id} if servers else {}
    dep = dr.Deployment.create_from_registered_model_version(
        model_package_id=reg.id, label=name, description="建機メーカー向けデモ: 人口100万人あたり販売台数を予測",
        max_wait=1800, **kwargs)
    print(f"    デプロイ完了: deployment_id={dep.id}")
    return {"project_id": project.id, "model_id": model.id, "deployment_id": dep.id}


if __name__ == "__main__":
    targets = sys.argv[1:] or list(CATS)
    path = os.path.join(os.path.dirname(__file__), "deployments.json")
    result = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    # 説明用コメントは deployments.example.json と同じものを先頭に残す
    example = os.path.join(os.path.dirname(__file__), "deployments.example.json")
    comment = json.load(open(example, encoding="utf-8")).get("_comment", [])[1:] if os.path.exists(example) else []
    result = {"_comment": comment, **{k: v for k, v in result.items() if k != "_comment"}}
    for slug in targets:
        result[slug] = build(slug)
        json.dump(result, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
