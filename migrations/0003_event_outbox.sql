-- Intake cell: ADR-0008 event outbox (M5), added 2026-11-04. Do not edit once applied; add a new migration.
-- Every new intake and every status change writes one envelope, in the same transaction, through
-- a trigger; solo_intake.event_outbox relays the rows to Kafka data.ingest.v1. The envelope holds
-- reference fields only: no input_ref, lease owner or error message.

CREATE TABLE intake.event_outbox (
    seq             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id              text NOT NULL UNIQUE,
    topic           text NOT NULL,
    message_key     text NOT NULL,
    envelope        jsonb NOT NULL,
    attempts        integer NOT NULL DEFAULT 0,
    last_error      text,
    next_attempt_at timestamptz,
    sent_at         timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX event_outbox_unsent ON intake.event_outbox (seq) WHERE sent_at IS NULL;

-- Rows are written only by the trigger function (it runs as the owner); the relay role reads and
-- marks them. Nobody else sees the table.
ALTER TABLE intake.event_outbox ENABLE ROW LEVEL SECURITY;
CREATE POLICY relay_all ON intake.event_outbox TO intake_relay USING (true) WITH CHECK (true);
GRANT USAGE ON SCHEMA intake TO intake_relay;
DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO intake_relay', current_database()); END $$;
GRANT SELECT, UPDATE (attempts, last_error, next_attempt_at, sent_at) ON intake.event_outbox TO intake_relay;

CREATE FUNCTION intake.record_intake_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, intake AS $$
DECLARE
    event_id text := 'intake.intake.' || NEW.status || ':' || gen_random_uuid();
BEGIN
    INSERT INTO intake.event_outbox (id, topic, message_key, envelope)
    VALUES (
        event_id,
        'data.ingest.v1',
        NEW.workspace_id || ':' || NEW.id,
        jsonb_build_object(
            'id', event_id,
            'type', 'intake.intake.' || NEW.status,
            'version', 1,
            'occurred_at', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
            'producer', 'intake-api',
            'correlation_id', NEW.intake_key,
            'causation_id', NULL,
            'data', jsonb_build_object(
                'workspace_id', NEW.workspace_id,
                'intake_id', NEW.id,
                'intake_key', NEW.intake_key,
                'source_id', NEW.source_id,
                'domain', NEW.domain,
                'dataset', NEW.dataset,
                'schema_version', NEW.schema_version,
                'payload_kind', NEW.payload_kind,
                'privacy_class', NEW.privacy_class,
                'requested_by', NEW.requested_by,
                'status', NEW.status,
                'from_status', CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END,
                'attempt_count', NEW.attempt_count,
                'record_count', NEW.record_count,
                'raw_sha256', NEW.raw_sha256,
                'lake_run_id', NEW.lake_run_id,
                'lake_manifest_key', NEW.lake_manifest_key,
                'lake_bronze_object_key', NEW.lake_bronze_object_key,
                'error_code', NEW.error_code
            )
        )
    );
    RETURN NULL;
END
$$;
REVOKE ALL ON FUNCTION intake.record_intake_event() FROM PUBLIC;

-- The row lock of the intake serialises its writers, so outbox order per intake is commit order.
CREATE TRIGGER intake_created_event AFTER INSERT ON intake.intakes
    FOR EACH ROW EXECUTE FUNCTION intake.record_intake_event();
CREATE TRIGGER intake_status_event AFTER UPDATE OF status ON intake.intakes
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION intake.record_intake_event();
