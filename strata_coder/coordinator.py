from .depth import resolve as resolve_depth
"""Shared durable task queue and bounded inference proxy. Standard library only.

A coordinator is a single-user trust domain. Its token grants administrative
access; owner labels provide fairness, not multi-tenant authorization.
"""
import argparse
from contextlib import contextmanager
from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
from .transport import Transport


TERMINAL = {'applied', 'cancelled', 'failed', 'interrupted', 'needs_supervisor', 'needs_rebase', 'review_ready'}


class Conflict(ValueError): pass


class Store:
    def __init__(self, path, max_workers=4, capacity=1000, per_owner=100, lease_seconds=60):
        for n in (max_workers, capacity, per_owner, lease_seconds):
            if type(n) is not int or n < 1:
                raise ValueError('Limits must be positive integers')
        self.max_workers, self.capacity, self.per_owner, self.lease_seconds = max_workers, capacity, per_owner, lease_seconds
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, workspace TEXT NOT NULL, owner TEXT NOT NULL,
          request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, contract TEXT NOT NULL,
          base TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
          revision INTEGER NOT NULL DEFAULT 0, worker TEXT, lease TEXT,
          expires REAL, result TEXT, approved_hash TEXT, apply_requested REAL,
          UNIQUE(workspace, owner, request_key));
        CREATE TABLE IF NOT EXISTS fairness (owner TEXT PRIMARY KEY, served REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
          workspace TEXT NOT NULL, task_id TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS blocked_apply (workspace TEXT PRIMARY KEY);
        CREATE INDEX IF NOT EXISTS queue_idx ON tasks(status, workspace, created);
        ''')
        if 'apply_requested' not in [r[1] for r in self.db.execute('PRAGMA table_info(tasks)')]:
            self.db.execute('ALTER TABLE tasks ADD COLUMN apply_requested REAL')
        # Never blindly replay a side-effecting task after a server restart.
        with self.transaction():
            for row in self.db.execute("SELECT * FROM tasks WHERE status IN ('running','cancelling','applying')").fetchall():
                if row['status'] == 'applying':
                    self.db.execute('INSERT OR IGNORE INTO blocked_apply VALUES (?)', (row['workspace'],))
                self._state(row['id'], 'interrupted')
            active = self.get_meta('inference_active', '0')
            if int(active):
                self.set_meta('inference_blocked', 'Previous coordinator stopped during inference. Verify upstream is idle, then reset.')
            self.set_meta('inference_active', '0')

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = not self.db.in_transaction
            if outer: self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                if outer: self.db.execute('COMMIT')
            except Exception:
                if outer: self.db.execute('ROLLBACK')
                raise

    def get_meta(self, key, default=''):
        with self.transaction():
            r = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return r[0] if r else default

    def set_meta(self, key, value):
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def _row(self, tid, workspace):
        r = self.db.execute('SELECT * FROM tasks WHERE id=? AND workspace=?', (tid, workspace)).fetchone()
        if r is None:
            raise ValueError('Unknown task in this workspace')
        return r

    def _state(self, tid, status, result=None):
        self.db.execute('UPDATE tasks SET status=?, revision=revision+1 WHERE id=?', (status, tid))
        if result is not None:
            self.db.execute('UPDATE tasks SET result=? WHERE id=?', (json.dumps(result), tid))
        r = self.db.execute('SELECT workspace FROM tasks WHERE id=?', (tid,)).fetchone()
        self.db.execute('INSERT INTO events(workspace,task_id,status) VALUES (?,?,?)', (r[0], tid, status))

    def expire(self):
        with self.transaction():
            for r in self.db.execute("SELECT * FROM tasks WHERE status IN ('running','cancelling','applying') AND expires < ?", (time.time(),)).fetchall():
                if r['status'] == 'applying':
                    self.db.execute('INSERT OR IGNORE INTO blocked_apply VALUES (?)', (r['workspace'],))
                self._state(r['id'], 'interrupted', {'reason': 'Worker lease expired; side effects not replayed.'})

    def submit(self, workspace, owner, request_key, contract, base):
        for v in (workspace, owner, request_key, base):
            if not isinstance(v, str) or not 1 <= len(v) <= 200:
                raise ValueError('workspace, owner, request_key and base require bounded strings')
        if isinstance(contract, dict) and any(k in contract for k in ('depth','reasoning_effort','max_output_tokens')):
            resolve_depth({}, **{k:contract[k] for k in ('depth','reasoning_effort','depth_reason','max_output_tokens') if k in contract})
        raw = json.dumps(contract, sort_keys=True)
        if not isinstance(contract, dict) or len(raw) > 16000:
            raise ValueError('Contract must be a bounded object')
        fingerprint = hashlib.sha256((base + raw).encode()).hexdigest()
        with self.transaction():
            self.expire()
            existing = self.db.execute('SELECT * FROM tasks WHERE workspace=? AND owner=? AND request_key=?', (workspace, owner, request_key)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise Conflict('Idempotency key was already used for a different contract/base')
                return {'task_id': existing['id'], 'status': existing['status'], 'deduplicated': True}
            count = self.db.execute("SELECT count(*) FROM tasks WHERE status IN ('queued','running','cancelling','apply_queued','applying')").fetchone()[0]
            owner_count = self.db.execute("SELECT count(*) FROM tasks WHERE owner=? AND status IN ('queued','running','cancelling','apply_queued','applying')", (owner,)).fetchone()[0]
            if count >= self.capacity or owner_count >= self.per_owner:
                raise Conflict('Queue capacity reached; wait before submitting new work')
            tid = uuid.uuid4().hex
            self.db.execute('INSERT INTO tasks(id,workspace,owner,request_key,fingerprint,contract,base,status,created) VALUES (?,?,?,?,?,?,?,?,?)',
                            (tid, workspace, owner, request_key, fingerprint, raw, base, 'queued', time.time()))
            self._state(tid, 'queued')
            return {'task_id': tid, 'status': 'queued', 'deduplicated': False}

    def claim(self, workspace, worker, kind='work'):
        if kind not in ('work', 'apply'):
            raise ValueError('Invalid claim kind')
        with self.transaction():
            self.expire()
            if kind == 'work':
                self.db.execute('INSERT OR REPLACE INTO workers VALUES (?,?,?)', (worker, workspace, time.time()+15))
            active = self.db.execute("SELECT count(*) FROM tasks WHERE status IN ('running','cancelling')").fetchone()[0]
            if kind == 'work' and active >= self.max_workers:
                return None
            if kind == 'apply':
                if self.db.execute('SELECT 1 FROM blocked_apply WHERE workspace=?', (workspace,)).fetchone():
                    return None
                if self.db.execute("SELECT 1 FROM tasks WHERE workspace=? AND status='applying'", (workspace,)).fetchone():
                    return None
            state = 'queued' if kind == 'work' else 'apply_queued'
            # Least recently served owner; FIFO within that owner. No fixed agent count.
            if kind == 'work':
                r = self.db.execute('''SELECT t.* FROM tasks t LEFT JOIN fairness f ON t.owner=f.owner
                    WHERE t.status='queued' AND EXISTS (
                      SELECT 1 FROM workers w WHERE w.workspace=t.workspace AND w.expires>?
                      AND NOT EXISTS (SELECT 1 FROM tasks busy WHERE busy.worker=w.id AND busy.status IN ('running','cancelling')))
                    ORDER BY COALESCE(f.served,0), t.created LIMIT 1''', (time.time(),)).fetchone()
            else:
                r = self.db.execute('SELECT * FROM tasks WHERE workspace=? AND status=? ORDER BY apply_requested, created LIMIT 1', (workspace,state)).fetchone()
            if not r or r['workspace'] != workspace:
                return None
            lease = uuid.uuid4().hex
            self.db.execute('UPDATE tasks SET worker=?,lease=?,expires=? WHERE id=?', (worker, lease, time.time()+self.lease_seconds, r['id']))
            if kind == 'work':
                self.db.execute('INSERT OR REPLACE INTO fairness VALUES (?,?)', (r['owner'], time.time()))
            self._state(r['id'], 'running' if kind == 'work' else 'applying')
            return {**dict(r), 'lease': lease, 'contract': json.loads(r['contract']), 'lease_seconds': self.lease_seconds}

    def check_lease(self, workspace, task_id, lease):
        with self.transaction():
            self.expire()
            r = self._row(task_id, workspace)
            if r['lease'] != lease or r['status'] not in ('running', 'cancelling', 'applying'):
                raise Conflict('Stale or inactive lease')
            return {'cancel': r['status'] == 'cancelling'}

    def heartbeat(self, workspace, task_id, lease):
        with self.transaction():
            result = self.check_lease(workspace, task_id, lease)
            self.db.execute('UPDATE tasks SET expires=? WHERE id=?', (time.time()+self.lease_seconds, task_id))
            return result

    def finish(self, workspace, task_id, lease, status, result):
        if status not in TERMINAL or not isinstance(result, dict) or len(json.dumps(result)) > 60000:
            raise ValueError('Invalid task completion')
        with self.transaction():
            self.heartbeat(workspace, task_id, lease)
            r = self._row(task_id, workspace)
            if r['status'] == 'cancelling':
                status = 'cancelled'
            self._state(task_id, status, result)
            self.db.execute('UPDATE tasks SET lease=NULL,expires=NULL WHERE id=?', (task_id,))
            return {'status': status}

    def summary(self, workspace, task_id, wait_seconds=0):
        end = time.monotonic() + min(25, max(0, int(wait_seconds)))
        while True:
            with self.transaction():
                self.expire()
                r = self._row(task_id, workspace)
                if r['status'] not in ('queued','running','cancelling','apply_queued','applying') or time.monotonic() >= end:
                    result = json.loads(r['result']) if r['result'] else {}
                    return {**result, 'task_id': task_id, 'status': r['status'], 'revision': r['revision'],
                            'owner': r['owner'], 'base_at_submission': r['base'],
                            'depth_selection': {k:json.loads(r['contract']).get(k) for k in ('depth','reasoning_effort','depth_reason','max_output_tokens')}}
            time.sleep(.1)

    def cancel(self, workspace, task_id):
        with self.transaction():
            r = self._row(task_id, workspace)
            if r['status'] == 'applying':
                raise Conflict('Apply already started; inspect outcome before another operation')
            if r['status'] in ('queued','apply_queued'):
                self._state(task_id, 'cancelled')
            elif r['status'] == 'running':
                self._state(task_id, 'cancelling')
            return self.summary(workspace, task_id)

    def apply(self, workspace, task_id, reviewed_patch_sha256):
        with self.transaction():
            r = self._row(task_id, workspace)
            if r['status'] in ('apply_queued','applying','applied') and r['approved_hash'] == reviewed_patch_sha256:
                return self.summary(workspace, task_id)
            result = json.loads(r['result'] or '{}')
            if r['status'] != 'review_ready' or not result.get('changed_files') or result.get('patch_sha256') != reviewed_patch_sha256:
                raise Conflict('A review-ready patch and its exact reviewed hash are required')
            if self.db.execute('SELECT 1 FROM blocked_apply WHERE workspace=?', (workspace,)).fetchone():
                raise Conflict('Workspace apply is quarantined after an interrupted apply; inspect manually')
            self.db.execute('UPDATE tasks SET approved_hash=?,apply_requested=? WHERE id=?', (reviewed_patch_sha256, time.time(), task_id))
            self._state(task_id, 'apply_queued')
            return self.summary(workspace, task_id)

    def events(self, workspace, after=0, wait_seconds=0):
        end = time.monotonic() + min(15,max(0,int(wait_seconds)))
        while True:
            with self.transaction():
                rows = self.db.execute('SELECT e.seq,e.task_id,e.status,t.contract FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.workspace=? AND e.seq>? ORDER BY e.seq LIMIT 100', (workspace,int(after))).fetchall()
                if rows or time.monotonic() >= end:
                    return {'events': [{**{k:r[k] for k in ('seq','task_id','status')}, 'depth_selection':{k:json.loads(r['contract']).get(k) for k in ('depth','reasoning_effort','depth_reason')}} for r in rows], 'cursor': rows[-1]['seq'] if rows else int(after)}
            time.sleep(.2)

    def health(self):
        with self.transaction():
            self.expire()
            counts = {r[0]: r[1] for r in self.db.execute('SELECT status,count(*) FROM tasks GROUP BY status')}
            return {'counts': counts, 'worker_limit': self.max_workers, 'queue_capacity': self.capacity,
                    'inference_blocked': self.get_meta('inference_blocked')}

    def close(self): self.db.close()


class InferenceGate:
    """Fair owner rotation and a hard bound on upstream HTTP calls, independent of Workers."""
    def __init__(self, store, upstream, limit=1, waiting_limit=1000):
        if limit < 1:
            raise ValueError('Inference limit must be positive')
        self.store, self.upstream, self.limit, self.waiting_limit = store, upstream, limit, waiting_limit
        self.condition = threading.Condition()
        self.pending, self.served = [], {}
        self.active = 0

    def run(self, workspace, task_id, lease, messages, tools):
        r = self.store.check_lease(workspace, task_id, lease)
        if r['cancel']:
            raise Conflict('Task cancelled')
        with self.store.lock:
            task = self.store._row(task_id, workspace)
            owner = task['owner']
            contract = json.loads(task['contract'])
        options=resolve_depth({}, **{k:contract[k] for k in ('depth','reasoning_effort','depth_reason','max_output_tokens') if k in contract})
        if hasattr(self.upstream, 'validate_options'):self.upstream.validate_options(options)
        ticket = {'id': uuid.uuid4().hex, 'owner': owner, 'at': time.monotonic()}
        deadline = time.monotonic() + 600
        with self.condition:
            if len(self.pending) >= self.waiting_limit:
                raise Conflict('Inference waiting queue is full')
            self.pending.append(ticket)
            try:
                while True:
                    blocked = self.store.get_meta('inference_blocked')
                    if blocked:
                        raise Conflict('Inference paused: ' + blocked)
                    if self.store.check_lease(workspace, task_id, lease)['cancel']:
                        raise Conflict('Task cancelled')
                    winner = min(self.pending, key=lambda t: (self.served.get(t['owner'], 0), t['at']))
                    if winner is ticket and self.active < self.limit:
                        self.pending.remove(ticket)
                        self.active += 1
                        self.store.set_meta('inference_active', self.active)
                        self.served[owner] = time.monotonic()
                        break
                    if time.monotonic() > deadline:
                        raise Conflict('Inference wait budget exceeded')
                    self.condition.wait(.2)
            except Exception:
                if ticket in self.pending: self.pending.remove(ticket)
                self.condition.notify_all()
                raise
        try:
            if hasattr(self.upstream, 'chat_with_options'):
                return self.upstream.chat_with_options(messages, tools, options)
            return self.upstream.chat(messages, tools)
        except Exception:
            # Upstream might still compute after an HTTP timeout. Do not oversubscribe it.
            self.store.set_meta('inference_blocked', 'Upstream request failed with uncertain completion; verify idle and reset.')
            raise RuntimeError('Upstream inference failed; admission paused pending operator check') from None
        finally:
            with self.condition:
                self.active -= 1
                self.store.set_meta('inference_active', self.active)
                self.condition.notify_all()


def make_server(address, store, gate, token):
    if len(token) < 24:
        raise ValueError('Coordinator token must contain at least 24 characters')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token):
                self.send_response(401); self.end_headers(); return
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 500000:
                    raise ValueError('Request too large or empty')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data,dict): raise ValueError('Expected object')
                route = self.path.removeprefix('/v1/')
                if route == 'health': result = store.health()
                elif route == 'models': result = gate.upstream.health()
                elif route == 'infer': result = gate.run(**data)
                elif route == 'reset-inference':
                    if data.get('confirmed_idle') is not True or gate.active:
                        raise Conflict('Verify upstream is idle; active requests cannot be reset')
                    store.set_meta('inference_blocked',''); result={'reset':True}
                elif route == 'reset-apply':
                    if data.get('confirmed_inspected') is not True or not isinstance(data.get('workspace'),str):
                        raise Conflict('Inspect repository and interrupted apply outcome first')
                    with store.transaction():
                        if store.db.execute("SELECT 1 FROM tasks WHERE workspace=? AND status='applying'",(data['workspace'],)).fetchone():
                            raise Conflict('Apply is still running')
                        store.db.execute('DELETE FROM blocked_apply WHERE workspace=?',(data['workspace'],))
                    result={'reset':True}
                else:
                    methods = {'submit':store.submit,'claim':store.claim,'heartbeat':store.heartbeat,
                               'finish':store.finish,'summary':store.summary,'cancel':store.cancel,
                               'apply':store.apply,'events':store.events}
                    if route not in methods: raise ValueError('Unknown route')
                    result = methods[route](**data)
                status, response = 200, {'result': result}
            except (ValueError, TypeError) as e:
                status, response = 409 if isinstance(e,Conflict) else 400, {'error':str(e)[:500]}
            except Exception:
                status, response = 503, {'error':'Coordinator operation failed'}
            raw = json.dumps(response).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128
    return Server(address, Handler)


def main():
    p=argparse.ArgumentParser(description='Shared Strata-Coder coordinator; loopback-only, access through SSH')
    p.add_argument('--state',required=True);p.add_argument('--port',type=int,default=8091)
    p.add_argument('--worker-limit',type=int,default=4);p.add_argument('--inference-limit',type=int,default=1)
    p.add_argument('--queue-capacity',type=int,default=1000);p.add_argument('--per-owner',type=int,default=100)
    p.add_argument('--strata-url',default='http://127.0.0.1:8080/v1');p.add_argument('--model',default='')
    p.add_argument('--reasoning-support',choices=['unverified','supported','unsupported'],default='unverified',help='Operator-verified model capability; never inferred from HTTP success')
    args=p.parse_args();os.umask(0o077);folder=Path(args.state).expanduser();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    # One coordinator owns a DB. Never run two admission gates against one GPU.
    from .locking import exclusive_lock
    lock=exclusive_lock(folder/'coordinator.lock')
    token_path=folder/'token'
    if not token_path.exists():
        fd=os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32))
    token=token_path.read_text().strip()
    store=Store(folder/'queue.sqlite3',args.worker_limit,args.queue_capacity,args.per_owner)
    upstream=Transport({'mode':'direct','base_url':args.strata_url,'model':args.model,'reasoning_support':args.reasoning_support})
    server=make_server(('127.0.0.1',args.port),store,InferenceGate(store,upstream,args.inference_limit),token)
    print(f'Coordinator ready on 127.0.0.1:{server.server_port}; token file: {token_path}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();upstream.close();lock.close()


if __name__=='__main__':main()
