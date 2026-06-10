"""Load collected live parquet (``data/live``) into TimescaleDB.

Reads the rotating part-files written by the WS collector, maps them onto the
``assetctx`` / ``trades`` / ``book_levels`` hypertable schema, and idempotently
upserts them so the Grafana stack has data to chart. Run after the stack is up:

    make up
    make collect   # gather some data first (or run it for a while)
    make load
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

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


def _load_book(outdir: Path) -> pd.DataFrame:
    """Read collected L2 book part-files, ts (ms) -> tz-aware ``time``."""
    files = sorted((outdir / "book").glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns="ts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="data/live",
        help="collector output dir holding trades/, assetctx/, book/ (default: data/live)",
    )
    args = parser.parse_args()
    outdir = Path(args.outdir)

    trades, ctx = load_live(outdir)
    book = _load_book(outdir)
    if trades.empty and ctx.empty and book.empty:
        print(f"no parquet found under {args.outdir!r}; run `make collect` first")
        return

    with store.connect() as conn:
        n_ctx = (
            store.upsert_assetctx(conn, ctx.rename(columns=ASSETCTX_RENAME))
            if not ctx.empty
            else 0
        )
        n_trades = (
            store.upsert_trades(conn, trades.rename(columns={"ts": "time"}))
            if not trades.empty
            else 0
        )
        n_book = store.upsert_book(conn, book) if not book.empty else 0

    print(
        f"loaded assetctx={n_ctx} trades={n_trades} book={n_book} from {args.outdir!r}"
    )


if __name__ == "__main__":
    main()
