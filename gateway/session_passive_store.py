"""Owner-only, idempotent ingress for finalized external dialogue.

The owning SessionDB executes every mutation. Callers prove session access first;
this module keeps the runtime epoch, attachment and transcript lease checks inside
that same transaction. No inference or provider calls occur here.
"""
import hashlib
import json
import re
import uuid

from hermes_state_runtime import RuntimeStoreError, _epoch, _session

PREFIX = 'passive.v1:'
ID = re.compile(r'[A-Za-z0-9._-]{1,128}\Z')
CAPABILITIES = {
    'version': 1, 'passive_only': True, 'origin_adoption': True,
    'operations': ['attach', 'snapshot', 'commit', 'reconcile', 'detach'],
    'max_request_bytes': 163840, 'max_message_bytes': 65536, 'max_messages': 2,
    'max_snapshot_messages': 20, 'max_snapshot_bytes': 32768,
    'restart_requires_reattach': True,
}


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RuntimeStoreError('invalid_input')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def store_id(db):
    with db._read_ctx() as conn:
        row = conn.execute("SELECT value FROM state_meta WHERE key='store_instance_id'").fetchone()
    if not row or not row[0]:
        raise RuntimeStoreError('store_unavailable')
    return row[0]


def ensure_store_id(db):
    value = str(uuid.uuid4())
    def write(conn):
        conn.execute("INSERT OR IGNORE INTO state_meta(key,value) VALUES('store_instance_id',?)", (value,))
    db._execute_write(write)
    return store_id(db)


def _load(conn, key):
    row = conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _save(conn, key, value):
    conn.execute('INSERT INTO state_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, json.dumps(value, ensure_ascii=False)))


def _receipt_rows_present(conn, receipt):
    ids = receipt['message_ids']
    count = conn.execute('SELECT count(*) FROM messages WHERE session_id=? AND (active=1 OR compacted=1) AND id IN ('
        + ','.join('?' for _ in ids) + ')', (receipt['session_id'], *ids)).fetchone()[0]
    if count != len(ids):
        raise RuntimeStoreError('retired')


class PassiveHistory:
    def __init__(self, db, *, epoch, principal, profile):
        self.db, self.epoch, self.principal, self.profile = db, epoch, principal, profile
        self.prefix = PREFIX + digest(principal) + ':'

    def _attachment_key(self, tab):
        return self.prefix + 'tab:' + identifier(tab)

    def _event_key(self, event):
        return self.prefix + 'event:' + identifier(event)

    def attach(self, body):
        if set(body) != {'tab_id', 'session_id'}:
            raise RuntimeStoreError('invalid_input')
        selected, tab = body['session_id'], identifier(body['tab_id'])
        key = self._attachment_key(tab)
        def write(conn):
            _epoch(conn, self.epoch)
            _session(conn, selected)
            for stale_key, encoded in conn.execute('SELECT key,value FROM state_meta WHERE key LIKE ?',
                    (self.prefix + 'tab:%',)).fetchall():
                record = json.loads(encoded)
                if record['epoch'] != self.epoch or not conn.execute('SELECT 1 FROM sessions WHERE id=?',
                        (record['session_id'],)).fetchone():
                    conn.execute('DELETE FROM state_meta WHERE key=?', (stale_key,))
            old = _load(conn, key)
            # One bounded active selector set, while event receipts remain durable.
            if old is None and conn.execute('SELECT count(*) FROM state_meta WHERE key LIKE ?',
                    (self.prefix + 'tab:%',)).fetchone()[0] >= 64:
                raise RuntimeStoreError('busy')
            record = {'tab_id': tab, 'session_id': selected, 'attachment_id': uuid.uuid4().hex,
                      'generation': (old['generation'] if old else 0) + 1, 'epoch': self.epoch}
            _save(conn, key, record)
            return {name: record[name] for name in ('tab_id', 'session_id', 'attachment_id', 'generation')}
        return {**self.db._execute_write(write), 'profile': self.profile}

    def _check(self, conn, body):
        _epoch(conn, self.epoch)
        _session(conn, body['session_id'])
        record = _load(conn, self._attachment_key(body.get('tab_id')))
        fields = ('tab_id', 'session_id', 'attachment_id', 'generation')
        if (not record or type(body.get('generation')) is not int or record['epoch'] != self.epoch
                or any(body.get(name) != record[name] for name in fields)):
            raise RuntimeStoreError('stale_attachment')

    def snapshot(self, body, *, physical_session):
        with self.db._read_ctx() as conn:
            self._check(conn, body)
        messages = self.db.get_messages(physical_session, limit=21, latest=True, include_ancestors=True)
        rows, size = [], 0
        candidates = [row for row in messages if row.get('role') in {'user', 'assistant'}
                      and isinstance(row.get('content'), str) and row['content'].strip()]
        for row in reversed(candidates):
            content = row['content']
            count = len(content.encode('utf-8'))
            if len(rows) >= 20 or size + count > 32768:
                break
            rows.append({'id': row['id'], 'role': row['role'], 'content': content})
            size += count
        return {'profile': self.profile, 'conversation_id': body['session_id'], 'session_id': physical_session,
                'messages': list(reversed(rows)), 'truncated': len(messages) >= 21 or len(rows) < len(candidates),
                'capabilities': CAPABILITIES, 'store_id': store_id(self.db)}

    def commit(self, body, *, physical_session, _origin=False):
        required = {'tab_id', 'session_id', 'attachment_id', 'generation', 'event_id', 'origin_turn_id', 'messages'}
        if _origin:
            required -= {'tab_id', 'attachment_id', 'generation'}
        if set(body) != required:
            raise RuntimeStoreError('invalid_input')
        identifier(body['origin_turn_id'])
        rows = body['messages']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
            raise RuntimeStoreError('invalid_input')
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'role', 'content'}
                    or row['role'] not in {'user', 'assistant'} or not isinstance(row['content'], str)
                    or not row['content'].strip() or len(row['content'].encode('utf-8')) > 65536):
                raise RuntimeStoreError('not_passive')
        if len(rows) == 2 and [row['role'] for row in rows] != ['user', 'assistant']:
            raise RuntimeStoreError('not_passive')
        key = self._event_key(body['event_id'])
        fingerprint = digest([body['session_id'], body['origin_turn_id'], rows])
        def write(conn):
            _epoch(conn, self.epoch)
            _session(conn, body['session_id'])
            _session(conn, physical_session)
            saved = _load(conn, key)
            if saved:
                if saved['digest'] != fingerprint:
                    raise RuntimeStoreError('event_conflict')
                _receipt_rows_present(conn, saved['receipt'])
                return {**saved['receipt'], 'replayed': True}
            if not _origin:
                self._check(conn, body)
            # Compression/admission can move the selected transcript after an HTTP read.
            from hermes_state_runtime import _canonical_chain
            if _canonical_chain(conn, body['session_id'])[-1] != physical_session:
                raise RuntimeStoreError('busy')
            self.db._check_transcript_write_guards(conn, physical_session, None,
                                                  reject_active_turn_lease=True,
                                                  reject_active_compression_lock=True)
            logical = self.db._session_turn_lease_key_on_conn(conn, body['session_id'])
            if conn.execute("SELECT 1 FROM session_admissions WHERE target_session_id=? "
                            "AND status IN ('started','unknown') LIMIT 1", (logical,)).fetchone():
                raise RuntimeStoreError('busy')
            messages = [dict(row) for row in rows]
            self.db._append_messages_in_transaction(conn, physical_session, messages)
            ids = [row['_row_id'] for row in messages]
            receipt = {'producer': 'passive.ingress.v1', 'event_id': body['event_id'],
                       'origin_turn_id': body['origin_turn_id'], 'conversation_id': body['session_id'],
                       'session_id': physical_session, 'message_ids': ids,
                       'revision': max(ids), 'replayed': False}
            _save(conn, key, {'digest': fingerprint, 'receipt': receipt})
            return receipt
        return {'profile': self.profile, 'status': 'saved', 'receipt': self.db._execute_write(write)}

    def reconcile(self, body):
        if set(body) != {'session_id', 'event_id'}:
            raise RuntimeStoreError('invalid_input')
        with self.db._read_ctx() as conn:
            _session(conn, body['session_id'])
            saved = _load(conn, self._event_key(body['event_id']))
            if saved and saved['receipt']['conversation_id'] != body['session_id']:
                raise RuntimeStoreError('event_conflict')
            if saved:
                _receipt_rows_present(conn, saved['receipt'])
        return {'profile': self.profile, 'status': 'saved' if saved else 'unknown',
                'receipt': {**saved['receipt'], 'replayed': True} if saved else None}

    def detach(self, body):
        def write(conn):
            self._check(conn, body)
            conn.execute('DELETE FROM state_meta WHERE key=?', (self._attachment_key(body['tab_id']),))
        self.db._execute_write(write)
        return {'profile': self.profile, 'status': 'detached'}
