"""Select the perp universe to study (top-N by 24h notional volume)."""

from __future__ import annotations

import pandas as pd

from .api import HyperliquidInfo


def perp_contexts(client: HyperliquidInfo | None = None) -> pd.DataFrame:
    """Snapshot of every active perp with its live fair-value figures."""
    client = client or HyperliquidInfo()
    meta, ctxs = client.meta_and_asset_ctxs()
    rows = []
    for u, c in zip(meta["universe"], ctxs):
        if u.get("isDelisted"):
            continue
        rows.append(
            {
                "coin": u["name"],
                "dayNtlVlm": float(c.get("dayNtlVlm") or 0.0),
                "openInterest": float(c.get("openInterest") or 0.0),
                "oraclePx": float(c.get("oraclePx") or 0.0),
                "markPx": float(c.get("markPx") or 0.0),
                "midPx": float(c.get("midPx") or 0.0)
                if c.get("midPx")
                else float("nan"),
                "premium": float(c["premium"])
                if c.get("premium") is not None
                else float("nan"),
                "funding": float(c.get("funding") or 0.0),
            }
        )
    df = (
        pd.DataFrame(rows)
        .sort_values("dayNtlVlm", ascending=False)
        .reset_index(drop=True)
    )
    return df


def top_perps_by_volume(
    n: int = 20, client: HyperliquidInfo | None = None
) -> list[str]:
    return perp_contexts(client)["coin"].head(n).tolist()
