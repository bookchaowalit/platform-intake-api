"""ADR-0008 M5: intake events through a trigger-fed outbox (migration 0003) and the relay."""

import json
from typing import Any

import psycopg
import pytest
from intake_helpers import INTAKES, intake_id

from solo_intake import event_outbox


class Recorder:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str, dict[str, Any]]] = []
        self.fail = fail

    def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        if self.fail:
            raise TimeoutError("broker did not acknowledge")
        self.sent.append((topic, key, value))


def events(harness, target: int) -> list[dict[str, Any]]:
    rows = harness.superuser(
        "SELECT envelope FROM intake.event_outbox WHERE envelope->'data'->>'intake_id' = %s ORDER BY seq",
        (str(target),),
    )
    return [row[0] for row in rows]


def relay_conn(harness) -> psycopg.Connection[Any]:
    return harness.cluster.connect("intake_relay", autocommit=True)


def test_create_and_each_status_change_write_one_event(client, owner, harness):
    target = intake_id(client, owner)
    path = f"{INTAKES}/{target}"
    assert (
        client.patch(
            path, headers=owner, json={"status": "processing", "attempt_count": 1}
        ).status_code
        == 200
    )
    assert (
        client.patch(path, headers=owner, json={"lease_owner": "worker-1"}).status_code
        == 200
    )  # no status change
    assert (
        client.patch(
            path, headers=owner, json={"status": "landed", "record_count": 12}
        ).status_code
        == 200
    )
    found = events(harness, target)
    assert [e["type"] for e in found] == [
        "intake.intake.queued",
        "intake.intake.processing",
        "intake.intake.landed",
    ]
    assert [e["data"]["from_status"] for e in found] == [None, "queued", "processing"]
    assert found[2]["data"]["record_count"] == 12
    assert set(found[0]) == {
        "id",
        "type",
        "version",
        "occurred_at",
        "producer",
        "correlation_id",
        "causation_id",
        "data",
    }


def test_events_carry_references_only(client, owner, harness):
    target = intake_id(
        client, owner, lease_owner="worker-secret", error_message="bank said no"
    )
    text = json.dumps(events(harness, target))
    assert "inbox/2026-10/statement.csv" not in text  # input_ref
    assert "worker-secret" not in text
    assert "bank said no" not in text


def test_a_rolled_back_change_leaves_no_event(client, owner, harness):
    target = intake_id(client, owner)
    late = client.patch(
        f"{INTAKES}/{target}",
        headers=owner,
        json={"status": "processing", "expected_version": 9},
    )
    assert late.status_code == 409
    assert len(events(harness, target)) == 1


def test_relay_publishes_in_order_as_the_relay_role(client, owner, harness):
    target = intake_id(client, owner)
    client.patch(f"{INTAKES}/{target}", headers=owner, json={"status": "processing"})
    recorder = Recorder()
    with relay_conn(harness) as conn:
        result = event_outbox.drain(conn, recorder)
    assert result.failed == 0
    mine = [
        value for _, _, value in recorder.sent if value["data"]["intake_id"] == target
    ]
    assert [v["data"]["status"] for v in mine] == ["queued", "processing"]
    assert all(topic == "data.ingest.v1" for topic, _, _ in recorder.sent)
    with relay_conn(harness) as conn:
        assert event_outbox.drain(conn, Recorder()).sent == 0


def test_a_failed_row_backs_off_and_counts_as_progress(client, owner, harness):
    intake_id(client, owner)
    with relay_conn(harness) as conn:
        result = event_outbox.drain(
            conn, Recorder(fail=True), batch_size=1, max_batches=50
        )
    assert result.sent == 0
    assert result.failed >= 1
    rows = harness.superuser(
        "SELECT count(*) FROM intake.event_outbox WHERE sent_at IS NULL AND attempts > 0"
    )
    assert rows[0][0] >= 1
    harness.superuser(
        "UPDATE intake.event_outbox SET next_attempt_at = now() - interval '1 minute' RETURNING 1"
    )
    with relay_conn(harness) as conn:
        assert event_outbox.drain(conn, Recorder()).failed == 0


def test_least_privilege(harness):
    with (
        relay_conn(harness) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT 1 FROM intake.intakes")
    with (
        harness.cluster.connect(harness.cell.role("api")) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT 1 FROM intake.event_outbox")
    with (
        relay_conn(harness) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE intake.event_outbox SET envelope = '{}'::jsonb")


def test_a_second_relay_skips_while_the_first_holds_the_lock(harness):
    with relay_conn(harness) as holder, holder.transaction():
        holder.execute(event_outbox.TRY_LOCK)
        with relay_conn(harness) as conn:
            assert event_outbox.relay_once(conn, Recorder()).skipped


def test_a_batch_stops_when_its_time_budget_is_spent(client, owner, harness):
    intake_id(client, owner)
    with relay_conn(harness) as conn:
        assert event_outbox.relay_once(conn, Recorder(), time_budget=0).sent == 0


def test_kafka_config_and_main_without_a_url(monkeypatch):
    config = event_outbox.kafka_config_from_env(
        {
            "INTAKE_KAFKA_BOOTSTRAP": "b:1",
            "INTAKE_KAFKA_USERNAME": "intake-producer",
            "INTAKE_KAFKA_PASSWORD": "p",
            "INTAKE_KAFKA_CA_PEM": "PEM",
        }
    )
    assert config["security.protocol"] == "SASL_SSL"
    assert config["sasl.username"] == "intake-producer"
    monkeypatch.delenv("INTAKE_RELAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        event_outbox.main([])
