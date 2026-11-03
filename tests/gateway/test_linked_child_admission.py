"""A generated child goal cannot replace or duplicate the original parent input."""
from types import SimpleNamespace

import pytest

from gateway.platforms.api_server_linked_child import prepare
from hermes_state import SessionDB
from gateway.session_passive_store import ensure_store_id
from hermes_state_runtime import RuntimeStoreError, begin_runtime_epoch


@pytest.fixture
def owner(tmp_path):
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('parent-a', source='api_server')
    ensure_store_id(db)
    epoch = begin_runtime_epoch(db, instance_id='fixture-owner')
    value = SimpleNamespace(db=db, epoch=epoch, profile_id=str(tmp_path))
    value.physical_target = lambda ref: ref.session_id
    yield value
    db.close()


def body():
    return {'session_id': 'parent-a', 'input': 'Please inspect the project',
            'origin': {'event_id': 'audio-one', 'origin_turn_id': 'turn-one'},
            'child': {'goal': 'Inspect the package manifest', 'context': 'Read-only source context',
                      'correlation_id': 'action-one'}}


def test_same_action_reuses_one_child_and_preserves_original_parent_bytes(owner):
    request = body()
    first = prepare(owner, principal='gateway-key-a', profile='default', body=request, key='one')
    again = prepare(owner, principal='gateway-key-a', profile='default', body=request, key='one')
    assert again['child_session_id'] == first['child_session_id']
    assert first['child_session_id'] != 'parent-a'
    assert first['request']['input'] == 'Inspect the package manifest'
    assert owner.db.get_messages('parent-a')[0]['content'] == 'Please inspect the project'
    assert len(owner.db.get_messages('parent-a')) == 1
    assert owner.db.get_session(first['child_session_id'])['parent_session_id'] == 'parent-a'
    changed = {**request, 'child': {**request['child'], 'goal': 'A different goal'}}
    with pytest.raises(RuntimeStoreError, match='event_conflict'):
        prepare(owner, principal='gateway-key-a', profile='default', body=changed, key='one')


def test_unproven_receipt_and_wrong_parent_create_no_child_or_parent_input(owner):
    request = body()
    request['origin']['receipt_id'] = 999
    with pytest.raises(RuntimeStoreError, match='event_conflict'):
        prepare(owner, principal='gateway-key-a', profile='default', body=request, key='one')
    assert owner.db.get_messages('parent-a') == []
    assert [row['id'] for row in owner.db.list_sessions_rich(limit=10)] == ['parent-a']


def test_removed_child_is_not_recreated_on_retry(owner):
    request = body()
    first = prepare(owner, principal='gateway-key-a', profile='default', body=request, key='one')
    owner.db.delete_session(first['child_session_id'])
    with pytest.raises(RuntimeStoreError, match='not_found'):
        prepare(owner, principal='gateway-key-a', profile='default', body=request, key='one')
    assert owner.db.get_session(first['child_session_id']) is None
