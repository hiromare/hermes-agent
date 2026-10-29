"""Public, narrowly projected provenance from the durable local creation receipt."""
import json

from hermes_state_local import local_receipt
from hermes_state_runtime import RuntimeStoreError


def session_provenance(db, session_id):
    # Reuse the gateway owner's established reader, not its private state_meta
    # layout or the SessionDB's private SQL API. A missing/invalid receipt is
    # not authoritative evidence of a worker.
    try:
        receipt = local_receipt(db, session_id)
    except RuntimeStoreError as exc:
        if exc.reason == 'storage_unavailable':
            return None
        raise
    try:
        policy = receipt['policy']
        request = json.loads(policy['request_json'])
        if receipt['session_id'] != session_id or policy['source'] != 'kanban' or request['source'] != 'kanban':
            return None
        board, task_id, run_id = request['board'], request['task_id'], request['run_id']
        if not isinstance(board, str) or not board or not isinstance(task_id, str) or not task_id:
            return None
        if type(run_id) is not int or run_id <= 0:
            return None
        return {'origin': 'kanban', 'purpose': 'worker', 'board': board,
                'task_id': task_id, 'run_id': run_id, 'evidence': 'validated_creation_claim'}
    except (KeyError, TypeError, ValueError):
        return None
