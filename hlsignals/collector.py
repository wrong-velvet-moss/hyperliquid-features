"""Live collector for the free liquidation-proxy path.

Subscribes to the public WebSocket for the chosen coins and records:
  - trades     : full tape (coin, side, px, sz, tid, buyer, seller)
  - assetctx   : markPx/oraclePx/midPx/premium/funding/openInterest snapshots

Public trades carry NO liquidation flag (verified live), so we cannot label
liquidations directly. Instead we capture `openInterest` over time: a sharp OI
contraction concurrent with a price move is the footprint of a liquidation
cascade (see livepanel.add_liq_proxy). Data is flushed to rotating Parquet
part-files so a crash/restart never loses more than `flush_secs` of data.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pandas as pd
import websockets

WS_URL = "wss://api.hyperliquid.xyz/ws"


def _f(v) -> float:
    return float(v) if v is not None else float("nan")


class LiveCollector:
    def __init__(
        self,
        coins: list[str],
        outdir: str | Path,
        flush_secs: int = 60,
        book_secs: float = 5.0,
    ) -> None:
        self.coins = coins
        self.outdir = Path(outdir)
        (self.outdir / "trades").mkdir(parents=True, exist_ok=True)
        (self.outdir / "assetctx").mkdir(parents=True, exist_ok=True)
        (self.outdir / "book").mkdir(parents=True, exist_ok=True)
        self.flush_secs = flush_secs
        self.book_secs = (
            book_secs  # min seconds between persisted book snapshots per coin
        )
        self._trades: list[dict] = []
        self._ctx: list[dict] = []
        self._book: list[dict] = []
        self._book_last: dict[str, float] = {}  # coin -> last sampled ts (monotonic)
        self._last_flush = time.time()
        self.n_trades = 0
        self.n_ctx = 0
        self.n_book = 0

    async def run(self, minutes: float | None = None) -> None:
        deadline = None if minutes is None else time.time() + minutes * 60
        backoff = 1
        while deadline is None or time.time() < deadline:
            try:
                async with websockets.connect(
                    WS_URL, max_size=16_000_000, ping_interval=20
                ) as ws:
                    await self._subscribe(ws)
                    backoff = 1
                    while deadline is None or time.time() < deadline:
                        budget = (
                            5.0
                            if deadline is None
                            else max(0.5, min(5.0, deadline - time.time()))
                        )
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=budget)
                            self._handle(json.loads(raw))
                        except asyncio.TimeoutError:
                            pass
                        self._maybe_flush()
            except (websockets.ConnectionClosed, OSError) as exc:
                print(f"[reconnect in {backoff}s] {exc}", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        self._flush(force=True)

    async def _subscribe(self, ws) -> None:
        for c in self.coins:
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "subscription": {"type": "trades", "coin": c},
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "subscription": {"type": "activeAssetCtx", "coin": c},
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": c},
                    }
                )
            )

    def _handle(self, m: dict) -> None:
        ch = m.get("channel")
        if ch == "trades":
            for t in m["data"]:
                u = t.get("users", [None, None])
                self._trades.append(
                    {
                        "ts": int(t["time"]),
                        "coin": t["coin"],
                        "side": t["side"],  # "B"=aggressive buy, "A"=aggressive sell
                        "px": float(t["px"]),
                        "sz": float(t["sz"]),
                        "tid": t["tid"],
                        "buyer": u[0],
                        "seller": u[1],
                    }
                )
                self.n_trades += 1
        elif ch == "activeAssetCtx":
            d = m["data"]
            x = d["ctx"]
            self._ctx.append(
                {
                    "ts": int(
                        time.time() * 1000
                    ),  # ctx msg has no ts; stamp on receipt
                    "coin": d["coin"],
                    "markPx": _f(x.get("markPx")),
                    "oraclePx": _f(x.get("oraclePx")),
                    "midPx": _f(x.get("midPx")),
                    "premium": _f(x.get("premium")),
                    "funding": _f(x.get("funding")),
                    "openInterest": _f(x.get("openInterest")),
                    "dayNtlVlm": _f(x.get("dayNtlVlm")),
                }
            )
            self.n_ctx += 1
        elif ch == "l2Book":
            self._sample_book(m["data"])

    def _sample_book(self, d: dict) -> None:
        """Persist a top-of-book snapshot, throttled to one per coin per book_secs.

        The l2Book feed pushes on every change; we only keep a periodic snapshot
        so the depth heatmap stays a manageable size. ``levels`` is ``[bids, asks]``,
        each a list of ``{px, sz, n}`` from best to worst.
        """
        coin = d["coin"]
        now = time.time()
        if now - self._book_last.get(coin, 0.0) < self.book_secs:
            return
        self._book_last[coin] = now
        ts = int(d.get("time", now * 1000))
        for side, levels in zip(("bid", "ask"), d["levels"]):
            for lvl, level in enumerate(levels):
                self._book.append(
                    {
                        "ts": ts,
                        "coin": coin,
                        "side": side,
                        "lvl": lvl,
                        "px": float(level["px"]),
                        "sz": float(level["sz"]),
                        "n": int(level["n"]),
                    }
                )
                self.n_book += 1

    def _maybe_flush(self) -> None:
        if time.time() - self._last_flush >= self.flush_secs:
            self._flush()

    def _flush(self, force: bool = False) -> None:
        stamp = int(time.time())
        if self._trades:
            pd.DataFrame(self._trades).to_parquet(
                self.outdir / "trades" / f"{stamp}.parquet", index=False
            )
            self._trades = []
        if self._ctx:
            pd.DataFrame(self._ctx).to_parquet(
                self.outdir / "assetctx" / f"{stamp}.parquet", index=False
            )
            self._ctx = []
        if self._book:
            pd.DataFrame(self._book).to_parquet(
                self.outdir / "book" / f"{stamp}.parquet", index=False
            )
            self._book = []
        self._last_flush = time.time()
        print(
            f"[flush {stamp}] cumulative trades={self.n_trades} "
            f"ctx={self.n_ctx} book={self.n_book}",
            flush=True,
        )
