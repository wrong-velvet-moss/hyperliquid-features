# hl-signals

Collect Hyperliquid market data and test whether it's **predictive of forward returns**.

Original goal: liquidations + order flow + stop/TP + a fair-value figure. The
research below changed the plan once we confirmed what's actually obtainable.

## Motivation

The idea came from watching the **order book**: deep resting levels kept showing
up clustered around **liquidation prices near the mid**, not spread randomly
through the book. That's the footprint **uninformed flow** leaves — retail
traders who manage risk almost entirely with **stop-loss and take-profit**
orders, parked at round numbers and obvious liquidation levels.

If that positioning is this concentrated and predictable, there may be **alpha**
in it. Informed traders rarely telegraph their exits this way, so the resting
stop/TP book reads as a **proxy for where forced selling/buying will hit**. And
because the same uninformed positioning exists on every venue, it's a window
into **cross-exchange liquidation flow** — not just Hyperliquid's own book.

This study tests that hypothesis: collect the real, per-address **stop/TP
triggers** (genuinely public on an on-chain CLOB — see below), map where they
cluster relative to price, and check whether those clusters are **predictive of
forward returns**.

## What's publicly available (verified against the live API, June 2026)

| Signal | Public? | Source |
| --- | --- | --- |
| **Fair value** (oracle px, mark px, mid, **premium**, **funding**, OI) | ✅ free | `metaAndAssetCtxs`, `fundingHistory`, `candleSnapshot` |
| **Liquidations** | ⚠️ no clean feed | No flag in the public `trades` stream. Historical = parse S3 `node_fills_by_block` (requester-pays) where each fill keeps a `liquidation` object; or 3rd parties (CoinGlass/Coinalyze/Allium). Live = collect `trades` WS yourself. |
| **Stop-loss / take-profit orders** | ✅ public, per address | Hyperliquid is an on-chain CLOB, so other users' trigger orders **are** queryable: `frontendOpenOrders(user)` returns their resting stops/TPs with exact `triggerPx`. There's no global firehose, so a market-wide view is *reconstructed* by enumerating addresses (from the trade tape) and polling each — see `scripts/poll_triggers.py`. The S3 node archive is the exhaustive source. |

**Correction:** an earlier version of this repo claimed stop/TP orders were
*impossible* to obtain. That was wrong — they're public per address (verified
live: a 150-address sweep returned real Stop Market / Take Profit orders with
exact trigger prices). The **Stop / Take-Profit Orders (REAL)** dashboard shows
them; the **Modeled Liquidation Heatmap** remains as a separate *estimate* for
the full-universe what-if. We still lead with the **fair-value spike** because
it's free and pullable in minutes.

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

On first start the DB schema (`db/init/`) creates the `assetctx`, `trades`, and
`book_levels` hypertables, and Grafana auto-provisions the TimescaleDB
datasource. Override ports/credentials by copying `.env.example` → `.env`.

The collector also samples the **L2 order book** (`l2Book`, top 20 levels per
side, one snapshot per coin every `book_secs`) into `book_levels` — everyone's
resting limit orders aggregated by price. Stop-loss / take-profit trigger orders
are also public (per address) and collected separately via `make triggers` — see
the table above and `scripts/poll_triggers.py`.

### Getting data into the dashboard

```bash
make collect   # run the live WS collector for a while -> data/live/*.parquet
make load      # upsert collected parquet into TimescaleDB (idempotent)
```

`make load` (`scripts/load_db.py`) maps the collector's part-files onto the
hypertable schema and upserts with `ON CONFLICT DO NOTHING`, so re-running it is
safe — only new rows are inserted. Run it on a loop, or after each collection
session, to keep Grafana fed.

#### Live mode (hands-off)

To skip the manual `collect` → `load` cycle, stream straight into TimescaleDB —
Grafana auto-refreshes, so the market dashboards update on their own:

```bash
make live            # collector writes trades/book/assetctx directly to the DB
make triggers-loop   # re-sweep stop/TP orders every 15 min (background)
make retention       # rolling buffer: drop old chunks (trades/book 7d, rest 30d)
```

The WS market data is truly live (sub-minute). Stop/TP orders have no firehose,
so `triggers-loop` refreshes them periodically (a full sweep is rate-limited).
`make retention` keeps the DB from growing forever — adjust the windows in
`db/init/04_retention.sql`.

### Dashboards

Grafana auto-provisions five dashboards into the `hl-signals` folder
(`grafana/dashboards/*.json`). **Real** = actual public data; **modeled** = an
estimate, clearly labelled.

| Dashboard | Shows | Source |
| --- | --- | --- |
| **Live Market Monitor** | Per-coin mark, OI, premium, funding, cumulative volume delta, OI-contraction liq proxy | `assetctx` + `trades` — ✅ real |
| **Order Book Depth** | Resting-depth heatmap (size by bps from mid), bid vs ask depth, spread, largest walls | `book_levels` (L2) — ✅ real, *everyone's resting orders* |
| **Order Flow & Forced Exits** | Whale tape (large executed trades over a notional threshold), large-trade net notional, signed liq-pressure, biggest OI-drop events | `trades` + `assetctx` — ✅ real |
| **Stop / Take-Profit Orders (REAL)** | Other traders' resting stop-loss / take-profit triggers by price + a clusters table | `trigger_orders` — ✅ real, *actual stop/TP orders* |
| **Modeled Liquidation Heatmap** | Estimated liq clusters by bps from price + per-leverage-tier liq levels | `assetctx` + `coin_meta` — ⚠️ **modeled, not real orders** |

Other traders' resting limit orders, executed trades, **and stop/TP triggers**
are all genuinely public on Hyperliquid (it's an on-chain CLOB) — the first four
dashboards are real. The Modeled Liquidation Heatmap is the estimate other sites
present as a "liq/stop heatmap" for the full user base — a what-if projection,
labelled as such.

Feed the real stop/TP view with `make triggers` (polls per-address trigger
orders); the modeled heatmap needs per-coin leverage caps via `make meta`. Both
read addresses/coins accumulated by `make collect` + `make load`.

Edits to any dashboard JSON are picked up live (the provider watches the folder),
so you can tweak panels in the Grafana UI and copy the model back into the repo.

## Quickstart

This is a [uv](https://docs.astral.sh/uv/) project — `uv` reads `pyproject.toml`,
creates the virtualenv, and installs dependencies on first `uv run`.

```bash
uv run scripts/fetch_fairvalue.py --n 20 --days 120   # ~1 min, free public API
uv run scripts/spike_fairvalue.py                     # prints IC table + writes report
```

## Development

Commit guardrails run via [pre-commit](https://pre-commit.com) so each commit
lands small and clean — a large-file guard (>1 MB), private-key detection, and
`ruff` lint + format. Enable once per clone:

```bash
make hooks                 # uv run pre-commit install
make precommit             # run all hooks across the repo on demand
```

After that, `git commit` auto-formats staged Python and rejects oversized or
secret-bearing files before they ever enter history.

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
