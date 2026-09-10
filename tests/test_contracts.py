import copy
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parent.parent
MODEL = runpy.run_path(str(ROOT / 'scripts/check-contracts.py'))

class ContractsTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'examples/pilot.json').read_text())

    def test_valid_fork_and_join(self):
        self.assertEqual(MODEL['validate'](self.data), 5)

    def test_cycle_and_missing_dependency_rejected(self):
        for predecessor in ('SQUAD-005', 'MISSING'):
            with self.subTest(predecessor=predecessor):
                data = copy.deepcopy(self.data)
                data['tasks'][0]['depends_on'] = [predecessor]
                with self.assertRaises(ValueError):
                    MODEL['validate'](data)

    def test_changed_authority_invalidates_hash(self):
        self.data['tasks'][0]['contract']['authority']['allowed'] = 'Deploy'
        with self.assertRaisesRegex(ValueError, 'Stale contract hash'):
            MODEL['validate'](self.data)

    def test_prior_evidence_invalid_after_revision(self):
        task = self.data['tasks'][0]
        task['evidence'] = [{'revision': 1, 'criteria_hash': task['criteria_hash'],
                             'reference': 'synthetic/check', 'verifier': 'probe', 'result': 'pass'}]
        task['contract']['revision'] = 2
        task['criteria_hash'] = MODEL['digest'](task['contract'])
        with self.assertRaisesRegex(ValueError, 'Stale evidence'):
            MODEL['validate'](self.data)

    def test_agreement_requires_receipt(self):
        task = self.data['tasks'][0]
        task['contract']['decision']['status'] = 'agreed'
        task['criteria_hash'] = MODEL['digest'](task['contract'])
        with self.assertRaisesRegex(ValueError, 'decision evidence'):
            MODEL['validate'](self.data)

if __name__ == '__main__':
    unittest.main()
