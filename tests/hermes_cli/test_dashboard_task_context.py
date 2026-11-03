"""Only host-proven HTTP admission can establish a plugin task actor."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from hermes_cli.dashboard_task_context import resolve_dashboard_task_context
from hermes_state import SessionDB
from gateway.session_passive_store import ensure_store_id


@pytest.fixture
def profile(tmp_path, monkeypatch):
    home = tmp_path / 'user'
    root = home / '.hermes'
    root.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setenv('HERMES_HOME', str(root))
    db = SessionDB(root / 'state.db')
    identity = ensure_store_id(db)
    db.close()
    return root, identity


def test_private_hosted_admission_binds_only_its_own_profile_and_store(profile):
    root, identity = profile
    request = SimpleNamespace(state=SimpleNamespace(hosted_http_authenticated=True))
    context = resolve_dashboard_task_context(request, 'default')
    assert context.profile_home == root
    assert context.store_id == identity
    assert context.principal_kind == 'shared_hosted_operator'
    other = root / 'profiles' / 'other'
    other.mkdir(parents=True)
    (other / 'config.yaml').write_text('model: test\n')
    with pytest.raises(HTTPException) as failure:
        resolve_dashboard_task_context(request, 'other')
    assert failure.value.status_code == 403
    assert not (other / 'state.db').exists()


def test_headers_cannot_forge_verified_host_admission(profile):
    request = SimpleNamespace(state=SimpleNamespace(),
        app=SimpleNamespace(state=SimpleNamespace(auth_required=True)),
        headers={'x-hosted-http-authenticated': 'true', 'x-forwarded-for': '127.0.0.1'})
    with pytest.raises(HTTPException) as failure:
        resolve_dashboard_task_context(request, 'default')
    assert failure.value.status_code == 401
