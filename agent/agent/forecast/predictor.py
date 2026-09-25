"""DataRobot real-time prediction client for the three category deployments.

Credentials are read from DATAROBOT_API_TOKEN / DATAROBOT_ENDPOINT only. Error
messages are sanitised before they leave this module: the DataRobot SDK embeds
the API token in some exception texts, so raw exceptions are never surfaced.
"""

import io
import logging
import os
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
import requests

from agent.forecast import data
from agent.forecast.features import FEATURES

logger = logging.getLogger(__name__)

MAX_ROWS_PER_REQUEST = 3800
REQUEST_TIMEOUT_S = 60
PREDICTION_ID_COLS = ["iso3", "year", "population", "scenario_id"]


class PredictionError(RuntimeError):
    """Prediction failure with a message that is safe to show to users."""


def sanitize(text: str) -> str:
    """Remove anything that looks like a credential from an error message."""
    token = os.environ.get("DATAROBOT_API_TOKEN", "")
    if token:
        text = text.replace(token, "***")
    text = re.sub(r"(?i)(bearer|token)(\s*(of)?\s*[\"':= ]\s*)\S+", r"\1\2***", text)
    return re.sub(r"[A-Za-z0-9+/=_-]{40,}", "***", text)


def _credentials() -> tuple[str, str]:
    endpoint = os.environ.get("DATAROBOT_ENDPOINT", "").rstrip("/")
    token = os.environ.get("DATAROBOT_API_TOKEN", "")
    if not endpoint or not token:
        raise PredictionError(
            "DataRobot の接続情報（エンドポイント／APIキー）が設定されていません"
        )
    return endpoint, token


def _post(
    deployment_id: str, frame: pd.DataFrame, params: dict[str, Any]
) -> list[dict[str, Any]]:
    endpoint, token = _credentials()
    buf = io.StringIO()
    frame.to_csv(buf, index=False)
    try:
        r = requests.post(
            f"{endpoint}/deployments/{deployment_id}/predictions",
            params=params,
            data=buf.getvalue().encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/csv; charset=UTF-8",
            },
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise PredictionError(
            f"DataRobot への接続に失敗しました（{type(e).__name__}）"
        ) from None
    if not r.ok:
        detail = ""
        try:
            detail = str(r.json().get("message", ""))[:200]
        except ValueError:
            pass
        raise PredictionError(
            sanitize(f"予測リクエストが失敗しました（HTTP {r.status_code}）{detail}")
        )
    rows: list[dict[str, Any]] = r.json()["data"]
    return sorted(rows, key=lambda x: int(x["rowId"]))


def _request_frame(score: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in PREDICTION_ID_COLS if c in score.columns] + FEATURES
    return score[cols]


def predict(slug: str, score: pd.DataFrame) -> pd.Series:
    """Predicted units per million population, index-aligned with ``score``."""
    deps = data.load_deployments()
    if slug not in deps:
        raise PredictionError(f"{data.CATEGORIES[slug]}のモデルは準備中です")
    dep_id = deps[slug]["deployment_id"]
    frame = _request_frame(score)
    chunks = [
        frame.iloc[i : i + MAX_ROWS_PER_REQUEST]
        for i in range(0, len(frame), MAX_ROWS_PER_REQUEST)
    ]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda c: _post(dep_id, c, {}), chunks))
    values = [float(row["prediction"]) for part in results for row in part]
    return pd.Series(values, index=score.index, name="prediction")


def predict_many(scores: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """Predict several categories in parallel. Raises on the first failure."""
    with ThreadPoolExecutor(max_workers=len(scores) or 1) as ex:
        futures = {slug: ex.submit(predict, slug, s) for slug, s in scores.items()}
        return {slug: f.result() for slug, f in futures.items()}


def explain(
    slug: str, rows: pd.DataFrame, max_explanations: int = 5
) -> list[dict[str, Any]]:
    """Prediction and top-N explanations for a handful of rows.

    Returns ``[{"prediction": float, "explanations": [{feature, strength, ...}]}]``.
    """
    deps = data.load_deployments()
    if slug not in deps:
        raise PredictionError(f"{data.CATEGORIES[slug]}のモデルは準備中です")
    out = _post(
        deps[slug]["deployment_id"],
        _request_frame(rows),
        {"maxExplanations": max_explanations},
    )
    return [
        {
            "prediction": float(r["prediction"]),
            "explanations": r.get("predictionExplanations") or [],
        }
        for r in out
    ]


def _sdk_client() -> Any:
    import datarobot as dr

    endpoint, token = _credentials()
    return dr.Client(token=token, endpoint=endpoint)


def feature_impact(slug: str) -> list[dict[str, Any]]:
    """Feature Impact of the deployed model (fallback when explanations fail)."""
    import datarobot as dr

    info = data.load_deployments().get(slug) or {}
    if not info.get("project_id") or not info.get("model_id"):
        raise PredictionError(
            "特徴量のインパクトを取得するためのモデル情報がありません"
        )
    try:
        _sdk_client()
        model = dr.Model.get(info["project_id"], info["model_id"])
        fi: Sequence[dict[str, Any]] = model.get_or_request_feature_impact(max_wait=120)
    except Exception as e:  # noqa: BLE001 - SDK raises many types; message is sanitised
        raise PredictionError(
            sanitize(f"特徴量のインパクトを取得できませんでした（{type(e).__name__}）")
        ) from None
    return [
        {"feature": f["featureName"], "impact": float(f.get("impactNormalized") or 0.0)}
        for f in fi
    ]


def holdout_relative_error(slug: str) -> float:
    """Unit-weighted relative error of the model on the 2021-2025 holdout rows."""
    import datarobot as dr

    info = data.load_deployments().get(slug) or {}
    if not info.get("project_id") or not info.get("model_id"):
        raise PredictionError(
            "ホールドアウト誤差を計算するためのモデル情報がありません"
        )
    try:
        _sdk_client()
        model = dr.Model.get(info["project_id"], info["model_id"])
        try:
            job = model.request_training_predictions(dr.enums.DATA_SUBSET.HOLDOUT)
            tp = job.get_result_when_complete(max_wait=300)
        except dr.errors.ClientError:
            tp = next(
                t
                for t in dr.TrainingPredictions.list(info["project_id"])
                if t.model_id == info["model_id"] and t.data_subset == "holdout"
            )
        pred = tp.get_all_as_dataframe()
    except Exception as e:  # noqa: BLE001
        raise PredictionError(
            sanitize(f"ホールドアウト予測を取得できませんでした（{type(e).__name__}）")
        ) from None
    train = data.train_data(slug)
    hold = train[train.partition == "holdout"].reset_index()
    merged = pred.merge(hold, left_on="row_id", right_on="index")
    if merged.empty:
        raise PredictionError(
            "ホールドアウト予測と学習データを突き合わせられませんでした"
        )
    units_pred = merged.prediction * merged.population / 1e6
    return float((units_pred - merged.units).abs().sum() / merged.units.abs().sum())
