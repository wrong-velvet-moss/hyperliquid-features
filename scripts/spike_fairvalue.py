#!/usr/bin/env python3
"""Predictiveness spike: do funding / premium / funding-z predict forward returns?

Reads data/fairvalue_panel.parquet, computes forward returns, and reports the
information coefficient (IC) for each signal x horizon, plus quantile-bucket
forward returns and a per-coin breakdown. Writes reports/fairvalue_spike.md.

Usage:
    python scripts/spike_fairvalue.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hlsignals.labels import DEFAULT_HORIZONS, add_forward_returns, add_funding_zscore
from hlsignals.predictive import ic_grid, per_coin_ic, quantile_table

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

SIGNALS = ["fundingRate", "premium", "funding_z"]
HORIZONS = list(DEFAULT_HORIZONS)


def main() -> None:
    panel = pd.read_parquet(DATA / "fairvalue_panel.parquet")
    panel = add_forward_returns(panel, HORIZONS)
    panel = add_funding_zscore(panel)

    grid = ic_grid(panel, SIGNALS, HORIZONS)
    headline_h = 8
    headline_sig = "premium"  # strongest signal in the IC grid; funding_z is ~noise
    coin_ic = per_coin_ic(panel, headline_sig, headline_h)
    qt_funding = quantile_table(panel, "fundingRate", f"fwd_ret_{headline_h}h")
    qt_premium = quantile_table(panel, "premium", f"fwd_ret_{headline_h}h")

    span = f"{panel['ts'].min()} -> {panel['ts'].max()}"
    n_rows = len(panel)
    n_coins = panel["coin"].nunique()

    def fmt(df: pd.DataFrame) -> str:
        try:
            return df.to_markdown(index=False, floatfmt=".5f")
        except ImportError:  # `tabulate` not installed -> plain text fallback
            return "```\n" + df.to_string(index=False) + "\n```"

    md = []
    md.append("# Fair-value predictiveness spike (Hyperliquid)\n")
    md.append(f"- Panel: **{n_rows:,}** coin-hours across **{n_coins}** perps")
    md.append(f"- Window: {span}")
    md.append("- Signals: `fundingRate` (hourly funding), `premium` (mark-vs-oracle), "
              "`funding_z` (per-coin 1-week z-score of funding)")
    md.append("- Target: forward simple return over 1/4/8/24h. IC = Spearman rank corr.\n")
    md.append("## Information coefficient (pooled across coins)\n")
    md.append(fmt(grid))
    md.append("\n*`ic`/`p_value` use overlapping windows (optimistic p). "
              "`ic_deoverlap` samples every `horizon` hours to remove overlap — trust that p more.*\n")
    md.append(f"## Forward {headline_h}h return by `fundingRate` quintile (bps)\n")
    md.append(fmt(qt_funding.reset_index()) if not qt_funding.empty else "_insufficient data_")
    md.append(f"\n## Forward {headline_h}h return by `premium` quintile (bps)\n")
    md.append(fmt(qt_premium.reset_index()) if not qt_premium.empty else "_insufficient data_")
    md.append(f"\n## Per-coin IC: `{headline_sig}` -> fwd_ret_{headline_h}h\n")
    md.append(fmt(coin_ic))
    report = "\n".join(md) + "\n"

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "fairvalue_spike.md").write_text(report)

    # console summary
    print(f"Panel: {n_rows:,} coin-hours, {n_coins} perps, {span}\n")
    print("=== Information coefficient (pooled) ===")
    print(grid.to_string(index=False))
    print(f"\n=== Forward {headline_h}h return by premium quintile (bps) ===")
    if not qt_premium.empty:
        print(qt_premium[["mean_ret_bps", "n"]].to_string())
    print(f"\nFull report -> {REPORTS / 'fairvalue_spike.md'}")


if __name__ == "__main__":
    main()
