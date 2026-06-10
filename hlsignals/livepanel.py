"""Turn collected live trades + asset-context part-files into a bar panel with an
open-interest liquidation proxy, ready for the same predictive harness."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_live(outdir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    outdir = Path(outdir)

    def _load(sub: str) -> pd.DataFrame:
        files = sorted((outdir / sub).glob("*.parquet"))
        if not files:
            return pd.DataFrame()
        df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df

    return _load("trades"), _load("assetctx")


def resample_panel(trades: pd.DataFrame, ctx: pd.DataFrame, freq: str = "5min") -> pd.DataFrame:
    """Per-coin OHLC + flow + OI bars at `freq`."""
    bars = []
    for coin, g in ctx.groupby("coin"):
        g = g.set_index("ts").sort_index()
        r = pd.DataFrame(
            {
                "markPx": g["markPx"].resample(freq).last(),
                "openInterest": g["openInterest"].resample(freq).last(),
                "premium": g["premium"].resample(freq).mean(),
                "funding": g["funding"].resample(freq).mean(),
            }
        )
        r["coin"] = coin
        bars.append(r)
    panel = pd.concat(bars).reset_index().rename(columns={"index": "ts"})

    if not trades.empty:
        t = trades.copy()
        t["signed"] = np.where(t["side"] == "B", t["sz"], -t["sz"])  # taker-buy positive
        agg = (
            t.set_index("ts")
            .groupby("coin")[["signed", "sz"]]  # select cols -> excludes the group key
            .resample(freq)
            .agg(cvd=("signed", "sum"), vol=("sz", "sum"), ntrades=("sz", "size"))
            .reset_index()
        )
        panel = panel.merge(agg, on=["coin", "ts"], how="left")
    return panel.sort_values(["coin", "ts"]).reset_index(drop=True)


def add_liq_proxy(panel: pd.DataFrame) -> pd.DataFrame:
    """OI-contraction liquidation proxy.

    d_oi < 0 means net positions closed in the bar. Pair the magnitude with the
    bar's price direction to guess which side was flushed:
      long_liq_proxy  : forced longs  (OI down while price down)
      short_liq_proxy : forced shorts (OI down while price up)
    `liq_pressure` is signed: +short flush / -long flush, the directional impulse
    whose predictive value (reversal vs continuation) we then test.
    """
    panel = panel.sort_values(["coin", "ts"]).copy()
    grp = panel.groupby("coin")
    panel["d_oi"] = grp["openInterest"].diff()
    panel["ret_bar"] = grp["markPx"].pct_change()
    closed = (-panel["d_oi"]).clip(lower=0.0)  # magnitude of OI reduction
    down = panel["ret_bar"] < 0
    panel["long_liq_proxy"] = np.where(down, closed, 0.0)
    panel["short_liq_proxy"] = np.where(~down, closed, 0.0)
    panel["liq_pressure"] = panel["short_liq_proxy"] - panel["long_liq_proxy"]
    return panel
