"""Scoring rows for the deployments, built exactly like make_datarobot_data.py."""

import pandas as pd

from agent.forecast import data
from agent.forecast.features import FEATURES, build_features

ID_COLS = ["iso3", "year", "population"]
LAG_HISTORY_FROM = 2019  # ラグ計算のために前につなげる実績の開始年


def build_score_frame(fut: pd.DataFrame, slug: str) -> pd.DataFrame:
    """Features for 2026-2050 for one scenario and category.

    The 2019-2025 actuals are prepended so lags / 5-year changes are computed on
    real history, then only forecast years are kept.
    """
    isos = data.category_countries(slug)
    hist = data.drivers_history()
    h = hist[hist.iso3.isin(isos) & (hist.year >= LAG_HISTORY_FROM)][data.BASE_COLS]
    f = fut[fut.iso3.isin(isos)][data.BASE_COLS]
    x = build_features(pd.concat([h, f]), data.country_master())  # type: ignore[no-untyped-call]
    x = x[x.year > data.BASE_YEAR].copy()
    x["scenario_id"] = fut.scenario_id.iloc[0]
    return x[["scenario_id", *ID_COLS, *FEATURES]].round(5).reset_index(drop=True)
