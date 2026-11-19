-- Roastery application tables: batches, batch_series, batch_events.
-- This is the same DDL the lab applies through
-- scripts/setup_roastery_db.py; the two must be kept in step. The
-- statements are idempotent (IF NOT EXISTS), matching the script.
--
-- batches: one row per finished roast. Relational columns only for
-- listing and sorting; the full batch document lives in the `data`
-- JSONB column. batch_series: the roast curve, one row per sample,
-- keyed by batch_number. batch_events: one row per control button
-- press captured during a roast.

-- Connect to the application database (created by 01).
\c db

CREATE TABLE IF NOT EXISTS batches (
    id            BIGSERIAL PRIMARY KEY,
    batch_number  INTEGER NOT NULL UNIQUE,
    roast_start   TIMESTAMPTZ,
    roast_end     TIMESTAMPTZ,
    bean_name     TEXT,
    drop_temp_f   DOUBLE PRECISION,
    data          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batch_series (
    id            BIGSERIAL PRIMARY KEY,
    batch_number  INTEGER NOT NULL REFERENCES batches(batch_number)
                  ON DELETE CASCADE,
    t_offset_sec  INTEGER NOT NULL,
    sample_ts     TIMESTAMPTZ,
    bean_temp_f   DOUBLE PRECISION,
    rate_of_rise_f DOUBLE PRECISION,
    fan_level     INTEGER,
    heat_level    INTEGER
);

CREATE INDEX IF NOT EXISTS batch_series_batch_idx
    ON batch_series (batch_number, t_offset_sec);

CREATE TABLE IF NOT EXISTS batch_events (
    id            BIGSERIAL PRIMARY KEY,
    batch_number  INTEGER NOT NULL,
    action        TEXT NOT NULL,
    t_offset_sec  INTEGER,
    bean_temp_f   DOUBLE PRECISION,
    rate_of_rise_f DOUBLE PRECISION,
    fan_level     INTEGER,
    heat_level    INTEGER,
    pressed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    press_counter BIGINT
);

CREATE INDEX IF NOT EXISTS batch_events_batch_idx
    ON batch_events (batch_number, pressed_at);

-- Polish round 3 (HUNT-22): press_counter carries the
-- ActionCounter value of the press that wrote the row. The
-- unique index is the dedupe key for the library reconcile
-- fallback: a (batch_number, press_counter) pair can exist
-- exactly once, whoever wrote it. Rows written before this
-- column existed keep NULL, and NULLs never conflict.
ALTER TABLE batch_events
    ADD COLUMN IF NOT EXISTS press_counter BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS batch_events_press_counter_uidx
    ON batch_events (batch_number, press_counter);
