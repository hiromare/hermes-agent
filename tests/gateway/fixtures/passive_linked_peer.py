"""Disposable real owner + HTTP engine; only the model vendor wire is synthetic."""
import asyncio
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import traceback

from shared_authority_peer import ModelPeer


async def probe(peer):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.run import GatewayRunner
    from gateway.session_api import bind_api_steps, run_steps_off_loop
    from gateway.session_authority import initialize_session_authority
    from tests.waiting import async_wait_until

    runner = GatewayRunner()
    home = os.environ['HERMES_HOME']
    await initialize_session_authority(runner, profile_id=home, instance_id='passive-live-fixture')
    owner = runner.session_authority
    api = APIServerAdapter(PlatformConfig(enabled=True, extra={'key': 'fixture-api-gateway-key',
                                                               'model_name': 'local-wire-stub'}))
    api.gateway_runner = runner
    api.set_message_handler(runner._handle_message)
    runner.adapters[Platform.API_SERVER] = api
    await run_steps_off_loop(owner, bind_api_steps(owner, 'existing-parent'))
    app = web.Application()
    for method, path, handler in api._http_route_table():
        app.router.add_route(method, path, handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    headers = {'Authorization': 'Bearer fixture-api-gateway-key', 'Idempotency-Key': 'voice-action-one'}
    request = {'session_id': 'existing-parent', 'input': 'Original spoken user request',
        'origin': {'event_id': 'voice-input-one', 'origin_turn_id': 'voice-turn-one'},
        'child': {'goal': 'Inspect the fixture and reply once', 'context': 'Fixture context only',
                  'correlation_id': 'delegation-one'}}
    try:
        accepted = await client.post('/v1/runs', headers=headers, json=request)
        assert accepted.status == 202, await accepted.text()
        first = await accepted.json()
        again = await client.post('/v1/runs', headers=headers, json=request)
        assert again.status == 202, await again.text()
        second = await again.json()
        assert first['run_id'] == second['run_id']
        await async_wait_until(lambda: api._run_statuses.get(first['run_id'], {}).get('status')
                               in {'completed', 'failed', 'cancelled'}, timeout=30,
                               what='the linked child run to settle')
        response = await client.get('/v1/runs/' + first['run_id'], headers=headers)
        assert response.status == 200, await response.text()
        latest = await response.json()
        assert latest['status'] == 'completed', latest
        assert latest['session_id'] == 'existing-parent', latest
        assert latest['child_session_id'] == first['child_session_id']
        parents = owner.db.get_messages('existing-parent')
        assert [row['content'] for row in parents if row['role'] == 'user'] == ['Original spoken user request']
        child = owner.db.get_session(first['child_session_id'])
        assert child['parent_session_id'] == 'existing-parent'
        assert len(peer.requests) == 1, len(peer.requests)
        child_users = [row['content'] for row in owner.db.get_messages(first['child_session_id']) if row['role'] == 'user']
        assert child_users == ['Inspect the fixture and reply once'], child_users
        Path(home, 'linked-receipt.json').write_text(json.dumps({'one_child': True, 'one_provider_call': True,
            'parent_original_preserved': True, 'child_goal_separate': True, 'status': latest['status']}))
    finally:
        await client.close()
        await api.disconnect()


if __name__ == '__main__':
    peer = ThreadingHTTPServer(('127.0.0.1', 0), ModelPeer)
    peer.requests, peer.metadata_requests = [], []
    peer.blocked, peer.release = threading.Event(), threading.Event()
    threading.Thread(target=peer.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{peer.server_port}/v1'
    os.environ.update(OPENAI_API_KEY='fixture-not-a-real-key', OPENAI_BASE_URL=base)
    Path(os.environ['HERMES_HOME'], 'config.yaml').write_text(
        f'model:\n  default: local-wire-stub\n  provider: custom\n  base_url: {base}\n'
        f'auxiliary:\n  title_generation:\n    enabled: false\nterminal:\n  cwd: {os.environ["HERMES_HOME"]}\n')
    status = 0
    try:
        asyncio.run(probe(peer))
    except BaseException:
        traceback.print_exc()
        status = 1
    finally:
        peer.server_close()
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(status)
