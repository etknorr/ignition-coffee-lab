# `db-init` Directory

## Usage

Database initialization .sql scripts placed in this directory run on
the Postgres container's first start, through its
`docker-entrypoint-initdb.d` mechanism, in alphanumeric order. This
follows the convention documented in etknorr/project-template.

- `01-`: Schema and database creation
- `02-`: Application tables

`01-roastery-schema.sql` creates the `db` database the gateway's
`db` connection points at. `02-roastery-app-tables.sql` creates
the application tables (batches, batch_series, batch_events) with
the same DDL the lab applies through
`scripts/setup_roastery_db.py`; keep the two in step. The SQL
historian creates its own tables on first connection, so there
is no historian table script here.
