-- Per-coin perp metadata (from `metaAndAssetCtxs`). Small reference/dim table
-- (not a hypertable), populated by scripts/load_meta.py. Used by the MODELED
-- liquidation heatmap to cap leverage tiers at each coin's real max leverage.
--
-- Runs on first container start (docker-entrypoint-initdb.d, ordered after 01).

CREATE TABLE IF NOT EXISTS coin_meta (
    coin         TEXT         PRIMARY KEY,
    max_leverage INTEGER,
    sz_decimals  INTEGER,
    updated_at   TIMESTAMPTZ  DEFAULT now()
);
