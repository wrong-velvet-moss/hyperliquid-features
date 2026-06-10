"""Thin, rate-limit-aware client for the Hyperliquid `info` REST endpoint.

All public market data is served from a single POST endpoint that dispatches on
a `type` field. Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint

Rate limits (IP-based): 1200 weight/min aggregate. The light endpoints we use
cost 2-20 weight each, so a small client-side throttle keeps us well under.
"""

from __future__ import annotations

import time
from typing import Any

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidInfo:
    def __init__(
        self,
        url: str = INFO_URL,
        min_interval: float = 0.12,  # ~8 req/s; comfortably under the weight budget
        timeout: float = 20.0,
        max_retries: int = 4,
    ) -> None:
        self.url = url
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._last = 0.0

    def _post(self, payload: dict[str, Any]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self._session.post(self.url, json=payload, timeout=self.timeout)
                self._last = time.time()
                if r.status_code == 429:  # rate limited -> exponential backoff
                    time.sleep(2**attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(
            f"Hyperliquid request failed after {self.max_retries} tries: {last_exc}"
        )

    # --- endpoints -----------------------------------------------------------

    def meta_and_asset_ctxs(self) -> list[Any]:
        """[meta, ctxs]. meta.universe lists perps; ctxs is the parallel array of
        live contexts (markPx, oraclePx, midPx, premium, funding, openInterest, dayNtlVlm)."""
        return self._post({"type": "metaAndAssetCtxs"})

    def funding_history(
        self, coin: str, start_ms: int, end_ms: int | None = None
    ) -> list[dict]:
        """Hourly {coin, fundingRate, premium, time}. Paginated by time (~500/call)."""
        payload: dict[str, Any] = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": int(start_ms),
        }
        if end_ms is not None:
            payload["endTime"] = int(end_ms)
        return self._post(payload)

    def frontend_open_orders(self, user: str) -> list[dict]:
        """All of ``user``'s resting orders, including trigger (stop/TP) orders.

        Public per-address endpoint. Each order carries ``isTrigger``,
        ``triggerPx``, ``orderType`` (e.g. "Stop Market", "Take Profit Limit"),
        ``reduceOnly`` and ``isPositionTpsl`` — i.e. other traders' stop-loss and
        take-profit levels are visible here.

        Args:
            user: The 0x address to query.

        Returns:
            A list of open-order dicts (empty if the address has none).
        """
        return self._post({"type": "frontendOpenOrders", "user": user})

    def candle_snapshot(
        self, coin: str, interval: str, start_ms: int, end_ms: int
    ) -> list[dict]:
        """OHLCV candles {t,T,s,i,o,c,h,l,v,n}. Max 5000 most-recent candles."""
        return self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": int(start_ms),
                    "endTime": int(end_ms),
                },
            }
        )
