"""Predictiveness diagnostics: information coefficient + quantile-bucket spreads.

Caveat baked into the reporting: sampling an h-hour forward return every hour
creates overlapping windows, so naive p-values overstate significance. We report
both the full (overlapping) IC and a de-overlapped IC sampled every h hours.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def information_coefficient(df: pd.DataFrame, signal: str, ret_col: str, method: str = "spearman"):
    d = df[[signal, ret_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) < 30:
        return {"ic": np.nan, "p": np.nan, "n": len(d)}
    fn = stats.spearmanr if method == "spearman" else stats.pearsonr
    rho, p = fn(d[signal], d[ret_col])
    return {"ic": float(rho), "p": float(p), "n": int(len(d))}


def deoverlapped_ic(df: pd.DataFrame, signal: str, ret_col: str, horizon: int, method: str = "spearman"):
    """IC on non-overlapping samples (every `horizon` rows within each coin)."""
    keep = []
    for _, g in df.sort_values(["coin", "ts"]).groupby("coin"):
        keep.append(g.iloc[::horizon])
    sampled = pd.concat(keep) if keep else df
    return information_coefficient(sampled, signal, ret_col, method)


def quantile_table(df: pd.DataFrame, signal: str, ret_col: str, q: int = 5) -> pd.DataFrame:
    d = df[[signal, ret_col]].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(d) < q * 10:
        return pd.DataFrame()
    d["bucket"] = pd.qcut(d[signal].rank(method="first"), q, labels=False)
    g = d.groupby("bucket")[ret_col].agg(mean_ret="mean", median_ret="median", n="count")
    g["mean_ret_bps"] = g["mean_ret"] * 1e4
    return g


def ic_grid(df: pd.DataFrame, signals: list[str], horizons: list[int], method: str = "spearman") -> pd.DataFrame:
    """Pooled IC for every signal x horizon, plus the de-overlapped IC."""
    out = []
    for sig in signals:
        for h in horizons:
            ret = f"fwd_ret_{h}h"
            full = information_coefficient(df, sig, ret, method)
            deov = deoverlapped_ic(df, sig, ret, h, method)
            out.append(
                {
                    "signal": sig,
                    "horizon_h": h,
                    "ic": full["ic"],
                    "p_value": full["p"],
                    "n": full["n"],
                    "ic_deoverlap": deov["ic"],
                    "p_deoverlap": deov["p"],
                    "n_deoverlap": deov["n"],
                }
            )
    return pd.DataFrame(out)


def per_coin_ic(df: pd.DataFrame, signal: str, horizon: int, method: str = "spearman") -> pd.DataFrame:
    ret = f"fwd_ret_{horizon}h"
    rows = []
    for coin, g in df.groupby("coin"):
        r = information_coefficient(g, signal, ret, method)
        rows.append({"coin": coin, "ic": r["ic"], "p_value": r["p"], "n": r["n"]})
    return pd.DataFrame(rows).sort_values("ic").reset_index(drop=True)
