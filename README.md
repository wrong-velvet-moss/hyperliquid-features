# hl-signals

Collect Hyperliquid market data and test whether it's **predictive of forward returns**.

Original goal: liquidations + order flow + stop/TP + a fair-value figure. The
research below changed the plan once we confirmed what's actually obtainable.

## What's publicly available (verified against the live API, June 2026)

| Signal | Public? | Source |
| --- | --- | --- |
| **Fair value** (oracle px, mark px, mid, **premium**, **funding**, OI) | ✅ free | `metaAndAssetCtxs`, `fundingHistory`, `candleSnapshot` |
| **Liquidations** | ⚠️ no clean feed | No flag in the public `trades` stream. Historical = parse S3 `node_fills_by_block` (requester-pays) where each fill keeps a `liquidation` object; or 3rd parties (CoinGlass/Coinalyze/Allium). Live = collect `trades` WS yourself. |
| **Stop-loss / take-profit orders** | ❌ impossible | Other users' trigger orders are never public — invisible until they fire. Any "stop/TP heatmap" elsewhere is *modeled*, not real data. |

**Design consequence:** stop/TP is dropped (substitute liquidations + open
interest as the forced-flow / positioning proxy). We lead with the **fair-value
spike** because it's free and pullable in minutes; liquidations are step 2 and
need paid S3 access (see `hlsignals/liquidations.py`).

## Layout

```
hlsignals/
  api.py          # rate-limit-aware Hyperliquid `info` REST client
  universe.py     # top-N perps by 24h volume + live fair-value snapshot
  fairvalue.py    # hourly funding/premium + OHLCV panel
  labels.py       # forward returns, funding z-score
  predictive.py   # information coefficient, de-overlapped IC, quantile buckets
  liquidations.py # STEP 2 stub: market-wide liquidations from S3 node archive
  collector.py    # live WS collector: trades + assetCtx -> data/live/*.parquet
  livepanel.py    # assemble collected live parquet into a bar panel
scripts/
  fetch_fairvalue.py     # pull data -> data/fairvalue_panel.parquet
  spike_fairvalue.py     # run the predictiveness test -> reports/fairvalue_spike.md
  collect_live.py        # run the live collector (free liquidation-proxy path)
  spike_liquidations.py  # IC harness on the collected OI-based liquidation proxy
db/init/          # TimescaleDB schema (auto-applied on first container start)
grafana/          # provisioned datasource + dashboards (auto-loaded by Grafana)
docker-compose.yml # Grafana + TimescaleDB monitoring stack
Makefile          # common tasks: `make help`
```

## Live monitoring stack (Grafana + TimescaleDB)

Collected market data is surfaced in Grafana, backed by a TimescaleDB
(Postgres) hypertable store. Everything is provisioned from this repo — bring it
up with one command (requires Docker + Docker Compose):

```bash
make up        # start Grafana + TimescaleDB (creates .env from .env.example)
make ps        # check status
make logs      # tail logs
make down      # stop (volumes persist)
```

- **Grafana** → http://localhost:3000 (default `admin` / `admin`, change in `.env`)
- **TimescaleDB** → `localhost:5432`, db `hlsignals` (open a shell with `make psql`)

On first start the DB schema (`db/init/`) creates `assetctx` and `trades`
hypertables, and Grafana auto-provisions the TimescaleDB datasource. Override
ports/credentials by copying `.env.example` → `.env`.

### Getting data into the dashboard

```bash
make collect   # run the live WS collector for a while -> data/live/*.parquet
make load      # upsert collected parquet into TimescaleDB (idempotent)
```

`make load` (`scripts/load_db.py`) maps the collector's part-files onto the
hypertable schema and upserts with `ON CONFLICT DO NOTHING`, so re-running it is
safe — only new rows are inserted. Run it on a loop, or after each collection
session, to keep Grafana fed.

## Quickstart

This is a [uv](https://docs.astral.sh/uv/) project — `uv` reads `pyproject.toml`,
creates the virtualenv, and installs dependencies on first `uv run`.

```bash
uv run scripts/fetch_fairvalue.py --n 20 --days 120   # ~1 min, free public API
uv run scripts/spike_fairvalue.py                     # prints IC table + writes report
```

## Reading the result

`spike_fairvalue.py` reports the **information coefficient** (Spearman rank
correlation between each signal and the forward return) for funding / premium /
funding-z over 1/4/8/24h, plus quintile-bucket forward returns and a per-coin
breakdown. Because an h-hour return sampled hourly overlaps, trust the
`ic_deoverlap` p-values over the naive ones. |IC| around 0.02–0.05 with a
consistent sign and a monotone bucket spread is a real (if small) edge at this
frequency; near-zero / sign-flipping across coins is noise.

## Next steps

1. **Liquidations (step 2):** implement `hourly_liquidations_from_s3` and rerun
   the *same* harness — does a liquidation spike precede reversal or continuation?
2. **Combine signals:** funding_z + premium + liq_notional in a single ranked model.
3. **Promote to a collector** only if a signal looks real and you need fresher /
   higher-frequency (sub-hour) data than the REST history provides.
