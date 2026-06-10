"""Poll real stop-loss / take-profit (trigger) orders into ``trigger_orders``.

Hyperliquid is an on-chain CLOB, so other traders' trigger orders are public —
queryable per address via ``frontendOpenOrders``. There is no global firehose,
so we enumerate addresses and poll each, keeping the ``isTrigger`` rows. Each run
is a snapshot stamped with one time.

Address sources (``--source``):
  - ``leaderboard`` (default): the public leaderboard (~38k traders), biggest
    account values first — the most positions, so the most stops/TPs.
  - ``trades``: distinct addresses seen in our collected trade tape.
  - ``both``: leaderboard then trades, de-duplicated.

    make triggers                              # leaderboard sweep -> trigger_orders
    uv run hl-poll-triggers --max-addrs 2000 --source both
"""

from __future__ import annotations

import argparse
import time

import pandas as pd
import psycopg
import requests

from .. import store
from ..api import HyperliquidInfo

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


def _leaderboard_addresses(limit: int, timeout: float = 60.0) -> list[str]:
    """Top trader addresses from the public leaderboard, by account value desc."""
    resp = requests.get(LEADERBOARD_URL, timeout=timeout)
    resp.raise_for_status()
    rows = resp.json().get("leaderboardRows", [])

    def _account_value(row: dict) -> float:
        value = row.get("accountValue")
        try:
            return float(value) if value is not None else 0.0
        except ValueError:
            return 0.0

    rows.sort(key=_account_value, reverse=True)
    return [row["ethAddress"] for row in rows[:limit] if row.get("ethAddress")]


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


def _dedupe(addrs: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    uniq: list[str] = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq[:limit]


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


def _gather_addresses(source: str, max_addrs: int, since_hours: float) -> list[str]:
    addrs: list[str] = []
    if source in ("leaderboard", "both"):
        lb = _leaderboard_addresses(max_addrs)
        print(f"  {len(lb)} addresses from leaderboard", flush=True)
        addrs.extend(lb)
    if source in ("trades", "both"):
        with store.connect() as conn:
            tr = _recent_addresses(conn, max_addrs, since_hours)
        print(f"  {len(tr)} addresses from trades", flush=True)
        addrs.extend(tr)
    return _dedupe(addrs, max_addrs)


def _sweep(
    api: HyperliquidInfo, source: str, max_addrs: int, since_hours: float
) -> None:
    """Run one full sweep: gather addresses, poll each, upsert the triggers."""
    snapshot = pd.Timestamp.now(tz="UTC")
    print(f"gathering addresses ({source})...", flush=True)
    addrs = _gather_addresses(source, max_addrs, since_hours)
    if not addrs:
        print("no addresses found; try --source leaderboard, or collect trades first")
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
        if i % 100 == 0:
            print(f"  {i}/{len(addrs)} polled, {len(rows)} triggers so far", flush=True)

    with store.connect() as conn:
        n = store.upsert_triggers(conn, pd.DataFrame(rows)) if rows else 0

    print(
        f"sweep {snapshot.isoformat()}: {n} trigger orders "
        f"from {n_with}/{len(addrs)} addresses"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-addrs", type=int, default=1000, help="max addresses to poll this sweep"
    )
    parser.add_argument(
        "--source",
        choices=["leaderboard", "trades", "both"],
        default="leaderboard",
        help="where to source addresses (default: leaderboard)",
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=72.0,
        help="for --source trades/both: only addresses seen trading within N hours",
    )
    parser.add_argument(
        "--loop",
        type=float,
        default=0.0,
        help="repeat every N seconds (0 = one sweep then exit)",
    )
    args = parser.parse_args()

    api = HyperliquidInfo()
    while True:
        _sweep(api, args.source, args.max_addrs, args.since_hours)
        if args.loop <= 0:
            break
        print(f"next sweep in {args.loop:.0f}s...", flush=True)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
