#!/usr/bin/env python3
"""Run the live collector (free liquidation-proxy path).

Examples:
    uv run hl-collect --n 20            # run until killed (Ctrl-C)
    uv run hl-collect --n 10 --minutes 90 --flush 30
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ..ingest.collector import LiveCollector
from ..ingest.universe import top_perps_by_volume

OUTDIR = Path("data/live")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="top N perps by 24h volume")
    ap.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="stop after N minutes (default: run forever)",
    )
    ap.add_argument("--flush", type=int, default=60, help="flush every N seconds")
    ap.add_argument(
        "--sink",
        choices=["parquet", "db", "both"],
        default="parquet",
        help="where to write: parquet files, TimescaleDB (live), or both",
    )
    args = ap.parse_args()

    coins = top_perps_by_volume(args.n)
    dest = OUTDIR if args.sink != "db" else "TimescaleDB"
    print(
        f"Collecting {len(coins)} coins (sink={args.sink}) -> {dest}\n{coins}",
        flush=True,
    )
    collector = LiveCollector(coins, OUTDIR, flush_secs=args.flush, sink=args.sink)
    try:
        asyncio.run(collector.run(minutes=args.minutes))
    except KeyboardInterrupt:
        collector._flush(force=True)
        print("stopped.")


if __name__ == "__main__":
    main()
