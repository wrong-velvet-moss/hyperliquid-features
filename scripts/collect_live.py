#!/usr/bin/env python3
"""Run the live collector (free liquidation-proxy path).

Examples:
    python scripts/collect_live.py --n 20            # run until killed (Ctrl-C)
    python scripts/collect_live.py --n 10 --minutes 90 --flush 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hlsignals.collector import LiveCollector
from hlsignals.universe import top_perps_by_volume

OUTDIR = Path(__file__).resolve().parents[1] / "data" / "live"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="top N perps by 24h volume")
    ap.add_argument("--minutes", type=float, default=None, help="stop after N minutes (default: run forever)")
    ap.add_argument("--flush", type=int, default=60, help="flush part-files every N seconds")
    args = ap.parse_args()

    coins = top_perps_by_volume(args.n)
    print(f"Collecting {len(coins)} coins -> {OUTDIR}\n{coins}", flush=True)
    collector = LiveCollector(coins, OUTDIR, flush_secs=args.flush)
    try:
        asyncio.run(collector.run(minutes=args.minutes))
    except KeyboardInterrupt:
        collector._flush(force=True)
        print("stopped.")


if __name__ == "__main__":
    main()
