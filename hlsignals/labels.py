"""Forward-return labels and derived signals for the predictiveness test."""

from __future__ import annotations

import pandas as pd

DEFAULT_HORIZONS = (1, 4, 8, 24)  # hours


def add_forward_returns(
    panel: pd.DataFrame, horizons=DEFAULT_HORIZONS, price_col: str = "close"
) -> pd.DataFrame:
    """fwd_ret_{h}h = close[t+h]/close[t] - 1, computed within each coin."""
    panel = panel.sort_values(["coin", "ts"]).copy()
    grp = panel.groupby("coin")[price_col]
    for h in horizons:
        panel[f"fwd_ret_{h}h"] = grp.shift(-h) / panel[price_col] - 1.0
    return panel


def add_funding_zscore(panel: pd.DataFrame, window: int = 168) -> pd.DataFrame:
    """Per-coin rolling z-score of funding (default 1-week window). Removes each
    coin's baseline funding level so the signal is 'unusually crowded vs itself'."""
    panel = panel.sort_values(["coin", "ts"]).copy()

    def _z(s: pd.Series) -> pd.Series:
        m = s.rolling(window, min_periods=window // 2).mean()
        sd = s.rolling(window, min_periods=window // 2).std()
        return (s - m) / sd

    panel["funding_z"] = panel.groupby("coin")["fundingRate"].transform(_z)
    return panel
