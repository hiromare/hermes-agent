"""Real owner, HTTP admission, persistence, status, and provider request count."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_retry_keeps_original_parent_and_one_real_child_run(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    home, state = tmp_path / 'home', tmp_path / 'state'
    home.mkdir()
    state.mkdir()
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ', 'SYSTEMROOT') if key in os.environ}
    env.update(HOME=str(home), USERPROFILE=str(home), HERMES_HOME=str(state),
               PYTHONPATH=str(repo), PYTHONUNBUFFERED='1')
    result = subprocess.run([sys.executable, str(Path(__file__).parent / 'fixtures/passive_linked_peer.py')],
        cwd=repo, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((state / 'linked-receipt.json').read_text())
    assert receipt == {'one_child': True, 'one_provider_call': True, 'parent_original_preserved': True,
                       'child_goal_separate': True, 'status': 'completed'}
