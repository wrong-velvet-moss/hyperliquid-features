#!/usr/bin/env python3
"""Predictiveness spike for real stop / take-profit (trigger) clusters.

Roadmap #2: do dense trigger clusters predict the location/direction of the next
move? Reads the real per-address trigger orders + the live price spine from
TimescaleDB, builds proximity-weighted cluster features (``research/triggers.py``),
and runs the SAME IC harness as the other spikes. Horizons are in BARS (at the
chosen --freq), not hours.

Hypothesis: stop clusters cascade (continuation, +IC), take-profits fade
(mean-reversion). The harness reports the empirical sign.

Usage:
    make up && make live                 # stream assetctx into the DB (price spine)
    uv run hl-poll-triggers --source both  # sweep real stop/TP orders into the DB
    # let both accumulate (hours/days), then:
    uv run hl-spike-triggers --freq 15min
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ..research.labels import add_forward_returns
from ..research.predictive import ic_grid, per_coin_ic, quantile_table
from ..research.triggers import build_trigger_panel, load_assetctx, load_triggers

REPORTS = Path("reports")

# Only scale-free / normalised signals are pooled across coins (raw notionals
# would mostly measure coin size). trigger_density is an unsigned magnitude
# diagnostic, surfaced via its quantile table rather than read as a directional IC.
SIGNALS = [
    "net_trigger_skew",
    "stop_imbalance_z",
    "tp_imbalance_z",
    "stop_imbalance_oi",
    "tp_imbalance_oi",
    "trigger_density",
]
HORIZONS = [1, 3, 6, 12]  # bars
HEADLINE_H = 3
HEADLINE_SIG = "net_trigger_skew"
MIN_BARS = 500  # below this the test is meaningless; keep collecting


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--freq", default="15min", help="bar size (pandas offset, e.g. 5min/15min/1h)"
    )
    ap.add_argument("--lookback-days", type=int, default=30, help="DB history to load")
    ap.add_argument(
        "--decay-bps", type=float, default=50.0, help="proximity decay scale (bps)"
    )
    ap.add_argument(
        "--max-bps", type=float, default=300.0, help="ignore triggers beyond this (bps)"
    )
    ap.add_argument(
        "--max-snap-age",
        type=float,
        default=2.0,
        help="null a bar if its trigger snapshot is older than this many bars",
    )
    ap.add_argument(
        "--coins", nargs="*", default=None, help="restrict to these coins (default all)"
    )
    args = ap.parse_args()

    ctx = load_assetctx(args.coins, args.lookback_days)
    if ctx.empty:
        raise SystemExit(
            "no assetctx in DB — run `make up && make live` to stream the price spine"
        )
    triggers = load_triggers(args.coins, args.lookback_days)
    if triggers.empty:
        raise SystemExit(
            "no trigger_orders in DB — run `make triggers` (hl-poll-triggers) first"
        )

    panel = build_trigger_panel(
        ctx,
        triggers,
        freq=args.freq,
        decay_bps=args.decay_bps,
        max_bps=args.max_bps,
        max_snap_age=args.max_snap_age,
    )
    panel = add_forward_returns(panel, HORIZONS, price_col="mark_px")

    n = int(panel["fwd_ret_1h"].notna().sum())
    span = f"{panel['ts'].min()} -> {panel['ts'].max()}"
    n_coins = panel["coin"].nunique()
    print(f"{len(panel)} bars @{args.freq} across {n_coins} coins | {span}")
    if n < MIN_BARS:
        print(
            f"\n[!] Only ~{n} usable bars. This is a PIPELINE SMOKE TEST, not a real "
            f"result —\n    let hl-poll-triggers + the live collector run until you have "
            f">~{MIN_BARS} bars (hours/days), then rerun."
        )

    grid = ic_grid(panel, SIGNALS, HORIZONS)
    qt_skew = quantile_table(panel, HEADLINE_SIG, f"fwd_ret_{HEADLINE_H}h")
    qt_density = quantile_table(panel, "trigger_density", f"fwd_ret_{HEADLINE_H}h")
    coin_ic = per_coin_ic(panel, HEADLINE_SIG, HEADLINE_H)

    def fmt(df: pd.DataFrame) -> str:
        try:
            return df.to_markdown(index=False, floatfmt=".5f")
        except ImportError:  # `tabulate` not installed -> plain text fallback
            return "```\n" + df.to_string(index=False) + "\n```"

    md = []
    md.append("# Trigger-cluster predictiveness spike (Hyperliquid)\n")
    md.append(
        f"- Panel: **{len(panel):,}** coin-bars @{args.freq} across **{n_coins}** perps"
    )
    md.append(f"- Window: {span}")
    md.append(
        f"- Features: proximity-weighted (decay {args.decay_bps:.0f}bps, cutoff "
        f"{args.max_bps:.0f}bps) stop/TP notional near price, as-of the latest sweep"
    )
    md.append(
        "- Signals: `net_trigger_skew` (signed cluster location), `stop_imbalance` / "
        "`tp_imbalance` (z-scored + OI-normalised), `trigger_density` (magnitude)"
    )
    md.append(
        "- Target: forward bar return over 1/3/6/12 bars. IC = Spearman rank corr.\n"
    )
    md.append("## Information coefficient (pooled across coins)\n")
    md.append(fmt(grid))
    md.append(
        "\n*`ic`/`p_value` use overlapping windows (optimistic p). `ic_deoverlap` "
        "samples every `horizon` bars to remove overlap — trust that p more. "
        "Positive IC on the stop signals ⇒ continuation, the cascade hypothesis.*\n"
    )
    md.append(
        f"## Forward {HEADLINE_H}-bar return by `{HEADLINE_SIG}` quintile (bps)\n"
    )
    md.append(
        fmt(qt_skew.reset_index()) if not qt_skew.empty else "_insufficient data_"
    )
    md.append(
        f"\n## Forward {HEADLINE_H}-bar return by `trigger_density` quintile (bps)\n"
    )
    md.append(
        fmt(qt_density.reset_index()) if not qt_density.empty else "_insufficient data_"
    )
    md.append(f"\n## Per-coin IC: `{HEADLINE_SIG}` -> fwd_ret_{HEADLINE_H}h\n")
    md.append(fmt(coin_ic) if not coin_ic.empty else "_insufficient data_")
    report = "\n".join(md) + "\n"

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / "triggers_spike.md"
    out_path.write_text(report)

    # console summary
    print("\n=== Information coefficient: trigger signals -> forward bar returns ===")
    print(grid.to_string(index=False))
    if not qt_skew.empty:
        print(
            f"\n=== Forward {HEADLINE_H}-bar return by {HEADLINE_SIG} quintile (bps) ==="
        )
        print((qt_skew["mean_ret"] * 1e4).round(2).to_string())
    print(f"\nFull report -> {out_path}")


if __name__ == "__main__":
    main()
