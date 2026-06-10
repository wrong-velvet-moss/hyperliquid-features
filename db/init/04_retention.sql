-- TimescaleDB retention: keep the store a rolling live buffer instead of an
-- ever-growing archive. Old chunks are dropped automatically by a background
-- job. Adjust the intervals (or `make psql` + remove_retention_policy) to taste.
--
-- Runs on first container start; re-apply to a running DB with `make retention`.

-- High-volume tick data: keep ~7 days.
SELECT add_retention_policy('trades', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('book_levels', INTERVAL '7 days', if_not_exists => TRUE);

-- Lower-volume series / snapshots: keep ~30 days.
SELECT add_retention_policy('assetctx', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('trigger_orders', INTERVAL '30 days', if_not_exists => TRUE);
