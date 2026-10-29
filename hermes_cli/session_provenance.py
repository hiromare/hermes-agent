"""Public, narrowly projected provenance from the durable local creation receipt."""
import json

from hermes_state_local import POLICY_PREFIX


def session_provenance(db, session_id):
    row = db._read_one('SELECT value FROM state_meta WHERE key=?', (POLICY_PREFIX + session_id,))
    if not row:
        return None
    try:
        receipt = json.loads(row[0])
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
