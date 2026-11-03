"""Authenticated HTTP roundtrip through the real SessionAuthority and writer."""
import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import Platform, PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from gateway.platforms.api_server_passive_history import http_routes
from gateway.session import SessionSource
from gateway.session_authority import LiveSession, SessionAuthority
from hermes_state import SessionDB
from gateway.session_passive_store import ensure_store_id
from hermes_state_runtime import begin_runtime_epoch


@pytest.mark.asyncio
async def test_http_authentication_and_retry_preserve_exact_existing_chat(tmp_path):
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('existing-chat', source='api_server')
    identity = ensure_store_id(db)
    epoch = begin_runtime_epoch(db, instance_id='fixture')
    runner = SimpleNamespace(session_authorities=None)
    owner = SessionAuthority(runner, profile_id=str(tmp_path), instance_id='fixture', db=db, epoch=epoch)
    runner.session_authority = owner
    owner.sessions['existing-chat'] = LiveSession(
        SessionSource(platform=Platform.API_SERVER, chat_id='existing-chat', user_id='api', chat_type='dm'),
        'fixture-api-route')
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={'key': 'fixture-http-gateway-key'}))
    adapter.gateway_runner = runner
    app = web.Application()
    for method, path, handler in http_routes(adapter):
        app.router.add_route(method, path, handler)
    app.router.add_get('/v1/capabilities', adapter._handle_capabilities)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        denied = await client.get('/v1/passive-history/capabilities')
        assert denied.status == 401
        headers = {'Authorization': 'Bearer fixture-http-gateway-key'}
        capabilities = await client.get('/v1/capabilities', headers=headers)
        assert capabilities.status == 200
        assert (await capabilities.json())['store_id'] == identity
        attached = await client.post('/v1/passive-history/attach', headers=headers,
                                     json={'session_id': 'existing-chat', 'tab_id': 'voice-tab'})
        assert attached.status == 200, await attached.text()
        body = await attached.json()
        fields = {key: body[key] for key in ('session_id', 'tab_id', 'generation', 'attachment_id')}
        payload = {**fields, 'event_id': 'voice-event', 'origin_turn_id': 'voice-turn',
                   'messages': [{'role': 'user', 'content': 'Actual captured words'}]}
        for _ in range(2):
            committed = await client.post('/v1/passive-history/commit', headers=headers, json=payload)
            assert committed.status == 200, await committed.text()
        snapshot = await client.post('/v1/passive-history/snapshot', headers=headers, json=fields)
        assert snapshot.status == 200
        rows = (await snapshot.json())['messages']
        assert [row['content'] for row in rows] == ['Actual captured words']
        other = await client.post('/v1/passive-history/commit', headers=headers,
                                  json={**payload, 'session_id': 'missing-chat'})
        assert other.status == 409
        assert len(db.get_messages('existing-chat')) == 1
        detached = await client.post('/v1/passive-history/detach', headers=headers, json=fields)
        assert detached.status == 200
        assert await detached.json() == {'status': 'detached'}
    finally:
        await client.close()
        await adapter.disconnect()
        db.close()
