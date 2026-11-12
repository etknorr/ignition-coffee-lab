-- Create database
-- Mirrors services/db/init/1-schema.sql in etknorr/project-template:
-- the database, the connection, and the historian are all named "db",
-- so one gateway config definition serves every deployment mode.
CREATE DATABASE db;

-- Connect to the database
\c db

-- Grant privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT ALL PRIVILEGES ON TABLES TO ignition;

-- No table creation here on purpose: the SQL historian creates and
-- owns its own tables the first time it connects.
