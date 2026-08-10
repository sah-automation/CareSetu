"""PHASE-1 T2b: consumed_events ledger helper contract (ticket #20).

Pins the idempotent-subscriber dedupe primitive (ADR-0002 §3, issue #16)
without a database: ``record_consumed_event`` inserts the delivery row into the
subscriber's own schema and returns whether it was newly written. A fake
connection reports the insert ``rowcount`` - 1 for a first delivery, 0 for a
replay that hit the ``event_id`` primary key - and records the executed
statement so the test can assert the ledger contract it builds.
"""

from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.compiler import Compiled

from bus.envelope import Envelope
from bus.ledger import record_consumed_event


class SamplePayload(BaseModel):
    sample_field: int


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeConnection:
    def __init__(self, rowcount: int) -> None:
        self._rowcount = rowcount
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self._rowcount)


def _envelope() -> Envelope[SamplePayload]:
    return Envelope[SamplePayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=SamplePayload(sample_field=1),
    )


def _compiled(statement: object) -> Compiled:
    return statement.compile(dialect=postgresql.dialect())


async def test_first_delivery_records_the_ledger_contract() -> None:
    connection = _FakeConnection(rowcount=1)
    envelope = _envelope()

    recorded = await record_consumed_event(
        connection, "iam", envelope, handler_result={"applied": True}
    )

    assert recorded is True
    statement = connection.executed[0]
    assert statement.table.name == "consumed_events"
    assert statement.table.schema == "iam"
    compiled = _compiled(statement)
    assert "ON CONFLICT (event_id) DO NOTHING" in str(compiled)
    assert compiled.params["event_id"] == envelope.event_id
    assert compiled.params["event_type"] == "phase1.round_trip"
    assert compiled.params["handler_result"] == {"applied": True}


async def test_replay_of_same_event_id_is_not_recorded_again() -> None:
    connection = _FakeConnection(rowcount=0)
    envelope = _envelope()

    recorded = await record_consumed_event(connection, "iam", envelope)

    assert recorded is False
    assert len(connection.executed) == 1


async def test_handler_result_defaults_to_null() -> None:
    connection = _FakeConnection(rowcount=1)

    await record_consumed_event(connection, "iam", _envelope())

    assert _compiled(connection.executed[0]).params["handler_result"] is None


async def test_processed_at_is_timezone_aware() -> None:
    connection = _FakeConnection(rowcount=1)

    await record_consumed_event(connection, "iam", _envelope())

    processed_at = _compiled(connection.executed[0]).params["processed_at"]
    assert processed_at.tzinfo is not None
