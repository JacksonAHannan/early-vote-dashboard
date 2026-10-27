import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dallas_identity', Path(__file__).with_name('dallas_identity.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ExactIdentityRecovery(unittest.TestCase):
    def test_unique_identity_uses_explicit_same_date_native_target(self):
        found, audit = m.resolve_blank_precincts(['synthetic-a'], {'synthetic-a': 1},
                                              [('synthetic-a', '100')], {'100'})
        self.assertEqual(found, {'synthetic-a': '100'})
        self.assertEqual(audit, {'exact_unique_identity_assigned': 1})

    def test_known_precinct_or_other_date_reuse_cannot_reassign_blank_row(self):
        found, audit = m.resolve_blank_precincts(['synthetic-a'], {'synthetic-a': 2},
                                              [('synthetic-a', '100')], {'100'})
        self.assertEqual(found, {})
        self.assertEqual(audit, {'native_identifier_missing_or_nonunique': 1})

    def test_duplicate_sos_rows_fail_even_when_target_agrees(self):
        found, _ = m.resolve_blank_precincts(['synthetic-a'], {'synthetic-a': 1},
                                            [('synthetic-a', '100'), ('synthetic-a', '100')], {'100'})
        self.assertEqual(found, {})

    def test_conflicting_foreign_and_missing_sos_targets_stay_unknown(self):
        for pairs in [[('synthetic-a', '100'), ('synthetic-a', '200')],
                      [('synthetic-a', 'UNKNOWN')], []]:
            with self.subTest(pairs=pairs):
                found, _ = m.resolve_blank_precincts(['synthetic-a'], {'synthetic-a': 1}, pairs, {'100'})
                self.assertEqual(found, {})

    def test_partial_enrichment_conserves_total_and_original_known_counts(self):
        self.assertEqual(m.apply_aggregate_counts({'100': 8, 'UNASSIGNED': 3},
                                                  {'synthetic-a': '100', 'synthetic-b': '200'}, 3),
                         {'100': 9, '200': 1, 'UNASSIGNED': 1})

    def test_disagreement_with_published_unknown_aggregate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            m.apply_aggregate_counts({'100': 8, 'UNASSIGNED': 2}, {'synthetic-a': '100'}, 3)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            m.apply_aggregate_counts({'100': 8, 'UNASSIGNED': 1}, {'synthetic-a': '100', 'synthetic-b': '100'}, 1)


if __name__ == '__main__':
    unittest.main()
