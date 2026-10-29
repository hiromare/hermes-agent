"""Cross-version session provenance contract uses the gateway's stable receipt reader."""

import json

import pytest

from hermes_cli import session_provenance as projection
from hermes_state_runtime import RuntimeStoreError


def _receipt(*, source="kanban", request_source="kanban"):
    return {
        "session_id": "worker-A",
        "policy": {"source": source, "request_json": json.dumps({
            "source": request_source, "board": "default", "task_id": "t_123",
            "run_id": 7, "claim_lock": "SECRET-NEVER-SERIALIZE",
        })},
    }


def test_projected_provenance_is_bounded_and_reads_canonical_receipt(monkeypatch):
    observed = []

    def reader(db, session_id):
        observed.append((db, session_id))
        return _receipt()

    monkeypatch.setattr(projection, "local_receipt", reader)
    db = object()
    assert projection.session_provenance(db, "worker-A") == {
        "origin": "kanban", "purpose": "worker", "board": "default",
        "task_id": "t_123", "run_id": 7, "evidence": "validated_creation_claim",
    }
    assert observed == [(db, "worker-A")]
    assert "SECRET" not in str(projection.session_provenance(db, "worker-A"))


@pytest.mark.parametrize("receipt", [
    _receipt(source="desktop"), _receipt(request_source="api_server"),
    {**_receipt(), "session_id": "other"}, {"policy": {}},
    {**_receipt(), "policy": {"source": "kanban", "request_json": "{}"}},
    {**_receipt(), "policy": {"source": "kanban", "request_json": "not-json"}},
])
def test_wrong_or_incomplete_creation_claim_is_not_worker_proof(monkeypatch, receipt):
    monkeypatch.setattr(projection, "local_receipt", lambda _db, _id: receipt)
    assert projection.session_provenance(object(), "worker-A") is None


def test_no_receipt_fails_closed_but_unrelated_authority_errors_propagate(monkeypatch):
    def reader(_db, _id):
        raise RuntimeStoreError("storage_unavailable")

    monkeypatch.setattr(projection, "local_receipt", reader)
    assert projection.session_provenance(object(), "missing") is None

    def refused(_db, _id):
        raise RuntimeStoreError("permission_denied")

    monkeypatch.setattr(projection, "local_receipt", refused)
    with pytest.raises(RuntimeStoreError, match="permission_denied"):
        projection.session_provenance(object(), "not-authorized")
