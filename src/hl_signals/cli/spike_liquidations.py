#!/usr/bin/env python3
"""Predictiveness spike for the OI-based liquidation proxy.

Loads collected live data (data/live/), resamples to bars, builds the liquidation
proxy, and runs the SAME IC harness as the fair-value spike. Horizons are in BARS
(at the chosen --freq), not hours.

Usage:
    uv run hl-collect --n 20            # let this run for hours/days first
    uv run hl-spike-liquidations --freq 5min
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..research.labels import add_forward_returns
from ..research.livepanel import add_liq_proxy, load_live, resample_panel
from ..research.predictive import ic_grid, quantile_table

LIVE = Path("data/live")
SIGNALS = [
    "liq_pressure",
    "long_liq_proxy",
    "short_liq_proxy",
    "cvd",
    "d_oi",
    "premium",
]
HORIZONS = [1, 3, 6, 12]  # bars
MIN_BARS = 500  # below this the test is meaningless; keep collecting


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--freq", default="5min", help="bar size (pandas offset, e.g. 1min/5min/15min)"
    )
    args = ap.parse_args()

    trades, ctx = load_live(LIVE)
    if ctx.empty:
        raise SystemExit("no collected data in data/live/ — run hl-collect first")

    panel = add_liq_proxy(resample_panel(trades, ctx, freq=args.freq))
    panel = add_forward_returns(panel, HORIZONS, price_col="markPx")
    n = panel["ret_bar"].notna().sum()
    span = f"{panel['ts'].min()} -> {panel['ts'].max()}"
    print(
        f"{len(panel)} bars @{args.freq} across {panel['coin'].nunique()} coins | {span}"
    )

    if n < MIN_BARS:
        print(
            f"\n[!] Only ~{n} usable bars. This is a PIPELINE SMOKE TEST, not a real result —"
        )
        print(
            f"    let hl-collect run until you have >~{MIN_BARS} bars (hours/days), then rerun."
        )

    grid = ic_grid(panel, SIGNALS, HORIZONS)
    print("\n=== Information coefficient: proxy signals -> forward bar returns ===")
    print(grid.to_string(index=False))

    qt = quantile_table(panel, "liq_pressure", "fwd_ret_3h")
    if not qt.empty:
        print("\n=== forward 3-bar return by liq_pressure quintile (bps) ===")
        print((qt["mean_ret"] * 1e4).round(2).to_string())


if __name__ == "__main__":
    main()
