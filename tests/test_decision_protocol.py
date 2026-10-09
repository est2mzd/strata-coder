import unittest
import test_decision as fixtures
from strata_coder.decision_protocol import packet, prompt, expand


class CompactProtocolTests(unittest.TestCase):
    setUp = fixtures.DecisionTests.setUp
    tearDown = fixtures.DecisionTests.tearDown

    def prepare(self, count=1):
        self.contract['allow_apply'] = False
        contracts = [dict(self.contract, objective=f'Fix a.py case {n}') for n in range(count)]
        self.b.prepare(contracts)
        return {'ticket': packet(self.b)['ticket'],
                'decisions': [[n, 'run', 'low'] for n in range(count)]}

    def test_shared_fields_and_acceptance_preserved(self):
        self.prepare(3)
        p = packet(self.b)
        self.assertEqual(p['common']['background'], self.contract['background'])
        self.assertTrue(all('background' not in item for item in p['items']))
        self.assertTrue(all(item['acceptance'] == self.contract['acceptance'] for item in p['items']))
        self.assertEqual(len(p['items']), 3)

    def test_numbered_rows_resolve_correct_missions_even_reordered(self):
        response = self.prepare(3)
        response['decisions'].reverse()
        decisions = expand(self.b, response)
        self.assertEqual([d['id'] for d in decisions], list(reversed(self.b.data['missions'])))
        self.assertEqual(self.m.calls, [])

    def test_ticket_rejects_changed_contract_and_consumed_state(self):
        response = self.prepare()
        mission = next(iter(self.b.data['missions'].values()))
        mission['contract']['acceptance'].append('additional requirement')
        with self.assertRaisesRegex(ValueError, 'ticket'):
            expand(self.b, response)
        mission['status'] = 'verified_not_applied'
        with self.assertRaises(ValueError):
            expand(self.b, response)
        self.assertEqual(self.m.calls, [])

    def test_missing_duplicate_boolean_and_foreign_rows_rejected(self):
        response = self.prepare(2)
        for rows in ([[0, 'run', 'low']], [[0, 'stop'], [0, 'stop']],
                     [[True, 'stop'], [0, 'stop']], [[0, 'stop'], [2, 'stop']]):
            with self.assertRaises(ValueError):
                expand(self.b, dict(response, decisions=rows))
        with self.assertRaises(ValueError):
            expand(self.b, dict(response, ticket='foreign'))
        self.assertEqual(self.m.calls, [])

    def test_fixed_depth_and_instruction_bounds_enforced(self):
        self.contract['depth'] = 'high'
        response = self.prepare()
        with self.assertRaises(ValueError):
            expand(self.b, response)
        response['decisions'] = [[0, 'inspect', 'Check edge cases']]
        self.assertEqual(expand(self.b, response)[0]['instruction'], 'Check edge cases')
        response['decisions'] = [[0, 'inspect', 'x' * 121]]
        with self.assertRaises(ValueError):
            expand(self.b, response)

    def test_oversized_acceptance_is_blocked_without_truncation(self):
        self.prepare()
        next(iter(self.b.data['missions'].values()))['contract']['acceptance'] = ['x' * 24001]
        with self.assertRaisesRegex(ValueError, 'never truncate'):
            prompt(self.b)
        self.assertEqual(self.m.calls, [])

    def test_cursor_wire_saved_and_expanded(self):
        from test_decision import CursorBoundaryTests
        from unittest.mock import patch
        from types import SimpleNamespace
        import json
        response = self.prepare()
        def fake_run(*args, **kw):
            kw['stdout'].write(json.dumps({'type':'result', 'result':json.dumps(response),
                'usage':dict(inputTokens=100, outputTokens=30, cacheReadTokens=0, cacheWriteTokens=0)}) + '\n')
            kw['stdout'].flush()
            return SimpleNamespace(returncode=0)
        opts = SimpleNamespace(step=1, baseline_tokens=2000, reserve_tokens=150,
            measure_over_budget=False, cli='/fake', model='fixture')
        with patch('subprocess.run', fake_run):
            result = CursorBoundaryTests.command(self).cursor_decide(self.b, opts)
        self.assertTrue(result['within_budget'])
        self.assertEqual(result['decisions'][0]['action'], 'run')
        self.assertEqual(self.b.data['cursor_usage'][0]['wire_response'], response)
