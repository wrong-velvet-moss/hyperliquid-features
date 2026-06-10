"""STEP 2: market-wide liquidation signal.

EMPIRICAL FINDING (verified live): the public `trades` feed has NO liquidation
flag (fields are only coin/side/px/sz/time/hash/tid/users), so liquidations
cannot be labeled from public data. Two real paths:

  FREE  -> live OI-proxy collector (implemented): see hl_signals/ingest/collector.py
           + hl_signals/research/livepanel.py. activeAssetCtx streams `openInterest`; a sharp
           OI contraction during a price move proxies a liquidation cascade.
  TRUE  -> S3 node archive (labeled, full history) -- blocked behind requester-pays
           + IAM perms; documented below.

------------------------------------------------------------------------------
ORIGINAL S3 PLAN (true labeled liquidations):

Hyperliquid does NOT expose a public liquidation feed or a liquidation flag in
the public `trades` channel. Liquidations are only explicitly marked in the
authenticated per-user `userFills` `liquidation` object. So a market-wide
historical liquidation series must come from one of:

  1. S3 node archive (requester-pays, costs AWS egress) -- the clean path:
       s3://hl-mainnet-node-data/node_fills_by_block
     Each fill preserves a `liquidation` object {liquidatedUser, markPx, method}
     where method in {"market","backstop"}. Parse -> per-coin hourly liquidation
     notional (and long/short split) -> merge into the panel exactly like funding.

  2. Live collection going forward: subscribe to the public `trades` WS and tag
     liquidations heuristically (counterparty == liquidator vault). Lossy.

  3. Third parties: CoinGlass / Coinalyze / Allium liquidation datasets.

Planned signal columns to add to the hourly panel:
    liq_notional_long, liq_notional_short, liq_notional_total, liq_count
Hypothesis to test (same harness as fair value): do liquidation spikes precede
short-horizon reversals (exhaustion) or continuation (cascade)?

Implement `hourly_liquidations_from_s3(coins, start, end) -> DataFrame[ts,coin,...]`
then reuse labels.add_forward_returns + predictive.ic_grid unchanged.
"""

from __future__ import annotations

import pandas as pd


def hourly_liquidations_from_s3(
    coins: list[str], start_ms: int, end_ms: int
) -> pd.DataFrame:  # noqa: ARG001
    raise NotImplementedError(
        "Wire up s3://hl-mainnet-node-data/node_fills_by_block parsing (requester-pays). "
        "See module docstring for the plan."
    )
