"""driver_overrides: what-if edits to one scenario's future drivers.

Each override is ``{target, driver, value, from_year[, to_year]}``. ``target`` is
an iso3 code, a region name, a Japanese country name, or ``world``. ``to_year`` is
an optional extension: after it, the scenario's own year-on-year path resumes from
the new level (e.g. "銅価格が今後10年、年3%ずつ上がったら" = 2026-2035).

Units:
- ``*_shift_pt``: percentage points (0.5 = +0.5pt)
- ``*_rate``: annual rate as a fraction (0.03 = 年3%). Values with |v| >= 1 are
  read as percent and divided by 100.
- ``gfcf_pct_gdp``: target level in % of GDP, reached over 5 years.
"""

from typing import Any

import numpy as np
import pandas as pd

from agent.forecast import data
from agent.forecast.scenarios import PCOL, recompute_derived

PRICE_DRIVERS = {f"{k}_price_change_rate": col for k, col in PCOL.items()}
COUNTRY_DRIVERS = {
    "gdp_growth_shift_pt",
    "urban_pct_shift_pt",
    "gfcf_pct_gdp",
    "coal_growth_rate",
}
ALL_DRIVERS = COUNTRY_DRIVERS | set(PRICE_DRIVERS)

URBAN_CAP_PCT = 95.0
GFCF_TRANSITION_YEARS = 5

DRIVER_JA = {
    "gdp_growth_shift_pt": "実質GDP成長率の上乗せ",
    "urban_pct_shift_pt": "都市化率の上乗せ",
    "gfcf_pct_gdp": "投資比率（固定資本形成のGDP比）",
    "coal_growth_rate": "石炭生産量の年率変化",
    "copper_price_change_rate": "銅価格の年率変化",
    "ironore_price_change_rate": "鉄鉱石価格の年率変化",
    "coal_price_change_rate": "石炭価格の年率変化",
    "gold_price_change_rate": "金価格の年率変化",
}


def _as_rate(value: float) -> float:
    return value / 100 if abs(value) >= 1 else value


def resolve_target(target: str) -> list[str]:
    """iso3 list for a target (iso3 / region / country_ja / world)."""
    master = data.country_master()
    t = str(target).strip()
    if t.lower() in ("world", "世界", "全世界", "global"):
        return list(master.iso3)
    if t.upper() in set(master.iso3):
        return [t.upper()]
    for col in ("region", "country_ja", "country_en", "sub_region"):
        hit = master[master[col] == t]
        if len(hit):
            return list(hit.iso3)
    raise ValueError(
        f"対象が見つかりません: {target}（国コード・地域名・world のいずれか）"
    )


def _window(years: pd.Series, o: dict[str, Any]) -> pd.Series:
    start = int(o.get("from_year") or data.BASE_YEAR + 1)
    end = int(o.get("to_year") or 9999)
    return (years >= start) & (years <= end)


def _replace_growth(
    level: pd.Series, base_value: float, in_window: pd.Series, rate: float
) -> pd.Series:
    """Rebuild a yearly level series with growth ``rate`` inside the window.

    ``level`` is sorted by year (2026..2050); outside the window the original
    year-on-year ratios are kept, so the path continues from the new level.
    """
    orig = level.to_numpy(dtype=float)
    prev = np.concatenate([[base_value], orig[:-1]])
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(prev > 0, orig / prev, 1.0)
    ratio = np.where(in_window.to_numpy(), 1 + rate, ratio)
    return pd.Series(base_value * np.cumprod(ratio), index=level.index)


def validate(overrides: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalise and validate overrides; raises ValueError with a Japanese message."""
    out = []
    for o in overrides or []:
        driver = str(o.get("driver", "")).strip()
        if driver not in ALL_DRIVERS:
            raise ValueError(
                f"未知のドライバーです: {driver}（使えるもの: {', '.join(sorted(ALL_DRIVERS))}）"
            )
        if o.get("value") is None:
            raise ValueError(f"{driver} の value が指定されていません")
        target = str(o.get("target") or "world")
        if driver in PRICE_DRIVERS and target.lower() not in (
            "world",
            "世界",
            "全世界",
            "global",
        ):
            raise ValueError(
                "資源価格は世界共通です。target は world を指定してください"
            )
        resolve_target(target)
        item = {
            "target": target,
            "driver": driver,
            "value": float(o["value"]),
            "from_year": int(o.get("from_year") or data.BASE_YEAR + 1),
        }
        if o.get("to_year"):
            item["to_year"] = int(o["to_year"])
        out.append(item)
    return out


def apply_driver_overrides(
    fut: pd.DataFrame, overrides: list[dict[str, Any]] | None
) -> pd.DataFrame:
    """Apply overrides to one scenario's future drivers (file 08 layout).

    Derived columns (gdp_ppp_bn, urban_pop_mn, gdp_growth_pct) are recomputed.
    """
    items = validate(overrides)
    if not items:
        return fut
    d = fut.sort_values(["iso3", "year"]).reset_index(drop=True).copy()
    hist = data.drivers_history()
    h25 = hist[hist.year == data.BASE_YEAR].set_index("iso3")
    p25 = data.commodity_prices_history().set_index("year").loc[data.BASE_YEAR]

    for o in items:
        driver, value = o["driver"], o["value"]
        in_win = _window(d.year, o)
        if driver in PRICE_DRIVERS:
            col = PRICE_DRIVERS[driver]
            rate = _as_rate(value)
            for _, idx in d.groupby("iso3").groups.items():
                d.loc[idx, col] = _replace_growth(
                    d.loc[idx, col], float(p25[col]), in_win[idx], rate
                )
            continue
        isos = set(resolve_target(o["target"]))
        for iso, idx in d.groupby("iso3").groups.items():
            if iso not in isos:
                continue
            w = in_win[idx]
            if driver == "gdp_growth_shift_pt":
                # per-capita growth + value pt, accumulated (population unchanged)
                boost = np.cumprod(np.where(w, 1 + value / 100, 1.0))
                d.loc[idx, "gdp_pc_ppp_const2021"] *= boost
            elif driver == "urban_pct_shift_pt":
                d.loc[idx, "urban_pct"] = np.where(
                    w,
                    np.minimum(d.loc[idx, "urban_pct"] + value, URBAN_CAP_PCT),
                    d.loc[idx, "urban_pct"],
                )
            elif driver == "gfcf_pct_gdp":
                # a level target, so to_year does not apply: the new level is kept
                yrs = d.loc[idx, "year"]
                ramp = ((yrs - o["from_year"] + 1) / GFCF_TRANSITION_YEARS).clip(0, 1)
                cur = d.loc[idx, "gfcf_pct_gdp"]
                d.loc[idx, "gfcf_pct_gdp"] = cur + (value - cur) * ramp
            elif driver == "coal_growth_rate":
                d.loc[idx, "coal_prod_twh"] = _replace_growth(
                    d.loc[idx, "coal_prod_twh"],
                    float(h25.loc[iso, "coal_prod_twh"]),
                    w,
                    _as_rate(value),
                )
    d = recompute_derived(d)
    return d


def describe(o: dict[str, Any]) -> str:
    """One-line Japanese description of an override (for confirmations and logs)."""
    name = DRIVER_JA.get(o["driver"], o["driver"])
    period = (
        f"{o['from_year']}年以降"
        if not o.get("to_year")
        else f"{o['from_year']}〜{o['to_year']}年"
    )
    v = o["value"]
    if o["driver"].endswith("_rate"):
        val = f"年{_as_rate(v) * 100:+.1f}%"
    elif o["driver"].endswith("_pt"):
        val = f"{v:+.1f}ポイント"
    else:
        val = f"{v:.1f}%へ{GFCF_TRANSITION_YEARS}年かけて移行"
    return f"{o['target']}：{name}を{period} {val}"
