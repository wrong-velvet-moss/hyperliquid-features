"""TimescaleDB sink for collected market data.

Thin psycopg layer: stage a DataFrame via ``COPY`` into a ``TEMP`` table, then
``INSERT ... ON CONFLICT DO NOTHING`` into the target hypertable so re-loading
the same parquet files is idempotent. Connection settings are read from the
environment (the same ``HL_DB_*`` / ``POSTGRES_*`` vars used by the stack).
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql

ASSETCTX_COLUMNS: tuple[str, ...] = (
    "time",
    "coin",
    "mark_px",
    "oracle_px",
    "mid_px",
    "premium",
    "funding",
    "open_interest",
    "day_ntl_vlm",
)
TRADES_COLUMNS: tuple[str, ...] = (
    "time",
    "coin",
    "side",
    "px",
    "sz",
    "tid",
    "buyer",
    "seller",
)
BOOK_COLUMNS: tuple[str, ...] = (
    "time",
    "coin",
    "side",
    "lvl",
    "px",
    "sz",
    "n",
)


def _env(*names: str, default: str) -> str:
    """Return the first non-empty environment variable, else ``default``."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def dsn() -> str:
    """Build a libpq connection string from the environment.

    Prefers the ``HL_DB_*`` names used by the Grafana service, falling back to
    the ``POSTGRES_*`` names from ``.env``. Defaults target the local stack.

    Returns:
        A libpq DSN string suitable for :func:`psycopg.connect`.
    """
    host = _env("HL_DB_HOST", default="localhost")
    port = _env("HL_DB_PORT", "POSTGRES_PORT", default="5432")
    name = _env("HL_DB_NAME", "POSTGRES_DB", default="hlsignals")
    user = _env("HL_DB_USER", "POSTGRES_USER", default="hl")
    password = _env("HL_DB_PASSWORD", "POSTGRES_PASSWORD", default="hl")
    return f"host={host} port={port} dbname={name} user={user} password={password}"


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Open a connection to TimescaleDB, closing it on exit."""
    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.close()


def _clean(value: object) -> object:
    """Coerce a cell to a libpq-friendly Python value.

    numpy scalars become native Python; NaN floats become ``None`` (SQL NULL).
    pandas ``Timestamp`` is a ``datetime`` subclass and passes through unchanged.
    """
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _rows(df: pd.DataFrame, columns: Sequence[str]) -> Iterator[tuple[object, ...]]:
    for record in df[list(columns)].itertuples(index=False, name=None):
        yield tuple(_clean(v) for v in record)


def _upsert(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    df: pd.DataFrame,
) -> int:
    """Idempotently bulk-load ``df`` into ``table`` via a staging temp table.

    Args:
        conn: Open connection (committed on success).
        table: Target hypertable name.
        columns: Target columns, in the order present in ``df``.
        df: Rows to insert. Empty frames are a no-op.

    Returns:
        Number of rows actually inserted (excludes conflicts skipped).
    """
    if df.empty:
        return 0
    table_id = sql.Identifier(table)
    col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "CREATE TEMP TABLE _stage (LIKE {tbl} INCLUDING DEFAULTS) ON COMMIT DROP"
            ).format(tbl=table_id)
        )
        with cur.copy(
            sql.SQL("COPY _stage ({cols}) FROM STDIN").format(cols=col_sql)
        ) as copy:
            for row in _rows(df, columns):
                copy.write_row(row)
        cur.execute(
            sql.SQL(
                "INSERT INTO {tbl} ({cols}) SELECT {cols} FROM _stage ON CONFLICT DO NOTHING"
            ).format(tbl=table_id, cols=col_sql)
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


def upsert_assetctx(conn: psycopg.Connection, df: pd.DataFrame) -> int:
    """Load asset-context snapshots into the ``assetctx`` hypertable."""
    return _upsert(conn, "assetctx", ASSETCTX_COLUMNS, df)


def upsert_trades(conn: psycopg.Connection, df: pd.DataFrame) -> int:
    """Load trades into the ``trades`` hypertable."""
    return _upsert(conn, "trades", TRADES_COLUMNS, df)


def upsert_book(conn: psycopg.Connection, df: pd.DataFrame) -> int:
    """Load L2 order-book levels into the ``book_levels`` hypertable."""
    return _upsert(conn, "book_levels", BOOK_COLUMNS, df)
