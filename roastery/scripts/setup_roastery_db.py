#!/usr/bin/env python3
"""Idempotent DDL for the Roastery v3 batch store (Postgres).

Data model (Eric's design, 2026-11-12):
- batches: one row per finished roast. Relational columns only for
  what gets listed, sorted, and filtered (batch_number is the human
  number and is UNIQUE; id is a surrogate primary key). Everything
  else about the batch (full metadata set, events with times and
  temps, phase durations, DTR, AUC, weights, roast degree, target
  profile, notes) lives in the `data` JSONB document, assembled and
  disassembled by the roastery scripting library, so the batch
  schema can evolve without migrations.
- batch_series: the roast curve for a batch, one row per sample,
  keyed by batch_number (foreign key, ON DELETE CASCADE). This is
  what "View as Background" reads, so every batch carries its own
  curve like an Artisan roast file.

Connection parameters come from the environment:
  ROASTERY_PGHOST (default localhost), ROASTERY_PGPORT (5432),
  ROASTERY_PGDB (db), ROASTERY_PGUSER (ignition),
  ROASTERY_PGPASSWORD (no default; for the lab, the password file
  at ROASTERY_PGPASSWORD_FILE is read instead when set).

Run with any python3; it shells out to psql.
"""
import os
import subprocess
import sys

DDL = """
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
"""


def main():
    password = os.environ.get("ROASTERY_PGPASSWORD")
    pw_file = os.environ.get("ROASTERY_PGPASSWORD_FILE")
    if not password and pw_file:
        with open(pw_file) as f:
            password = f.read().strip()
    if not password:
        sys.exit("Set ROASTERY_PGPASSWORD or ROASTERY_PGPASSWORD_FILE.")
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    cmd = [
        "psql",
        "-h", os.environ.get("ROASTERY_PGHOST", "localhost"),
        "-p", os.environ.get("ROASTERY_PGPORT", "5432"),
        "-U", os.environ.get("ROASTERY_PGUSER", "ignition"),
        "-d", os.environ.get("ROASTERY_PGDB", "db"),
        "-v", "ON_ERROR_STOP=1",
        "-c", DDL,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("Roastery batch store DDL applied (idempotent).")


if __name__ == "__main__":
    main()
