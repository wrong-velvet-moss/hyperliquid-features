-- TimescaleDB schema for hl-signals live market data.
-- Runs once on first container start (mounted into docker-entrypoint-initdb.d).
-- The loader (scripts/load_db.py) writes here; Grafana reads from it.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Per-coin asset-context snapshots (WS `activeAssetCtx`).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assetctx (
    time           TIMESTAMPTZ      NOT NULL,
    coin           TEXT             NOT NULL,
    mark_px        DOUBLE PRECISION,
    oracle_px      DOUBLE PRECISION,
    mid_px         DOUBLE PRECISION,
    premium        DOUBLE PRECISION,
    funding        DOUBLE PRECISION,
    open_interest  DOUBLE PRECISION,
    day_ntl_vlm    DOUBLE PRECISION
);
SELECT create_hypertable('assetctx', 'time', if_not_exists => TRUE);

-- Unique key enables idempotent re-loads (ON CONFLICT DO NOTHING).
-- TimescaleDB requires the partitioning column (time) in any unique index.
CREATE UNIQUE INDEX IF NOT EXISTS assetctx_time_coin_uniq ON assetctx (time, coin);
CREATE INDEX IF NOT EXISTS assetctx_coin_time_idx ON assetctx (coin, time DESC);

-- ---------------------------------------------------------------------------
-- Full trade tape (WS `trades`). side: 'B' aggressive buy, 'A' aggressive sell.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    time    TIMESTAMPTZ        NOT NULL,
    coin    TEXT               NOT NULL,
    side    TEXT,
    px      DOUBLE PRECISION,
    sz      DOUBLE PRECISION,
    tid     BIGINT,
    buyer   TEXT,
    seller  TEXT
);
SELECT create_hypertable('trades', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS trades_time_tid_uniq ON trades (time, tid);
CREATE INDEX IF NOT EXISTS trades_coin_time_idx ON trades (coin, time DESC);

-- ---------------------------------------------------------------------------
-- L2 order-book snapshots (WS `l2Book`). One row per price level per snapshot;
-- side is 'bid' / 'ask', lvl is the level index (0 = best). These are everyone's
-- resting limit orders, aggregated by price (n = number of orders at that price).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS book_levels (
    time    TIMESTAMPTZ        NOT NULL,
    coin    TEXT               NOT NULL,
    side    TEXT               NOT NULL,
    lvl     SMALLINT           NOT NULL,
    px      DOUBLE PRECISION,
    sz      DOUBLE PRECISION,
    n       INTEGER
);
SELECT create_hypertable('book_levels', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS book_levels_uniq ON book_levels (time, coin, side, lvl);
CREATE INDEX IF NOT EXISTS book_levels_coin_time_idx ON book_levels (coin, time DESC);
