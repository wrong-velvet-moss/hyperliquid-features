"""Poll real stop-loss / take-profit (trigger) orders into ``trigger_orders``.

Hyperliquid is an on-chain CLOB, so other traders' trigger orders are public —
queryable per address via ``frontendOpenOrders``. There is no global firehose,
so we enumerate addresses (from the trades we already collect) and poll each,
keeping the ``isTrigger`` rows. Each run is a snapshot stamped with one time.

    make up && make collect && make load   # accumulate the address universe
    make triggers                          # sweep -> trigger_orders
"""

from __future__ import annotations

import argparse

import pandas as pd
import psycopg

from hlsignals import store
from hlsignals.api import HyperliquidInfo


def _recent_addresses(
    conn: psycopg.Connection, limit: int, since_hours: float
) -> list[str]:
    """Distinct trader addresses seen in trades within the lookback window."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT addr FROM ("
            "  SELECT buyer AS addr, max(time) AS t FROM trades "
            "  WHERE buyer IS NOT NULL AND time > now() - (%s * interval '1 hour') GROUP BY buyer"
            "  UNION ALL"
            "  SELECT seller AS addr, max(time) AS t FROM trades "
            "  WHERE seller IS NOT NULL AND time > now() - (%s * interval '1 hour') GROUP BY seller"
            ") s GROUP BY addr ORDER BY max(t) DESC LIMIT %s",
            (since_hours, since_hours, limit),
        )
        return [r[0] for r in cur.fetchall()]


def _trigger_rows(addr: str, orders: list[dict], snapshot: pd.Timestamp) -> list[dict]:
    rows = []
    for o in orders:
        if not o.get("isTrigger"):
            continue
        rows.append(
            {
                "time": snapshot,
                "addr": addr,
                "coin": o["coin"],
                "oid": int(o["oid"]),
                "side": o.get("side"),
                "order_type": o.get("orderType"),
                "trigger_px": float(o["triggerPx"]) if o.get("triggerPx") else None,
                "limit_px": float(o["limitPx"]) if o.get("limitPx") else None,
                "sz": float(o["sz"]) if o.get("sz") is not None else None,
                "reduce_only": bool(o.get("reduceOnly")),
                "is_position_tpsl": bool(o.get("isPositionTpsl")),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-addrs", type=int, default=400, help="max addresses to poll this sweep"
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=72.0,
        help="only addresses seen trading within this many hours",
    )
    args = parser.parse_args()

    api = HyperliquidInfo()
    snapshot = pd.Timestamp.now(tz="UTC")

    with store.connect() as conn:
        addrs = _recent_addresses(conn, args.max_addrs, args.since_hours)
        if not addrs:
            print(
                "no recent addresses in trades; run `make collect && make load` first"
            )
            return
        print(f"polling {len(addrs)} addresses for trigger orders...", flush=True)

        rows: list[dict] = []
        n_with = 0
        for i, addr in enumerate(addrs, 1):
            try:
                orders = api.frontend_open_orders(addr)
            except RuntimeError as exc:
                print(f"  [{addr[:10]}…] skipped: {exc}", flush=True)
                continue
            trig = _trigger_rows(addr, orders, snapshot)
            if trig:
                n_with += 1
                rows.extend(trig)
            if i % 50 == 0:
                print(
                    f"  {i}/{len(addrs)} polled, {len(rows)} triggers so far",
                    flush=True,
                )

        n = store.upsert_triggers(conn, pd.DataFrame(rows)) if rows else 0

    print(
        f"sweep {snapshot.isoformat()}: {n} trigger orders from {n_with}/{len(addrs)} addresses"
    )


if __name__ == "__main__":
    main()
