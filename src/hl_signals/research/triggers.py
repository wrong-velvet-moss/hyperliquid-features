"""Turn collected stop/take-profit (trigger) orders into a bar panel of
cluster features, ready for the same predictive harness as the other spikes.

Unlike the OI-liquidation proxy (which reads parquet), the real trigger orders
and the live price spine only live in TimescaleDB, so this module reads from the
DB. Each sweep of ``hl-poll-triggers`` is one snapshot of every trader's resting
trigger orders; we as-of join the most recent snapshot onto a regular price grid
and measure how much trigger liquidity sits near price, and on which side.

Sign conventions (the trigger's own ``side`` is the direction it trades when it
fires):
  - a long's stop  = SELL below price -> fires into a fall -> down continuation
  - a short's stop = BUY  above price -> fires into a rise -> up continuation
  - a long's TP    = SELL above price -> fades a rally
  - a short's TP   = BUY  below price -> fades a selloff
Stops cascade (momentum); take-profits fade (mean reversion). We build signed
features and let the IC harness report the empirical sign.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from psycopg import sql

from .. import store

# Per-coin rolling window for the z-score normalisers: ~1 day of 15min bars.
Z_WINDOW = 96

_BUCKETS = ["sellstop_below", "buystop_above", "selltp_above", "buytp_below"]


def _fetch(
    select: sql.SQL, coins: list[str] | None, lookback_days: int
) -> pd.DataFrame:
    """Run a time-windowed SELECT and return the rows as a DataFrame (column
    names from the cursor description). Keeps us psycopg-only, parameterised."""
    query: sql.SQL | sql.Composed = select + sql.SQL(
        " WHERE time > now() - (%s * interval '1 day')"
    )
    params: list = [lookback_days]
    if coins:
        query += sql.SQL(" AND coin = ANY(%s)")
        params.append(list(coins))
    query += sql.SQL(" ORDER BY coin, time")
    with store.connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        cols = [c.name for c in cur.description or ()]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_assetctx(
    coins: list[str] | None = None, lookback_days: int = 30
) -> pd.DataFrame:
    """Price spine + open interest from ``assetctx`` over the lookback window."""
    return _fetch(
        sql.SQL(
            "SELECT time AS ts, coin, mark_px, open_interest, premium, funding "
            "FROM assetctx"
        ),
        coins,
        lookback_days,
    )


def load_triggers(
    coins: list[str] | None = None, lookback_days: int = 30
) -> pd.DataFrame:
    """Resting stop/TP orders from ``trigger_orders`` over the lookback window.

    One row per order per sweep snapshot. We aggregate notional, not identity,
    so addr/oid/limit_px are dropped.
    """
    return _fetch(
        sql.SQL(
            "SELECT time AS ts, coin, side, order_type, trigger_px, sz, "
            "reduce_only, is_position_tpsl FROM trigger_orders"
        ),
        coins,
        lookback_days,
    )


def resample_ctx(ctx: pd.DataFrame, freq: str = "15min") -> pd.DataFrame:
    """Per-coin price/OI bars at ``freq`` (the spine the features hang on)."""
    bars = []
    for coin, g in ctx.groupby("coin"):
        g = g.set_index("ts").sort_index()
        r = pd.DataFrame(
            {
                "mark_px": g["mark_px"].resample(freq).last(),
                "open_interest": g["open_interest"].resample(freq).last(),
                "premium": g["premium"].resample(freq).mean(),
                "funding": g["funding"].resample(freq).mean(),
            }
        )
        r["coin"] = coin
        bars.append(r)
    panel = pd.concat(bars).reset_index().rename(columns={"index": "ts"})
    return panel.sort_values(["coin", "ts"]).reset_index(drop=True)


def classify_triggers(triggers: pd.DataFrame) -> pd.DataFrame:
    """Tag each resting order as a stop or a take-profit and size its notional.

    Orders whose ``order_type`` is neither a stop nor a take-profit are dropped.
    """
    t = triggers.copy()
    order_type = t["order_type"].fillna("")
    kind = np.where(
        order_type.str.contains("Stop"),
        "stop",
        np.where(order_type.str.contains("Take Profit"), "tp", ""),
    )
    t["kind"] = kind
    t = t[t["kind"] != ""].copy()
    t["notional"] = t["sz"].astype(float) * t["trigger_px"].astype(float)
    return t[["ts", "coin", "side", "kind", "trigger_px", "notional"]]


def build_trigger_panel(
    ctx: pd.DataFrame,
    triggers: pd.DataFrame,
    freq: str = "15min",
    decay_bps: float = 50.0,
    max_bps: float = 300.0,
    max_snap_age: float = 2.0,
    z_window: int = Z_WINDOW,
) -> pd.DataFrame:
    """One row per (coin, bar) = price spine + proximity-weighted trigger features.

    For each bar we attach the most recent trigger snapshot at or before the bar
    (``merge_asof`` backward, per coin), drop snapshots older than
    ``max_snap_age`` bars, then weight each resting order by ``exp(-|dist|/decay)``
    (zeroed beyond ``max_bps``) and sum its notional into one of four buckets keyed
    on stop/tp x above/below the bar's mark. See module docstring for the signs.

    Args:
        ctx: Output of :func:`load_assetctx` (the price spine).
        triggers: Output of :func:`load_triggers` (resting orders per snapshot).
        freq: Bar size (pandas offset alias).
        decay_bps: Proximity decay scale in basis points.
        max_bps: Hard cutoff; orders farther than this contribute nothing.
        max_snap_age: Null a bar's features if its snapshot is older than this
            many bars (a stale sweep should not drive many bars).
        z_window: Rolling window (bars) for the per-coin z-score normalisers.

    Returns:
        Panel sorted by (coin, ts) with the four bucket notionals, the signed
        composites (``stop_imbalance``, ``tp_imbalance``, ``net_trigger_skew``),
        the unsigned ``trigger_density``, and the ``_oi`` / ``_z`` normalised
        variants. Bars with no usable snapshot have NaN features.
    """
    panel = resample_ctx(ctx, freq)
    trig = classify_triggers(triggers)

    if trig.empty:
        bars = panel.copy()
        bars["snap_ts"] = pd.NaT
    else:
        # As-of join the latest snapshot <= each bar, per coin.
        snap_times = trig[["coin", "ts"]].drop_duplicates().sort_values("ts")
        snap_times["snap_ts"] = snap_times["ts"]
        bars = pd.merge_asof(
            panel.sort_values("ts"),
            snap_times,
            on="ts",
            by="coin",
            direction="backward",
        )

    # Staleness guard: a snapshot older than max_snap_age bars is dropped.
    max_age = max_snap_age * pd.Timedelta(freq)
    stale = (bars["ts"] - bars["snap_ts"]) > max_age
    bars.loc[stale, "snap_ts"] = pd.NaT

    # Expand each bar against every resting order in its snapshot.
    if trig.empty:
        merged = bars.assign(
            side=np.nan, kind=np.nan, trigger_px=np.nan, notional=np.nan
        )
    else:
        trig2 = trig.rename(columns={"ts": "snap_ts"})
        merged = bars.merge(trig2, on=["coin", "snap_ts"], how="left")

    dist_bps = (merged["trigger_px"] / merged["mark_px"] - 1.0) * 1e4
    above = dist_bps > 0
    within = dist_bps.abs() <= max_bps
    w = np.where(within, np.exp(-dist_bps.abs() / decay_bps), 0.0)
    wn = merged["notional"].to_numpy() * w  # weighted notional per order

    is_stop = merged["kind"].to_numpy() == "stop"
    is_tp = merged["kind"].to_numpy() == "tp"
    sell = merged["side"].to_numpy() == "A"
    buy = merged["side"].to_numpy() == "B"
    above_a = above.to_numpy()

    merged["c_sellstop_below"] = np.where(is_stop & sell & ~above_a, wn, 0.0)
    merged["c_buystop_above"] = np.where(is_stop & buy & above_a, wn, 0.0)
    merged["c_selltp_above"] = np.where(is_tp & sell & above_a, wn, 0.0)
    merged["c_buytp_below"] = np.where(is_tp & buy & ~above_a, wn, 0.0)

    out = (
        merged.groupby(["coin", "ts"], sort=False)
        .agg(
            mark_px=("mark_px", "first"),
            open_interest=("open_interest", "first"),
            premium=("premium", "first"),
            funding=("funding", "first"),
            snap_ts=("snap_ts", "first"),
            sellstop_below=("c_sellstop_below", "sum"),
            buystop_above=("c_buystop_above", "sum"),
            selltp_above=("c_selltp_above", "sum"),
            buytp_below=("c_buytp_below", "sum"),
        )
        .reset_index()
    )

    # Bars with no usable snapshot: features are undefined, not zero.
    no_snap = out["snap_ts"].isna()
    out.loc[no_snap, _BUCKETS] = np.nan

    out["stop_imbalance"] = out["buystop_above"] - out["sellstop_below"]
    out["tp_imbalance"] = out["buytp_below"] - out["selltp_above"]
    total = out[_BUCKETS].sum(axis=1, min_count=1)
    oi = out["open_interest"].replace(0, np.nan)
    out["trigger_density"] = total / oi
    out["net_trigger_skew"] = (out["stop_imbalance"] + out["tp_imbalance"]) / (
        total + 1e-9
    )
    out["stop_imbalance_oi"] = out["stop_imbalance"] / oi
    out["tp_imbalance_oi"] = out["tp_imbalance"] / oi

    out = out.sort_values(["coin", "ts"]).reset_index(drop=True)

    def _z(s: pd.Series) -> pd.Series:
        m = s.rolling(z_window, min_periods=z_window // 2).mean()
        sd = s.rolling(z_window, min_periods=z_window // 2).std()
        return (s - m) / sd

    out["stop_imbalance_z"] = out.groupby("coin")["stop_imbalance"].transform(_z)
    out["tp_imbalance_z"] = out.groupby("coin")["tp_imbalance"].transform(_z)
    return out
