-- Resting trigger orders (stop-loss / take-profit) of other traders, polled
-- per-address from the public `frontendOpenOrders` endpoint by
-- scripts/poll_triggers.py. Each sweep is a snapshot stamped with one `time`.
--
-- This is REAL data: Hyperliquid is an on-chain CLOB, so other users' trigger
-- orders (with exact trigger prices) are publicly queryable per address.
--
-- Runs on first container start (docker-entrypoint-initdb.d, ordered after 01).

CREATE TABLE IF NOT EXISTS trigger_orders (
    time             TIMESTAMPTZ      NOT NULL,   -- sweep snapshot time
    addr             TEXT             NOT NULL,   -- trader 0x address
    coin             TEXT             NOT NULL,
    oid              BIGINT           NOT NULL,   -- order id
    side             TEXT,                        -- 'B' / 'A'
    order_type       TEXT,                        -- 'Stop Market', 'Take Profit Limit', ...
    trigger_px       DOUBLE PRECISION,
    limit_px         DOUBLE PRECISION,
    sz               DOUBLE PRECISION,
    reduce_only      BOOLEAN,
    is_position_tpsl BOOLEAN
);
SELECT create_hypertable('trigger_orders', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS trigger_orders_time_oid_uniq ON trigger_orders (time, oid);
CREATE INDEX IF NOT EXISTS trigger_orders_coin_time_idx ON trigger_orders (coin, time DESC);
