import unittest
import test_core as fixtures
from strata_coder.code_context import retrieve


class ContextTests(unittest.TestCase):
    def test_overview_then_decorated_unicode_method(self):
        source = 'import something\nclass C:\n    @decorator\n    async def café(self):\n        return "日本語"\n\ndef other():\n    return 0\n'
        overview = retrieve(source)
        self.assertNotIn('content', overview)
        self.assertEqual([x['symbol'] for x in overview['symbols']], ['C', 'C.café', 'other'])
        body = retrieve(source, symbol='C.café', expected_sha256=overview['sha256'])
        self.assertTrue(body['content'].startswith('    @decorator'))
        self.assertNotIn('other', body['content'])
        self.assertIn('日本語', body['content'])
        with self.assertRaisesRegex(ValueError, 'Stale'):
            retrieve(source + '\n', symbol='C.café', expected_sha256=overview['sha256'])

    def test_body_and_overview_pagination_have_no_gaps(self):
        source = '\n'.join(f'def f{i}():\n    return {i}' for i in range(60)) + '\n'
        first = retrieve(source)
        self.assertEqual(first['next_offset'], 50)
        self.assertEqual(len(retrieve(source, offset=50)['symbols']), 10)
        large = 'def f():\n' + '    # long comment\n' * 800 + '    return 1\n'
        pieces = []; offset = 0
        while offset is not None:
            page = retrieve(large, symbol='f', offset=offset)
            pieces.append(page['content']); offset = page['next_offset']
        self.assertEqual(''.join(pieces), large)

    def test_duplicate_definitions_and_invalid_python_not_guessed(self):
        for source, symbol in [('def f(): pass\ndef f(): pass\n', 'f'), ('not python !', '')]:
            with self.assertRaises(ValueError):
                retrieve(source, symbol=symbol)


class ContextBoundaryTests(unittest.TestCase):
    setUp = fixtures.CoreTests.setUp
    tearDown = fixtures.CoreTests.tearDown
    manager_for = fixtures.CoreTests.manager_for
    submit_done = fixtures.CoreTests.submit_done

    def test_research_can_read_symbols_but_not_secret_or_external_paths(self):
        m = self.manager_for([fixtures.response('done')])
        _, task = self.submit_done(m)
        path = __import__('pathlib').Path(task['worktree'])
        (path / 'a.py').write_text('def add(a, b):\n    return a+b\n')
        response = m.execute(task, 'code_context', {'path':'a.py'})
        self.assertEqual(response['symbols'][0]['symbol'], 'add')
        for name in ('../a.py', '.env', '/tmp/out.py'):
            with self.assertRaises(ValueError):
                m.execute(task, 'code_context', {'path':name})
        (path/'link.py').symlink_to(path/'a.py')
        with self.assertRaises(ValueError):
            m.execute(task, 'code_context', {'path':'link.py'})

    def test_context_hash_matches_raw_crlf_file(self):
        import hashlib
        from pathlib import Path
        m = self.manager_for([fixtures.response('done')])
        _, task = self.submit_done(m)
        raw = b'def f():\r\n    return 1\r\n'
        (Path(task['worktree'])/'a.py').write_bytes(raw)
        value = m.execute(task, 'code_context', {'path':'a.py', 'symbol':'f'})
        self.assertEqual(value['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['content'].encode(), raw)
