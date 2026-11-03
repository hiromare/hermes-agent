"""Verified dashboard actor and profile/store identity for bound plugin tasks.

Browser fields and Host/forwarding headers carry no authority. Hosted plugins
receive admission on the private IPC request scope; this is an explicit shared
operator role restricted to the plugin's own profile home, not an invented user.
"""
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException


@dataclass(frozen=True)
class DashboardTaskContext:
    principal_id: str
    principal_kind: str
    profile_name: str
    profile_home: Path
    store_id: str


def resolve_dashboard_task_context(request, profile=None):
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_active_profile_name, get_profile_dir, normalize_profile_name
    from hermes_state import SessionDB
    from gateway.session_passive_store import store_id

    name = normalize_profile_name(profile or get_active_profile_name())
    home = get_profile_dir(name).resolve()
    state = request.state
    native = getattr(state, 'native_http_principal', None)
    if getattr(state, 'hosted_http_authenticated', False) is True:
        if home != get_hermes_home().resolve():
            raise HTTPException(status_code=403, detail='profile_mismatch')
        from gateway.owner_identity import host_owner_subject
        principal, kind = host_owner_subject(), 'shared_hosted_operator'
    else:
        if native is not None and Path(native['profile_id']).resolve() != home:
            raise HTTPException(status_code=403, detail='profile_mismatch')
        from hermes_cli.web_server_sessions import _session_mutation_context
        _, actor = _session_mutation_context(request, name)
        if Path(actor.profile_id).resolve() != home:
            raise HTTPException(status_code=403, detail='profile_mismatch')
        principal, kind = actor.subject, 'verified_subject'
    # Reader only: the owning gateway provisions identity, never a dashboard writer.
    db = SessionDB(home / 'state.db', read_only=True)
    try:
        identity = store_id(db)
    finally:
        db.close()
    return DashboardTaskContext(principal, kind, name, home, identity)
