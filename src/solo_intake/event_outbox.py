"""ADR-0008 relay for intake.event_outbox (migration 0003): publish intake events to Kafka.

The rows are written by a trigger on intake.intakes in the same transaction as the change;
this module only relays them. Copied from architecture-docs/messaging (relay.py), as the
payment and knowledge cells did.

    INTAKE_RELAY_DATABASE_URL=... INTAKE_KAFKA_*=... intake-relay

Prints counts as JSON (no URLs, no event bodies). Exit 0 when nothing failed, 1 when a row
failed, 2 on setup errors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

PUBLISH_TIMEOUT_SECONDS = 15.0
# One batch commits within about this long (plus one publish timeout); a killed job would
# roll back the sent markers of its open batch.
BATCH_TIME_BUDGET_SECONDS = 60.0

TABLE = "intake.event_outbox"
TRY_LOCK = "SELECT pg_try_advisory_xact_lock(hashtext('adr0008-intake-outbox-relay'))"
RELAX_IDLE_TIMEOUT = (
    "SELECT set_config('idle_in_transaction_session_timeout', '60s', true)"
)
# A key whose oldest unsent row has failed sends only that row; a failed row waits for its
# backoff, so rows that keep failing cannot fill every batch.
SELECT_UNSENT = (
    f"SELECT o.id, o.topic, o.message_key, o.envelope FROM {TABLE} o"
    " WHERE o.sent_at IS NULL AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= now())"
    f" AND NOT EXISTS (SELECT 1 FROM {TABLE} f WHERE f.topic = o.topic"
    " AND f.message_key = o.message_key AND f.sent_at IS NULL AND f.attempts > 0"
    " AND f.seq < o.seq) ORDER BY o.seq LIMIT %s"
)
MARK_SENT = f"UPDATE {TABLE} SET sent_at = now(), attempts = attempts + 1, last_error = NULL WHERE id = %s"
# Backoff 1, 2, 4 … 64 minutes from the failure itself (clock_timestamp).
MARK_FAILED = (
    f"UPDATE {TABLE} SET attempts = attempts + 1, last_error = %s,"
    " next_attempt_at = clock_timestamp() + interval '1 minute' * power(2, least(attempts, 6))"
    " WHERE id = %s"
)
OLDEST_UNSENT = f"SELECT coalesce(extract(epoch FROM now() - min(created_at)), 0) FROM {TABLE} WHERE sent_at IS NULL"


class Publisher(Protocol):
    def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        """Return once the broker acknowledged the message; raise otherwise."""


@dataclass
class RelayResult:
    sent: int
    failed: int
    skipped: bool = False


def relay_once(
    conn: Any,
    publisher: Publisher,
    batch_size: int = 100,
    time_budget: float = BATCH_TIME_BUDGET_SECONDS,
) -> RelayResult:
    """Publish one batch in one explicit transaction (holds the relay lock throughout)."""
    sent = failed = 0
    with conn.transaction():
        conn.execute(RELAX_IDLE_TIMEOUT)
        locked = conn.execute(TRY_LOCK).fetchone()
        if not locked or not locked[0]:
            return RelayResult(0, 0, skipped=True)
        rows = conn.execute(SELECT_UNSENT, (batch_size,)).fetchall()
        blocked: set[tuple[str, str]] = set()
        deadline = time.monotonic() + time_budget
        for row_id, topic, key, envelope in rows:
            if time.monotonic() >= deadline:
                break  # the rest stay unsent for the next batch
            if (topic, key) in blocked:
                continue  # an earlier event for this key failed in this run; keep the order
            value = json.loads(envelope) if isinstance(envelope, str) else envelope
            try:
                publisher.publish(topic, key, value)
            except Exception as exc:  # noqa: BLE001 - recorded on the row (type only), retried after backoff
                conn.execute(MARK_FAILED, (type(exc).__name__, row_id))
                blocked.add((topic, key))
                failed += 1
                continue
            conn.execute(MARK_SENT, (row_id,))
            sent += 1
    return RelayResult(sent, failed)


def drain(
    conn: Any,
    publisher: Publisher,
    *,
    batch_size: int = 100,
    max_batches: int = 20,
    run_seconds: float = 300.0,
) -> RelayResult:
    """Run batches while they make progress (every processed row changes state)."""
    sent = failed = 0
    deadline = time.monotonic() + run_seconds
    for _ in range(max_batches):
        result = relay_once(conn, publisher, batch_size)
        sent += result.sent
        failed += result.failed
        if (
            result.skipped
            or result.sent + result.failed == 0
            or time.monotonic() >= deadline
        ):
            break
    return RelayResult(sent, failed)


class KafkaPublisher:
    """confluent-kafka producer (kafka-python-ng cannot authenticate to Kafka 4.x brokers)."""

    def __init__(
        self, config: dict[str, Any], timeout: float = PUBLISH_TIMEOUT_SECONDS
    ):
        from confluent_kafka import Producer

        self.timeout = timeout
        self.producer = Producer({**config, "acks": "all", "enable.idempotence": True})

    def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        result: dict[str, Any] = {}
        self.producer.produce(
            topic,
            key=key.encode(),
            value=json.dumps(value, separators=(",", ":")).encode(),
            on_delivery=lambda err, _message: result.setdefault("err", err),
        )
        deadline = time.monotonic() + self.timeout
        while "err" not in result and time.monotonic() < deadline:
            self.producer.poll(0.2)
        if "err" not in result:
            raise TimeoutError("broker did not acknowledge")
        if result["err"] is not None:
            raise RuntimeError(result["err"].name())

    def close(self) -> None:
        self.producer.flush(5)


def kafka_config_from_env(environ: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """SASL_SSL settings from INTAKE_KAFKA_* (Infisical /aiven: intake-producer)."""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as ca:
        ca.write(environ["INTAKE_KAFKA_CA_PEM"])
    return {
        "bootstrap.servers": environ["INTAKE_KAFKA_BOOTSTRAP"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": environ.get("INTAKE_KAFKA_SASL_MECHANISM", "SCRAM-SHA-256"),
        "sasl.username": environ["INTAKE_KAFKA_USERNAME"],
        "sasl.password": environ["INTAKE_KAFKA_PASSWORD"],
        "ssl.ca.location": ca.name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="intake-relay", description="Relay intake events to Kafka"
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-batches", type=int, default=20)
    parser.add_argument("--run-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    url = os.environ.get("INTAKE_RELAY_DATABASE_URL", "").strip()
    if not url:
        parser.error("set INTAKE_RELAY_DATABASE_URL (the intake_relay role)")
    import psycopg

    try:
        publisher = KafkaPublisher(kafka_config_from_env())
        conn = psycopg.connect(url, connect_timeout=20, autocommit=True)
    except Exception as exc:  # noqa: BLE001 - only the error class leaves the process
        print(json.dumps({"status": "error", "error": type(exc).__name__}))
        return 2
    try:
        result = drain(
            conn,
            publisher,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
            run_seconds=args.run_seconds,
        )
        row = conn.execute(OLDEST_UNSENT).fetchone()
        backlog = float(row[0]) if row else 0.0
    finally:
        publisher.close()
        conn.close()
    print(
        json.dumps(
            {
                "status": "failed" if result.failed else "ok",
                "sent": result.sent,
                "failed": result.failed,
                "oldest_unsent_seconds": round(backlog),
            }
        )
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
