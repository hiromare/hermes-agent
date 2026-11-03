"""Passive dialogue receipts share the owner transaction and lease guard."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from hermes_state import SessionDB
from gateway.session_passive_store import PassiveHistory, ensure_store_id
from hermes_state_runtime import RuntimeStoreError, begin_runtime_epoch


@pytest.fixture
def history(tmp_path):
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('chat-a', source='api_server')
    db.create_session('chat-b', source='api_server')
    ensure_store_id(db)
    epoch = begin_runtime_epoch(db, instance_id='test-owner')
    value = PassiveHistory(db, epoch=epoch, principal='operator-a', profile='default')
    yield value
    db.close()


def payload(history):
    attached = history.attach({'session_id': 'chat-a', 'tab_id': 'tab-a'})
    return {key: attached[key] for key in ('session_id', 'tab_id', 'attachment_id', 'generation')} | {
        'event_id': 'utterance-a', 'origin_turn_id': 'turn-a',
        'messages': [{'role': 'user', 'content': 'Voice question'}, {'role': 'assistant', 'content': 'Voice answer'}]}


def test_concurrent_identical_commits_have_one_canonical_pair_and_one_receipt(history):
    body = payload(history)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: history.commit(body, physical_session='chat-a'), range(2)))
    assert results[0]['receipt']['message_ids'] == results[1]['receipt']['message_ids']
    assert [row['content'] for row in history.db.get_messages('chat-a')] == ['Voice question', 'Voice answer']
    assert history.db.get_messages('chat-b') == []
    with pytest.raises(RuntimeStoreError, match='event_conflict'):
        history.commit({**body, 'messages': [{'role': 'user', 'content': 'different'}]}, physical_session='chat-a')


def test_restart_reconciles_saved_receipt_but_refuses_old_attachment_for_new_input(history):
    body = payload(history)
    saved = history.commit(body, physical_session='chat-a')
    epoch = begin_runtime_epoch(history.db, instance_id='new-owner')
    restarted = PassiveHistory(history.db, epoch=epoch, principal='operator-a', profile='default')
    reconciled = restarted.reconcile({'session_id': 'chat-a', 'event_id': body['event_id']})
    assert reconciled['receipt']['message_ids'] == saved['receipt']['message_ids']
    with pytest.raises(RuntimeStoreError, match='stale_attachment'):
        restarted.commit({**body, 'event_id': 'new-event'}, physical_session='chat-a')


def test_stale_or_foreign_attachment_cannot_move_transcript(history):
    body = payload(history)
    other = PassiveHistory(history.db, epoch=history.epoch, principal='other-operator', profile='default')
    for instance, changed in [(history, {**body, 'session_id': 'chat-b'}), (other, body)]:
        with pytest.raises(RuntimeStoreError, match='stale_attachment'):
            instance.commit(changed, physical_session=changed['session_id'])
    assert history.db.get_messages('chat-a') == []
    assert history.db.get_messages('chat-b') == []


def test_active_turn_refuses_passive_commit_without_partial_receipt(history):
    from hermes_state_errors import SessionTurnLeaseLostError
    body = payload(history)
    holder = 'fixture-owner'
    assert history.db.acquire_session_turn_lease('chat-a', holder)
    try:
        with pytest.raises(SessionTurnLeaseLostError):
            history.commit(body, physical_session='chat-a')
        assert history.reconcile({'session_id': 'chat-a', 'event_id': body['event_id']})['status'] == 'unknown'
    finally:
        history.db.release_session_turn_lease('chat-a', holder)


def test_tool_or_partial_payload_never_reaches_canonical_history(history):
    body = payload(history)
    for messages in ([{'role': 'tool', 'content': 'generated'}], [{'role': 'user', 'content': ''}]):
        with pytest.raises(RuntimeStoreError, match='not_passive'):
            history.commit({**body, 'messages': messages}, physical_session='chat-a')
    assert history.db.get_messages('chat-a') == []


def test_rewound_capture_cannot_be_reported_saved_or_reinserted(history):
    body = payload(history)
    saved = history.commit(body, physical_session='chat-a')
    history.db.rewind_to_message('chat-a', saved['receipt']['message_ids'][0])
    with pytest.raises(RuntimeStoreError, match='retired'):
        history.reconcile({'session_id': 'chat-a', 'event_id': body['event_id']})
    with pytest.raises(RuntimeStoreError, match='retired'):
        history.commit(body, physical_session='chat-a')
    assert history.db.get_messages('chat-a') == []
