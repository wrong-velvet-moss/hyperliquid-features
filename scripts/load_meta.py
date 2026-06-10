"""Fetch Hyperliquid perp metadata (max leverage per coin) into ``coin_meta``.

The MODELED liquidation heatmap uses ``max_leverage`` to cap its leverage tiers
per coin. Run occasionally (leverage tiers change rarely):

    make meta
"""

from __future__ import annotations

from hlsignals import store
from hlsignals.api import HyperliquidInfo

_UPSERT = (
    "INSERT INTO coin_meta (coin, max_leverage, sz_decimals) VALUES (%s, %s, %s) "
    "ON CONFLICT (coin) DO UPDATE SET "
    "max_leverage = EXCLUDED.max_leverage, "
    "sz_decimals = EXCLUDED.sz_decimals, "
    "updated_at = now()"
)


def main() -> None:
    api = HyperliquidInfo()
    meta, _ = api.meta_and_asset_ctxs()
    rows = [
        (c["name"], int(c["maxLeverage"]), int(c["szDecimals"]))
        for c in meta["universe"]
    ]
    with store.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT, rows)
        conn.commit()
    print(f"loaded coin_meta for {len(rows)} coins")


if __name__ == "__main__":
    main()
