import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('policy_evaluation',Path(__file__).resolve().parents[1]/'tools/evaluate_policy.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PolicyTests(unittest.TestCase):
    def test_policy_binding_and_bounds(self):
        value=dict(ticket='bound',strategy='Keep public signatures; fix validation before paging',
            constraints=['Only the three implementation files'],escalate='Stop if broader API changes are needed',depth='medium')
        self.assertEqual(module.valid_policy(value,'bound'),value)
        for bad in ({**value,'ticket':'stale'},{**value,'constraints':[]},
                    {**value,'strategy':'x'*401},{**value,'depth':'auto'},
                    {**value,'command':'rm -rf .'}):
            with self.assertRaises(ValueError):module.valid_policy(bad,'bound')
