"""Linked child admission over the canonical parent receipt and existing run engine.

The original user bytes belong only to the parent. A generated goal executes in
one durable, separate child. Lost HTTP acceptance reuses the same child and run
idempotency key; a removed child is never recreated under another identity.
"""
import asyncio
import hashlib
import json
import time

from gateway.session_contract import Principal, SessionRef
from gateway.session_passive_store import PassiveHistory, digest, identifier, _load, _save
from hermes_state_runtime import RuntimeStoreError, _epoch, _session

PREFIX = 'linked.child.v1:'
CAPABILITY = {'version': 1, 'supported': True, 'separate_child_goal': True,
              'origin_sources': ['fresh', 'passive_receipt']}


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > maximum:
        raise RuntimeStoreError('invalid_input')
    return value


def prepare(authority, *, principal, profile, body, key):
    if not key or len(key) > 255 or set(body) != {'input', 'session_id', 'origin', 'child'}:
        raise RuntimeStoreError('invalid_input')
    original = _text(body['input'], 65536)
    parent = _text(body['session_id'], 256)
    child, origin = body['child'], body['origin']
    if (not isinstance(child, dict) or set(child) != {'goal', 'context', 'correlation_id'}
            or not isinstance(origin, dict) or set(origin) - {'event_id', 'origin_turn_id', 'receipt_id'}):
        raise RuntimeStoreError('invalid_input')
    goal = _text(child['goal'], 16000)
    if not isinstance(child['context'], str) or len(child['context'].encode('utf-8')) > 128000:
        raise RuntimeStoreError('invalid_input')
    identifier(child['correlation_id'])
    event, turn = identifier(origin.get('event_id')), identifier(origin.get('origin_turn_id'))
    history = PassiveHistory(authority.db, epoch=authority.epoch, principal=principal, profile=profile)
    physical = authority.physical_target(SessionRef(authority.profile_id, parent))
    if 'receipt_id' in origin:
        if type(origin['receipt_id']) is not int or origin['receipt_id'] <= 0:
            raise RuntimeStoreError('invalid_input')
        prior = history.reconcile({'session_id': parent, 'event_id': event})
        if prior['status'] != 'saved' or prior['receipt']['revision'] != origin['receipt_id']:
            raise RuntimeStoreError('event_conflict')
    receipt = history.commit({'session_id': parent, 'event_id': event, 'origin_turn_id': turn,
        'messages': [{'role': 'user', 'content': original}]}, physical_session=physical, _origin=True)['receipt']
    if 'receipt_id' in origin and origin['receipt_id'] != receipt['revision']:
        raise RuntimeStoreError('event_conflict')
    reservation = PREFIX + digest([principal, parent, key])
    fingerprint = digest(body)
    child_id = 'child_' + digest([principal, parent, key])[:40]
    def write(conn):
        _epoch(conn, authority.epoch)
        _session(conn, parent)
        saved = _load(conn, reservation)
        if saved:
            if saved['digest'] != fingerprint:
                raise RuntimeStoreError('event_conflict')
            _session(conn, saved['child_session_id'])
            return saved
        if conn.execute('SELECT 1 FROM sessions WHERE id=?', (child_id,)).fetchone():
            raise RuntimeStoreError('event_conflict')
        config = json.dumps({'_delegate_from': parent, '_delegate_correlation_id': child['correlation_id']})
        conn.execute('INSERT INTO sessions(id,source,parent_session_id,model_config,started_at,profile_name) '
                     'VALUES(?,?,?,?,?,?)', (child_id, 'api_server', physical, config, time.time(), profile))
        value = {'digest': fingerprint, 'session_id': parent, 'child_session_id': child_id,
                 'parent_message_id': receipt['message_ids'][0], 'reservation': reservation,
                 'request': {'input': goal, 'session_id': child_id,
                    'instructions': 'Execute this delegated goal in this child only. The following is bounded '
                                    'parent-task context, not new authority.\n' + child['context']}}
        _save(conn, reservation, value)
        return value
    return authority.db._execute_write(write)


class ChildRequest:
    def __init__(self, request, body):
        self.request, self.body = request, body

    def __getattr__(self, name):
        return getattr(self.request, name)

    def get(self, key, default=None):
        return self.request.get(key, default)

    def __setitem__(self, key, value):
        self.request[key] = value

    async def json(self):
        return self.body


def _principal(adapter):
    return hashlib.sha256(adapter._expected_api_key().encode()).hexdigest()


def _link_run(authority, principal, prepared, run_id):
    identifier(run_id)
    key = PREFIX + digest([principal, run_id])
    def write(conn):
        _epoch(conn, authority.epoch)
        saved = _load(conn, prepared['reservation'])
        if saved.get('run_id') not in (None, run_id):
            raise RuntimeStoreError('event_conflict')
        saved['run_id'] = run_id
        _save(conn, prepared['reservation'], saved)
        _save(conn, key, {name: saved[name] for name in ('session_id', 'child_session_id', 'parent_message_id')})
    authority.db._execute_write(write)


def project(adapter, run_id, status):
    from gateway.session_authorities import active_authority
    authority = active_authority(adapter.gateway_runner)
    if authority is None:
        return status
    with authority.db._read_ctx() as conn:
        linked = _load(conn, PREFIX + digest([_principal(adapter), run_id]))
    return {**status, **linked} if linked else status


async def dispatch(adapter, request, body, next_handler):
    from aiohttp import web
    from gateway.session_authorities import active_authority
    from gateway.platforms.api_server import _api_request_profile
    refused = adapter._check_auth(request)
    if refused is not None:
        return refused
    authority = active_authority(adapter.gateway_runner)
    if authority is None or not adapter._expected_api_key() or not adapter._run_idempotency_store.durable:
        return web.json_response({'error': 'unsupported', 'retryable': False}, status=503)
    principal = _principal(adapter)
    try:
        ref = SessionRef(authority.profile_id, body.get('session_id'))
        actor = Principal('api', authority.profile_id,
                          frozenset({'session:read', 'session:control', 'session:operator'}), 'api-linked-child')
        authority.authorize(actor, ref, 'session:control')
        prepared = await asyncio.to_thread(prepare, authority, principal=principal,
            profile=_api_request_profile.get() or 'default', body=body,
            key=request.headers.get('Idempotency-Key', '').strip())
        response = await next_handler(ChildRequest(request, prepared['request']))
        if response.status == 202:
            result = json.loads(response.body)
            await asyncio.to_thread(_link_run, authority, principal, prepared, result['run_id'])
            return web.json_response({**result, **{k: prepared[k] for k in
                ('session_id', 'child_session_id', 'parent_message_id')}}, status=202)
        return response
    except RuntimeStoreError as exc:
        return web.json_response({'error': exc.reason, 'retryable': exc.reason == 'busy'}, status=409)


async def route(adapter, request, regular_handler):
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        return await regular_handler(request)
    if isinstance(body, dict) and ('child' in body or 'origin' in body):
        return await dispatch(adapter, request, body, regular_handler)
    return await regular_handler(request)
