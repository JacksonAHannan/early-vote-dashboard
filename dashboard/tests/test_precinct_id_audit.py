"""Admission diagnostics use production native identity rules, never SOS/VTD guesses."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / 'sources/precinct-expansion/discovery/audit_precinct_ids.py'
SPEC = importlib.util.spec_from_file_location('precinct_id_audit', PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PrecinctIdAuditTests(unittest.TestCase):
    def test_henderson_alphanumeric_native_padding_matches_production(self):
        native = audit.native_universe([{'CNTY': 213, 'PREC': '01TC'}], {213})
        self.assertEqual(native, {213: {'1TC'}})
        result = audit.audit_counts([{'counts': {'1TC': 25}}], native[213])
        self.assertEqual(result['mapped_share'], 1)
        self.assertEqual(result['unmapped_votes'], 0)

    def test_official_fips_selects_maverick_and_mcmullen_without_sos_id_join(self):
        reference = {'maverick': {'fips': '48323'}, 'mcmullen': {'fips': '48311'}}
        fips = audit.official_fips(reference, reference)
        self.assertEqual(fips, {'maverick': 323, 'mcmullen': 311})
        records = [{'CNTY': 323, 'cntykey': 162, 'PREC': '001A'},
                   {'CNTY': 311, 'cntykey': 156, 'PREC': '0004'},
                   {'CNTY': 317, 'cntykey': 159, 'PREC': 'WRONG'}]
        native = audit.native_universe(records, set(fips.values()))
        self.assertEqual(native[323], {'1A'})
        self.assertEqual(native[311], {'4'})
        self.assertEqual(audit.audit_counts([{'counts': {'1A': 10}}], native[fips['maverick']])['mapped_share'], 1)
        self.assertEqual(audit.audit_counts([{'counts': {'4': 3}}], native[fips['mcmullen']])['mapped_share'], 1)

    def test_normalization_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate normalized native precinct 1TC'):
            audit.native_universe([{'CNTY': 213, 'PREC': '01TC'},
                                   {'CNTY': 213, 'PREC': '1TC'}], {213})

    def test_same_precinct_label_in_different_counties_does_not_collide(self):
        self.assertEqual(audit.native_universe([{'CNTY': 213, 'PREC': '0001'},
                                                {'CNTY': 311, 'PREC': '0001'}], {213, 311}),
                         {213: {'1'}, 311: {'1'}})

    def test_cntykey_alone_cannot_substitute_for_official_fips(self):
        with self.assertRaisesRegex(ValueError, 'requires official CNTY'):
            audit.native_universe([{'cntykey': 162, 'PREC': '1A'}], {323})

    def test_ambiguous_county_fips_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'share one official FIPS'):
            audit.official_fips(['a', 'b'], {'a': {'fips': '48323'}, 'b': {'fips': '48323'}})

    def test_unknown_observed_or_vtd_style_labels_are_not_rewritten(self):
        days = [{'counts': {'108A': 5, '0108A': 2, 'UNASSIGNED': 1}}]
        original = json.loads(json.dumps(days))
        result = audit.audit_counts(days, {'108A'})
        self.assertEqual(days, original)
        self.assertEqual(result['unmapped_precincts'], {'0108A': 2, 'UNASSIGNED': 1})
        self.assertEqual(result['observed_votes'] - result['unmapped_votes'], 5)

    def test_empty_observations_are_undefined_coverage_not_zero_or_complete(self):
        result = audit.audit_counts([{'counts': {}}], {'1'})
        self.assertIsNone(result['mapped_share'])
        self.assertEqual(result['observed_votes'], 0)

    def test_all_mode_needs_no_probe_file_and_only_writes_requested_diagnostic(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'dashboard/data'
            data.mkdir(parents=True)
            (data / 'statewide.json').write_text(json.dumps({'counties': [
                {'id': 'maverick', 'name': 'Maverick', 'state_id': 159},
                {'id': 'mcmullen', 'name': 'McMullen', 'state_id': 162}]}))
            (data / 'county-reference.json').write_text(json.dumps({'counties': {
                'maverick': {'fips': '48323'}, 'mcmullen': {'fips': '48311'}}}))
            originals = {}
            for county, precinct in [('maverick', '1A'), ('mcmullen', '4')]:
                path = data / f'cache/{county}/2024-series.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps([{'counts': {precinct: 9}}]))
                originals[path] = path.read_bytes()
            output = root / 'analysis/result.json'
            native = {2024: {323: {'1A'}, 311: {'4'}}, 2026: {323: {'1A'}, 311: {'4'}}}
            with patch.object(audit, 'load_universes', return_value=native) as load, contextlib.redirect_stdout(io.StringIO()):
                result = audit.main(['--all', '--output', str(output)], root=root)
            load.assert_called_once_with(root, {323, 311})
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual({r['county']: r['years']['2024']['mapped_share'] for r in result},
                             {'maverick': 1, 'mcmullen': 1})
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)
            self.assertFalse((root / 'sources').exists())


if __name__ == '__main__':
    unittest.main()
