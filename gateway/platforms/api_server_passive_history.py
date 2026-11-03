"""Authenticated passive dialogue routes over the existing session owner."""
import asyncio
import hashlib
import json

from aiohttp import web

from gateway.session_contract import Principal, SessionRef
from hermes_state_runtime import RuntimeStoreError
from gateway.session_passive_store import CAPABILITIES, PassiveHistory, store_id


def _authority(adapter):
    from gateway.session_authorities import active_authority
    return active_authority(adapter.gateway_runner)


def capability_descriptor(adapter):
    authority = _authority(adapter)
    if authority is None or authority.retiring:
        return {}
    from gateway.platforms.api_server_linked_child import CAPABILITY
    result = {'store_id': store_id(authority.db), 'passive_history': CAPABILITIES}
    if adapter._run_idempotency_store.durable:
        result['linked_child_dispatch'] = CAPABILITY
    return result


def _error(reason, status=409):
    return web.json_response({'error': reason, 'retryable': reason in {'busy', 'store_unavailable'}}, status=status)


async def _dispatch(adapter, request, operation):
    if not adapter._expected_api_key():
        return _error('unauthorized', 401)
    refused = adapter._check_auth(request)
    if refused is not None:
        return refused
    authority = _authority(adapter)
    if authority is None or authority.retiring:
        return _error('unavailable', 503)
    from gateway.platforms.api_server import _api_request_profile
    profile = _api_request_profile.get() or 'default'
    principal = hashlib.sha256(adapter._expected_api_key().encode()).hexdigest()
    history = PassiveHistory(authority.db, epoch=authority.epoch, principal=principal, profile=profile)
    if operation == 'capabilities':
        return web.json_response({**CAPABILITIES, 'store_id': store_id(authority.db)})
    raw = await request.read()
    if len(raw) > CAPABILITIES['max_request_bytes']:
        return _error('payload_too_large', 413)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        return _error('invalid_input', 400)
    if not isinstance(body, dict) or not isinstance(body.get('session_id'), str):
        return _error('invalid_input', 400)
    ref = SessionRef(authority.profile_id, body['session_id'])
    actor = Principal('api', authority.profile_id,
                      frozenset({'session:read', 'session:control', 'session:operator'}), 'api-passive')
    authority.authorize(actor, ref, 'session:read' if operation in {'snapshot', 'reconcile'} else 'session:control')
    if operation == 'attach':
        result = await asyncio.to_thread(history.attach, body)
        result['snapshot'] = await asyncio.to_thread(history.snapshot, result_authority(result),
                                                    physical_session=authority.physical_target(ref))
    elif operation in {'snapshot', 'commit'}:
        result = await asyncio.to_thread(getattr(history, operation), body,
                                         physical_session=authority.physical_target(ref))
    else:
        result = await asyncio.to_thread(getattr(history, operation), body)
    return web.json_response(result)


def result_authority(result):
    return {key: result[key] for key in ('tab_id', 'session_id', 'attachment_id', 'generation')}


async def dispatch(adapter, request, operation):
    from hermes_state_errors import SessionTurnLeaseLostError
    from hermes_state import SessionCompressionInProgressError
    try:
        return await _dispatch(adapter, request, operation)
    except RuntimeStoreError as exc:
        reason = {'not_found': 'target_missing', 'permission_denied': 'denied',
                  'profile_mismatch': 'denied', 'stale_epoch': 'stale_attachment'}.get(exc.reason, exc.reason)
        return _error(reason, 400 if reason in {'invalid_input', 'not_passive'} else 409)
    except (SessionTurnLeaseLostError, SessionCompressionInProgressError):
        return _error('busy')


def http_routes(adapter):
    def handler(operation):
        async def invoke(request):
            return await dispatch(adapter, request, operation)
        return invoke
    return [('GET' if op == 'capabilities' else 'POST', '/v1/passive-history/' + op, handler(op))
            for op in ('capabilities', 'attach', 'snapshot', 'commit', 'reconcile', 'detach')]
