# `db-init` Directory

## Usage

Database initialization .sql scripts placed in this directory run on
the Postgres container's first start, through its
`docker-entrypoint-initdb.d` mechanism, in alphanumeric order. This
follows the convention documented in etknorr/project-template.

- `01-`: Schema and database creation

Only `01-roastery-schema.sql` ships here: it creates the `db`
database the gateway's `db` connection points at. The SQL historian
creates its own tables on first connection, so there is no table or
seed script counterpart to the template's example files.
