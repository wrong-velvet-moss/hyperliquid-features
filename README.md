# Hyperliquid Features

Collect public Hyperliquid market data and test whether the footprints of
**forced and mechanical exits** — liquidations, stop-losses, take-profits, and
the fair-value gap that drives them — are **predictive of forward returns**.

The data pipeline (REST + WebSocket → panel → information-coefficient harness) is
generic; the research question it serves is below.

## Motivation

Perpetual-futures venues like Hyperliquid are dominated by leveraged, retail-
heavy flow. A large share of the order activity is not informed price discovery
but the mechanical exits of traders who are managing risk rather than expressing
a view: margin calls (liquidations), profit targets (take-profits), and protective
stops (stop-losses).

Prior work in market microstructure and behavioural finance argues that this kind
of flow is, on average, **uninformed**:

- **Noise / uninformed traders** trade for non-informational reasons and lose to
  informed flow on average — Black, *Noise* (1986); Kyle, *Continuous Auctions
  and Insider Trading* (1985). Their order flow moves price *away* from
  fundamentals temporarily rather than toward them.
- **Retail traders underperform and overtrade** — Barber & Odean, *Trading Is
  Hazardous to Your Wealth* (2000).
- **The disposition effect** makes exit behaviour mechanical and predictable:
  traders sell winners too early and ride losers too long — Shefrin & Statman
  (1985); Odean, *Are Investors Reluctant to Realize Their Losses?* (1998). Stop
  and take-profit triggers are this behaviour encoded as resting orders.
- **Forced liquidations** are the extreme case: an over-leveraged, uninformed
  position closed *involuntarily* at the worst moment, injecting a burst of
  one-sided, price-insensitive flow.

### Hypothesis

> If liquidations, stops, and take-profits are predominantly the footprint of
> uninformed / over-leveraged traders, then the price dislocation they cause is
> **non-informational and should mean-revert**.

This yields a directly testable prediction on public data:

- A widening **premium** (perp mark above oracle) and bursts of **liquidation
  pressure** mark price being pushed away from fair value by forced/mechanical
  flow, and should be followed by **mean-reverting** forward returns (negative
  information coefficient).
- Clusters of resting **stop / take-profit** triggers mark the price levels where
  that flow will next be released, and so should carry information about where the
  next dislocation occurs.

The repo collects exactly the signals needed to test this — the fair-value gap, a
liquidation proxy, and real per-address trigger orders — and runs each through the
same information-coefficient (IC) harness against forward returns.

## What's publicly available on Hyperliquid

Verified against the live API, June 2026.

| Signal | Public? | Source |
| --- | --- | --- |
| **Fair value** — oracle px, mark px, mid, **premium**, **funding**, open interest | ✅ free | `metaAndAssetCtxs`, `fundingHistory`, `candleSnapshot` |
| **Stop-loss / take-profit orders** | ✅ public, *per address* | Hyperliquid is an on-chain CLOB, so other users' resting trigger orders are queryable: `frontendOpenOrders(user)` returns their stops/TPs with exact `triggerPx`. There is no global firehose, so a market-wide view is *reconstructed* by enumerating addresses (leaderboard + the trade tape) and polling each — see `hl-poll-triggers` (`src/hl_signals/cli/poll_triggers.py`). |
| **Liquidations** | ⚠️ no clean feed | The public `trades` stream carries no liquidation flag. The truth source is the S3 node archive (`node_fills_by_block`, requester-pays) where each fill keeps a `liquidation` object — not yet wired up. In the meantime we use a **free OI-contraction proxy** built from the live `assetctx` + `trades` feeds. |

> **Note on an earlier claim.** A previous version of this repo asserted stop/TP
> orders were *impossible* to obtain. That was wrong — they are public per address
> (a 150-address sweep returned real Stop Market / Take Profit orders with exact
> trigger prices). The **Stop / Take-Profit Orders (REAL)** dashboard shows them.
> A separate **Modeled Liquidation Heatmap** remains as a clearly-labelled
> *estimate* of the full-universe what-if, since true liquidations aren't in a
> public feed.

## The flows we're hunting

The signal we care about is not price discovery — it's the **mechanical exit
footprint** left by leveraged, retail-heavy flow. Three structural flows drive it,
each with a distinct shape on the tape:

- **Liquidations** are *involuntary* and *price-insensitive*. When margin breaches
  maintenance, the venue's liquidation engine closes the position with market
  orders regardless of where price is — a burst of one-sided flow that pushes mark
  away from oracle. The footprint is a sharp open-interest contraction coincident
  with a one-sided trade burst and a widening premium. Forced at the worst possible
  moment, they are the cleanest case of uninformed flow.
- **Stop-losses** are resting trigger orders that flip to market orders when price
  crosses a level. They **cluster** just beyond round numbers and recent swing
  highs/lows, and they **cascade**: one stop's market impact drags price into the
  next, so a cluster being hit reads as a self-reinforcing momentum burst. The
  level is knowable *before* the move.
- **Take-profits** are the mirror image — resting triggers that *fade* a move and
  supply mean-reverting liquidity into a trend. The disposition effect packs them
  closer to entry on the winning side, so they mark where a move is likely to
  stall.

### When the footprint should be legible

These are structural priors the pipeline is built to test, not results — but each
has a concrete reason to expect a visible signature:

- **Visibility.** Hyperliquid is an on-chain CLOB, so resting stop/TP triggers are
  queryable *per address* and liquidations leave an unambiguous OI-plus-trade
  signature. Unlike a centralized venue, a meaningful part of this flow is
  observable *ex ante* — the price levels where it will fire are sitting in the
  book — rather than only inferable after the fact.
- **Periodic seasonality.** Exits plausibly cluster on a clock: funding-settlement
  times, session opens and closes (Asia → EU → US), end-of-day risk trimming, and
  thin weekends. If forced/mechanical exits concentrate on a schedule, the
  dislocations they cause may be partly predictable in *time* as well as in price.
- **Volatility clustering.** Liquidations and stop cascades are self-exciting — a
  large move trips stops and liqs, which produce more move (Hawkes-like). So the
  forced-exit footprint should concentrate in high-volatility regimes and all but
  vanish in calm tape; conditioning a signal on the volatility regime should
  sharpen it rather than averaging it away.
- **Retail in low liquidity.** Leveraged retail flow is proportionally largest when
  professional liquidity steps away — overnight, weekends, holidays, and thinner
  alts. In those windows the uninformed footprint is a bigger share of volume, so
  the mechanical-exit dislocation should be larger and mean-revert more cleanly
  than the same flow would in a deep, well-arbitraged book.

The repo collects exactly the inputs these priors need — the fair-value gap, an
OI-contraction liquidation proxy, and real per-address trigger orders — so each can
be run through the same information-coefficient harness against forward returns as
the empirical legs are wired up (see [Roadmap](#roadmap)).

## Repository layout

A standard `src/` layout. The package is `hl_signals`; the runnable commands
are registered as console scripts in `pyproject.toml` (`[project.scripts]`) and
invoked with `uv run <command>`.

```
src/hl_signals/
  api.py            # rate-limit-aware Hyperliquid `info` REST client
  store.py          # TimescaleDB sink (idempotent COPY + ON CONFLICT DO NOTHING)
  ingest/           # getting market data in
    universe.py     # top-N perps by 24h volume + live fair-value snapshot
    collector.py    # live WS collector: trades + assetCtx + L2 book -> parquet and/or DB
    fairvalue.py    # hourly funding/premium + OHLCV panel
  research/         # testing predictiveness
    labels.py       # forward returns, funding z-score
    predictive.py   # information coefficient, de-overlapped IC, quantile buckets
    livepanel.py    # assemble collected live parquet into a bar panel + OI liq proxy
    liquidations.py # S3 node-archive liquidations (true-label path; NotImplemented stub)
  cli/              # console entry points (one main() each)
    fetch_fairvalue.py    # hl-fetch-fairvalue    pull data -> data/fairvalue_panel.parquet
    spike_fairvalue.py    # hl-spike-fairvalue    predictiveness test -> reports/fairvalue_spike.md
    collect.py            # hl-collect            run the live collector (parquet / db / both)
    spike_liquidations.py # hl-spike-liquidations IC harness on the OI-based liquidation proxy
    load_db.py            # hl-load-db            upsert collected live parquet into TimescaleDB
    load_meta.py          # hl-load-meta          per-coin max leverage -> coin_meta (modeled heatmap)
    poll_triggers.py      # hl-poll-triggers      sweep real stop/TP orders per address -> trigger_orders
db/init/          # TimescaleDB schema + retention (auto-applied on first start)
grafana/          # provisioned datasource + dashboards (auto-loaded)
docker-compose.yml # Grafana + TimescaleDB monitoring stack
Makefile          # common tasks: `make help`
```

## Quickstart — the research path

This is a [uv](https://docs.astral.sh/uv/) project: `uv` reads `pyproject.toml`,
creates the virtualenv, and installs dependencies on first `uv run`. No Docker
needed for the core test.

```bash
uv run hl-fetch-fairvalue --n 20 --days 120   # ~1 min, free public API
uv run hl-spike-fairvalue                      # prints IC table + writes report
```

`hl-fetch-fairvalue` pulls the top-N perps by 24h volume into
`data/fairvalue_panel.parquet`; `hl-spike-fairvalue` runs the IC harness and writes
`reports/fairvalue_spike.md`. (Both commands resolve `data/`/`reports/` relative to
the current directory, so run them from the repo root.)

## Live monitoring stack — Grafana + TimescaleDB

Collected market data is surfaced in Grafana, backed by a TimescaleDB (Postgres)
hypertable store. Everything is provisioned from this repo (requires Docker +
Docker Compose):

```bash
make up        # start Grafana + TimescaleDB (creates .env from .env.example)
make ps        # check status
make logs      # tail logs
make down      # stop (volumes persist)
```

- **Grafana** → http://localhost:3000 (default `admin` / `admin`, change in `.env`)
- **TimescaleDB** → `localhost:5432`, db `hlsignals` (`make psql` for a shell)

On first start, `db/init/` creates the `assetctx`, `trades`, `book_levels`, and
`trigger_orders` hypertables plus the `coin_meta` reference table, and Grafana
auto-provisions the datasource. Override ports/credentials in `.env`.

### Getting data into the dashboards

Two ways: collect-then-load, or stream live.

```bash
# batch: collect for a while, then load
make collect   # live WS collector -> data/live/*.parquet
make load      # upsert collected parquet into TimescaleDB (idempotent)

# live: stream straight into the DB (Grafana auto-refreshes)
make live            # collector writes trades/book/assetctx directly to the DB
make triggers-loop   # re-sweep real stop/TP orders every 15 min (background)
make retention       # rolling buffer: trades/book 7d, assetctx/triggers 30d
```

`make load` (`hl-load-db`) maps the collector's part-files onto the schema
and upserts with `ON CONFLICT DO NOTHING`, so re-running it is safe. The WS market
data is truly live (sub-minute); stop/TP orders have no firehose, so
`triggers-loop` refreshes them on a rate-limited sweep. `make retention` keeps the
DB from growing forever — adjust the windows in `db/init/04_retention.sql`.

To feed the trigger / heatmap dashboards: `make triggers` (real per-address stop/TP
orders) and `make meta` (per-coin leverage caps for the modeled heatmap).

### Dashboards

Grafana auto-provisions five dashboards into the `hl-signals` folder. **Real** =
actual public data; **modeled** = a clearly-labelled estimate.

| Dashboard | Shows | Source |
| --- | --- | --- |
| **Live Market Monitor** | Per-coin mark, OI, premium, funding, cumulative volume delta, OI-contraction liq proxy | `assetctx` + `trades` — ✅ real |
| **Order Book Depth** | Resting-depth heatmap (size by bps from mid), bid/ask depth, spread, largest walls | `book_levels` (L2) — ✅ real |
| **Order Flow & Forced Exits** | Whale tape, large-trade net notional, signed liq-pressure, biggest OI-drop events | `trades` + `assetctx` — ✅ real |
| **Stop / Take-Profit Orders (REAL)** | Other traders' resting stop-loss / take-profit triggers by price + a clusters table | `trigger_orders` — ✅ real |
| **Modeled Liquidation Heatmap** | Estimated liq clusters by bps from price + per-leverage-tier liq levels | `assetctx` + `coin_meta` — ⚠️ **modeled, not real orders** |

Resting limit orders, executed trades, and stop/TP triggers are all genuinely
public on Hyperliquid (it's an on-chain CLOB) — the first four dashboards are real.
The Modeled Liquidation Heatmap is the what-if projection other sites present as a
"liq heatmap" for the full user base, labelled as such. Edits to any dashboard JSON
are picked up live, so you can tweak panels in the UI and copy the model back.

## Reading the predictiveness results

`hl-spike-fairvalue` reports the **information coefficient** (Spearman rank
correlation between each signal and the forward return) for funding / premium /
funding-z over 1/4/8/24h, plus quintile-bucket forward returns and a per-coin
breakdown.

Because an h-hour return sampled hourly overlaps, **trust the `ic_deoverlap`
p-values over the naive ones**. |IC| around 0.02–0.05 with a consistent sign and a
monotone bucket spread is a real (if small) edge at this frequency; near-zero or
sign-flipping across coins is noise. A **negative** IC means the signal is followed
by mean reversion — the direction the uninformed-flow hypothesis predicts.

## Development

Commit guardrails run via [pre-commit](https://pre-commit.com): a large-file guard
(>1 MB), private-key detection, and `ruff` lint + format. Enable once per clone:

```bash
make hooks       # uv run pre-commit install
make precommit   # run all hooks across the repo on demand
```

After that, `git commit` auto-formats staged Python and rejects oversized or
secret-bearing files before they enter history.

## Roadmap

1. **True liquidations (the headline test):** implement
   `hourly_liquidations_from_s3` (parse `node_fills_by_block`), then run the *same*
   IC harness — does a liquidation spike precede reversal or continuation? This is
   the cleanest test of the uninformed-flow hypothesis.
2. **Trigger clusters as a signal:** test whether dense stop/TP clusters from
   `trigger_orders` predict the location and direction of the next move.
3. **Combine signals:** premium + liquidation pressure + trigger proximity in a
   single ranked, de-overlapped model.
4. **Promote to higher frequency** only where a signal looks real and sub-hour data
   beats the REST history.
