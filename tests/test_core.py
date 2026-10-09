import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from strata_coder.core import Manager, digest, git
from strata_coder.__main__ import dispatch
from strata_coder.transport import Transport


class FakeTransport:
    def __init__(self, responses=()): self.responses = iter(responses)
    def chat(self, messages, tools): return next(self.responses)
    def health(self): return {'models': ['test'], 'mode': 'direct'}
    def close(self): pass


def response(content=None, calls=(), finish='stop'):
    return {'choices': [{'message': {'role': 'assistant', 'content': content,
             'tool_calls': [{'id': str(i), 'type': 'function', 'function': {'name': n, 'arguments': json.dumps(a)}}
                            for i, (n, a) in enumerate(calls)]}, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'a.py').write_text('value = 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'initial')
        self.manager = None

    def tearDown(self):
        if self.manager: self.manager.close()
        self.tmp.cleanup()

    def manager_for(self, responses=(), config=None):
        self.manager = Manager(self.repo, self.root / 'state', config or {}, FakeTransport(responses))
        return self.manager

    def submit_done(self, m, **kwargs):
        tid = m.submit('Fix value', **kwargs)['task_id']
        m.thread.join(10)
        self.assertFalse(m.thread.is_alive())
        return tid, m.get(tid)

    def edit_responses(self):
        return [response(calls=[('write_file', {'path': 'a.py', 'content': 'value = 2\n',
                    'expected_sha256': digest(b'value = 1\n')})]), response('Changed a.py; please review.')]

    def test_edit_isolated_and_reviewed_apply(self):
        m = self.manager_for(self.edit_responses(), {'tests': {'unit': [sys.executable, '-c', 'import a; assert a.value == 2']}})
        tid, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['value becomes 2'], test_ids=['unit'])
        self.assertEqual(t['status'], 'review_ready')
        self.assertEqual((self.repo / 'a.py').read_text(), 'value = 1\n')
        self.assertEqual(t['final_tests'][0]['exit_code'], 0)
        with self.assertRaises(ValueError): m.apply(tid, 'wrong')
        m.apply(tid, t['patch_sha256'])
        self.assertEqual((self.repo / 'a.py').read_text(), 'value = 2\n')
        self.assertEqual(git(self.repo, 'log', '--format=%s', '-1'), 'initial')

    def test_dirty_repo_refused(self):
        m = self.manager_for()
        (self.repo / 'untracked').write_text('keep')
        with self.assertRaises(ValueError): m.submit('research')
        self.assertEqual((self.repo / 'untracked').read_text(), 'keep')

    def test_research_cannot_write(self):
        m = self.manager_for([response('Research complete')])
        _, t = self.submit_done(m)
        with self.assertRaises(ValueError): m.execute(t, 'write_file', {'path': 'a.py', 'content': 'bad', 'expected_sha256': digest(b'value = 1\n')})
        self.assertEqual(t['changed_files'], [])

    def test_traversal_symlink_secrets_and_scope(self):
        m = self.manager_for([response('Done')])
        _, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'])
        for name in ['../outside', '/etc/passwd', '.git/config', '.env', 'x/.env.local', 'key.pem', 'C:\\a']:
            with self.assertRaises(ValueError, msg=name): m.safe_path(t, name)
        (Path(t['worktree']) / 'link').symlink_to(self.root)
        with self.assertRaises(ValueError): m.safe_path(t, 'link/file')
        with self.assertRaises(ValueError): m.safe_path(t, 'other.py', write=True)

    def test_stale_hash(self):
        m = self.manager_for([response('Done')])
        _, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'])
        with self.assertRaises(ValueError): m.execute(t, 'write_file', {'path': 'a.py', 'content': 'bad', 'expected_sha256': 'old'})

    def test_dirty_apply_preserves_user_work(self):
        m = self.manager_for(self.edit_responses())
        tid, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'])
        (self.repo / 'a.py').write_text('user edit')
        with self.assertRaises(ValueError): m.apply(tid, t['patch_sha256'])
        self.assertEqual((self.repo / 'a.py').read_text(), 'user edit')

    def test_changed_base_refused(self):
        m = self.manager_for(self.edit_responses())
        tid, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'])
        git(self.repo, 'commit', '--allow-empty', '-qm', 'other commit')
        with self.assertRaises(ValueError): m.apply(tid, t['patch_sha256'])

    def test_failed_final_test_blocks_apply(self):
        m = self.manager_for(self.edit_responses(), {'tests': {'fail': [sys.executable, '-c', 'raise SystemExit(3)']}})
        tid, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'], test_ids=['fail'])
        self.assertEqual(t['status'], 'needs_supervisor')
        self.assertEqual(t['final_tests'][0]['exit_code'], 3)
        with self.assertRaises(ValueError): m.apply(tid, t['patch_sha256'])

    def test_timeout_and_no_arbitrary_command(self):
        m = self.manager_for([response('done')], {'test_timeout': 1, 'tests': {'sleep': [sys.executable, '-c', 'import time; time.sleep(10)']}})
        _, t = self.submit_done(m, mode='edit', allowed_paths=['a.py'], acceptance=['test'], test_ids=['sleep'])
        self.assertEqual(t['final_tests'][0]['reason'], 'timeout')
        with self.assertRaises(ValueError): m.execute(t, 'run_test', {'test_id': 'shell'})

    def test_evidence_pagination_and_unknown(self):
        m = self.manager_for([response('done')])
        tid, t = self.submit_done(m)
        eid = m.evidence(t, 'long', 'a' * 30000)
        self.assertEqual(len(m.get_evidence(tid, eid)['content_untrusted']), 4000)
        with self.assertRaises(ValueError): m.get_evidence(tid, '../task', limit=10)
        with self.assertRaises(ValueError): m.get_evidence(tid, eid, limit=20000)

    def test_model_truncation_not_success(self):
        m = self.manager_for([response('partial', finish='length')])
        _, t = self.submit_done(m)
        self.assertEqual(t['status'], 'needs_supervisor')

    def test_cancel_prevents_tools_after_inference(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeTransport):
            def chat(self, messages, tools):
                entered.set(); release.wait(3)
                return response(calls=[('write_file', {'path': 'a.py', 'content': 'bad', 'expected_sha256': digest(b'value = 1\n')})])
        m = self.manager_for()
        m.transport = Blocking()
        tid = m.submit('edit', mode='edit', allowed_paths=['a.py'], acceptance=['test'])['task_id']
        self.assertTrue(entered.wait(2))
        with self.assertRaises(ValueError): m.submit('second')
        m.cancel(tid); release.set(); m.thread.join(5)
        self.assertEqual(m.get(tid)['status'], 'cancelled')
        self.assertEqual((Path(m.get(tid)['worktree']) / 'a.py').read_text(), 'value = 1\n')

    def test_restart_retains_evidence(self):
        m = self.manager_for([response('done')])
        tid, t = self.submit_done(m)
        other = Manager(self.repo, self.root / 'state', {}, FakeTransport())
        self.assertEqual(other.summary(tid)['status'], 'review_ready')
        other.close()

    def test_mcp_handshake_and_schema(self):
        m = self.manager_for()
        self.assertEqual(dispatch(m, 'initialize', {'protocolVersion': '2025-06-18'})['serverInfo']['name'], 'strata-coder')
        self.assertEqual(len(dispatch(m, 'tools/list', {})['tools']), 6)
        with self.assertRaises(ValueError): dispatch(m, 'tools/call', {'name': 'strata_apply', 'arguments': {'command': 'rm'}})

    def test_direct_remote_requires_https_and_key(self):
        with self.assertRaises(ValueError): Transport({'mode': 'direct', 'base_url': 'http://10.1.1.1:8080/v1'}).connect()
        with self.assertRaises(ValueError): Transport({'ssh_host': '-oProxyCommand=bad'}).connect()

    def test_new_file_patch(self):
        m = self.manager_for([response(calls=[('write_file', {'path': 'b.py', 'content': 'x = 3\n', 'expected_sha256': ''})]), response('new')])
        tid, t = self.submit_done(m, mode='edit', allowed_paths=['b.py'], acceptance=['add b'])
        self.assertEqual(t['status'], 'review_ready')
        m.apply(tid, t['patch_sha256'])
        self.assertEqual((self.repo / 'b.py').read_text(), 'x = 3\n')


if __name__ == '__main__': unittest.main()
