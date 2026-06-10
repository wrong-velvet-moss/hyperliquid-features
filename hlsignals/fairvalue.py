"""Build an hourly fair-value + price panel from public Hyperliquid data.

Signals captured per (coin, hour):
  - fundingRate : realized hourly funding (longs pay shorts when positive)
  - premium     : (perp mark - oracle) / oracle, i.e. how far the perp trades
                  from Hyperliquid's CEX-weighted-median fair value (the oracle)

Both are the publicly available expression of the "fair value deviation" idea.
"""
from __future__ import annotations

import pandas as pd

from .api import HyperliquidInfo


def fetch_funding(client: HyperliquidInfo, coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    out: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        batch = client.funding_history(coin, cur, end_ms)
        if not batch:
            break
        out.extend(batch)
        last_t = int(batch[-1]["time"])
        if last_t <= cur:  # no forward progress -> done
            break
        cur = last_t + 1
        if len(batch) < 2:
            break
    if not out:
        return pd.DataFrame(columns=["ts", "coin", "fundingRate", "premium"])
    df = pd.DataFrame(out).drop_duplicates(subset="time")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    # Funding timestamps carry a few-ms jitter past the hour (e.g. 02:00:00.006);
    # floor to the hour so they align exactly with candle open times on merge.
    df["ts"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True).dt.floor("h")
    df["coin"] = coin
    return (
        df[["ts", "coin", "fundingRate", "premium"]]
        .drop_duplicates(subset="ts", keep="last")
        .sort_values("ts")
        .reset_index(drop=True)
    )


def fetch_candles(client: HyperliquidInfo, coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = client.candle_snapshot(coin, interval, start_ms, end_ms)
    if not rows:
        return pd.DataFrame(columns=["ts", "coin", "open", "high", "low", "close", "vol", "trades"])
    df = pd.DataFrame(rows).rename(
        columns={"t": "open_ms", "o": "open", "h": "high", "l": "low", "c": "close", "v": "vol", "n": "trades"}
    )
    for col in ["open", "high", "low", "close", "vol"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["open_ms"].astype("int64"), unit="ms", utc=True)
    df["coin"] = coin
    return df[["ts", "coin", "open", "high", "low", "close", "vol", "trades"]].sort_values("ts").reset_index(drop=True)


def build_panel(funding: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """Hourly spine = candles; left-join funding/premium on the hour open."""
    panel = candles.merge(funding, on=["ts", "coin"], how="left")
    return panel.sort_values(["coin", "ts"]).reset_index(drop=True)
