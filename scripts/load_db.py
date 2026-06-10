"""Load collected live parquet (``data/live``) into TimescaleDB.

Reads the rotating part-files written by the WS collector, maps them onto the
``assetctx`` / ``trades`` hypertable schema, and idempotently upserts them so the
Grafana stack has data to chart. Run after the stack is up:

    make up
    make collect   # gather some data first (or run it for a while)
    make load
"""

from __future__ import annotations

import argparse

from hlsignals import store
from hlsignals.livepanel import load_live

# Collector parquet column -> assetctx hypertable column.
ASSETCTX_RENAME = {
    "ts": "time",
    "markPx": "mark_px",
    "oraclePx": "oracle_px",
    "midPx": "mid_px",
    "openInterest": "open_interest",
    "dayNtlVlm": "day_ntl_vlm",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="data/live",
        help="collector output dir holding trades/ and assetctx/ (default: data/live)",
    )
    args = parser.parse_args()

    trades, ctx = load_live(args.outdir)
    if trades.empty and ctx.empty:
        print(f"no parquet found under {args.outdir!r}; run `make collect` first")
        return

    with store.connect() as conn:
        n_ctx = 0
        if not ctx.empty:
            n_ctx = store.upsert_assetctx(conn, ctx.rename(columns=ASSETCTX_RENAME))
        n_trades = 0
        if not trades.empty:
            n_trades = store.upsert_trades(conn, trades.rename(columns={"ts": "time"}))

    print(f"loaded assetctx={n_ctx} trades={n_trades} from {args.outdir!r}")


if __name__ == "__main__":
    main()
