-- Roles for the intake database. Locally a superuser runs this; on Neon
-- `intake-db provision` creates the same roles through the migrator.
--
-- intake_migrator  owns the schema and runs migrations only.
-- intake_api       the API at runtime: no superuser, no BYPASSRLS, owns nothing.
-- intake_publisher sweeps and marks the outbox across workspaces; nothing else.
-- intake_relay     relays intake.event_outbox to Kafka (ADR-0008); nothing else.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'intake_migrator') THEN
        CREATE ROLE intake_migrator LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'intake_api') THEN
        CREATE ROLE intake_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'intake_publisher') THEN
        CREATE ROLE intake_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'intake_relay') THEN
        CREATE ROLE intake_relay LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
