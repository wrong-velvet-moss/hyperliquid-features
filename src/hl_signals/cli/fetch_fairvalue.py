#!/usr/bin/env python3
"""Pull hourly funding/premium + OHLCV for the top-N perps -> data/fairvalue_panel.parquet.

Usage:
    uv run hl-fetch-fairvalue --n 20 --days 120
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from ..api import HyperliquidInfo
from ..ingest.fairvalue import build_panel, fetch_candles, fetch_funding
from ..ingest.universe import perp_contexts

DATA = Path("data")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="top N perps by 24h volume")
    ap.add_argument("--days", type=int, default=120, help="lookback window in days")
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    client = HyperliquidInfo()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    ctx = perp_contexts(client)
    coins = ctx["coin"].head(args.n).tolist()
    print(f"Top {args.n} perps by 24h notional volume:")
    for _, r in ctx.head(args.n).iterrows():
        print(
            f"  {r['coin']:<8} vol=${r['dayNtlVlm'] / 1e6:8.1f}M  OI=${r['openInterest'] / 1e6:7.1f}M"
        )
    DATA.mkdir(exist_ok=True)
    ctx.head(args.n).to_parquet(DATA / "universe.parquet", index=False)

    panels = []
    for i, coin in enumerate(coins, 1):
        try:
            funding = fetch_funding(client, coin, start_ms, end_ms)
            candles = fetch_candles(client, coin, args.interval, start_ms, end_ms)
            panel = build_panel(funding, candles)
            panels.append(panel)
            print(
                f"[{i:>2}/{len(coins)}] {coin:<8} candles={len(candles):>4}  funding={len(funding):>4}"
            )
        except Exception as exc:  # keep going; one bad coin shouldn't sink the run
            print(f"[{i:>2}/{len(coins)}] {coin:<8} FAILED: {exc}")

    if not panels:
        raise SystemExit("no data fetched")
    out = pd.concat(panels, ignore_index=True)
    dest = DATA / "fairvalue_panel.parquet"
    out.to_parquet(dest, index=False)
    print(f"\nSaved {len(out):,} rows across {out['coin'].nunique()} coins -> {dest}")
    print(f"Window: {out['ts'].min()}  ->  {out['ts'].max()}")


if __name__ == "__main__":
    main()
