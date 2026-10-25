import csv
import importlib.util
import io
import json
from pathlib import Path
import unittest
import tempfile
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts/states'

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

va = module('virginia')
nv = module('nevada')

def encoded(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()

class VirginiaNevadaTests(unittest.TestCase):
    def test_virginia_snapshot_dates_and_latest_revision(self):
        rows = [{'FILEDATE': '2026-10-24T05:00:01', 'COUNTABLE': '100', 'MAIL_IN': '40', 'ON_MACHINE': '60'}, {'FILEDATE': '2026-10-24T06:00:01', 'COUNTABLE': '110', 'MAIL_IN': '42', 'ON_MACHINE': '68'}]
        parsed = va.parse_series(encoded(rows), 2026)
        self.assertEqual(parsed, {'2026-10-23': {'total': 110, 'mail': 42, 'in_person': 68}})
        self.assertEqual(va.timestamp('24-Oct-2024 06:00:01').year, 2024)

    def test_clark_mail_excludes_undelivered_deduplicates_and_keeps_pending(self):
        rows = [{'IDNUMBER': '1', 'VOTER_NAME': 'PRIVATE PERSON', 'PRECINCT': '1001', 'VOTER_REG_PARTY': 'DEM', 'BALLOT_RECEIVE_DATE': '10/23/2026', 'RETURN_CODE': 'ACCEPTED'}, {'IDNUMBER': '2', 'VOTER_NAME': 'PRIVATE PERSON', 'PRECINCT': '1001', 'VOTER_REG_PARTY': 'NP ', 'BALLOT_RECEIVE_DATE': '10/23/2026', 'RETURN_CODE': 'SIGCURENEEDED'}, {'IDNUMBER': '3', 'VOTER_NAME': 'PRIVATE PERSON', 'PRECINCT': '1001', 'VOTER_REG_PARTY': 'REP', 'BALLOT_RECEIVE_DATE': '10/23/2026', 'RETURN_CODE': 'UNDELIVERABLE'}]
        data = nv.aggregate(encoded(rows + [rows[0]]), 'clark_mail', 2026)
        county = next(r for r in data['rows'] if r['precinct'] is None)
        self.assertEqual(county['votes'], 2)
        self.assertEqual(county['breakdowns']['party'], {'DEM': 1, 'NP': 1})
        self.assertEqual(data['duplicate_rows'], 1)
        self.assertNotIn('PRIVATE PERSON', json.dumps(data))
        self.assertNotIn('IDNUMBER', json.dumps(data))

    def test_general_ballot_party_never_inferred_as_registration(self):
        rows = [{'IDNUMBER': '1', 'NAME': 'PRIVATE PERSON', 'PRECINCT': '1001', 'PARTY': 'NA', 'ACTIVITY DATE': '10/17/2026 08:00:00 AM'}]
        data = nv.aggregate(encoded(rows), 'clark_early', 2026)
        self.assertTrue(all('breakdowns' not in row for row in data['rows']))

    def test_washoe_returned_statuses_do_not_include_outstanding_or_inperson(self):
        statuses = ['Accepted', 'Returned', 'Signature Cure Needed', 'Contact County Clerk', 'Mailed', 'Surrendered and Voted in Person', 'Canceled']
        rows = [{'VOTER_ID': str(i), 'FULL_NAME': 'PRIVATE PERSON', 'PRECINCT': '1001', 'VOTER_REG_PARTY': 'REP', 'BALLOT_RETURNED_DATE': '10/23/2026', 'BALLOT_STATUS': status} for i, status in enumerate(statuses)]
        data = nv.aggregate(encoded(rows), 'washoe_mail', 2026)
        county = next(r for r in data['rows'] if r['precinct'] is None)
        self.assertEqual(county['votes'], 4)
        self.assertEqual(county['breakdowns']['party'], {'REP': 4})

    def test_missing_registration_is_counted_as_unknown(self):
        row = {'VOTER_ID': '1', 'PRECINCT': '1018.1', 'VOTER_REG_PARTY': '', 'DATE_VOTED': '10/23/2026'}
        data = nv.aggregate(encoded([row]), 'washoe_early', 2026)
        self.assertEqual(data['rows'][0]['breakdowns']['party'], {'Unknown': 1})

    def test_general_election_code_rejects_primary_rows(self):
        row = {'IDNUMBER': '1', 'PRECINCT': '1001', 'PARTY': 'NA', 'ELECTION CODE': '26PE', 'ACTIVITY DATE': '10/17/2026'}
        with self.assertRaisesRegex(ValueError, 'different election'):
            nv.aggregate(encoded([row]), 'clark_early', 2026)

    def test_virginia_current_shards_preserve_native_name_aliases(self):
        rows = [{'FILEDATE': '2026-09-18T05:00:01', 'COUNTABLE': '0', 'MAIL_IN': '0', 'ON_MACHINE': '0'}, {'FILEDATE': '2026-09-19T05:00:01', 'COUNTABLE': '8', 'MAIL_IN': '3', 'ON_MACHINE': '5'}]
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            for label in ['401 - FIRST NAME', '401 - SECOND NAME']:
                archive.writestr(f'byLOCALITY_PRECINCT_NAME/FAIRFAX COUNTY {label}/2026/2026_November_General/data.csv', encoded(rows))
        previous = va.STORE
        try:
            with tempfile.TemporaryDirectory() as temporary:
                va.STORE = Path(temporary)
                names = {'FAIRFAX COUNTY': {'id': '51059', 'name': 'Fairfax County'}}
                index = va.write_precinct_shards(out.getvalue(), '2026-09-18', names, {'url': 'fixture'})
                self.assertEqual(index['counties'][0]['precincts'], 2)
                data = json.loads((va.STORE / 'precincts/51059.json').read_text())
                self.assertEqual({r['precinct'] for r in data['observations']}, {'401 - FIRST NAME', '401 - SECOND NAME'})
                self.assertTrue(all(r['year'] == 2026 and r['date'] == '2026-09-18' and r['comparable'] is False for r in data['observations']))
                self.assertEqual(len(data['observations']), 12)
        finally:
            va.STORE = previous

    def test_wrong_cycle_or_invalid_precinct_rejected(self):
        row = {'IDNUMBER': '1', 'PRECINCT': '1001', 'PARTY': 'NA', 'ACTIVITY DATE': '10/17/2024'}
        with self.assertRaisesRegex(ValueError, 'another election year'):
            nv.aggregate(encoded([row]), 'clark_early', 2026)
        row['ACTIVITY DATE'], row['PRECINCT'] = '10/17/2026', '<script>'
        with self.assertRaisesRegex(ValueError, 'precinct identifier'):
            nv.aggregate(encoded([row]), 'clark_early', 2026)

    def test_cumulative_uses_observed_event_dates_without_synthetic_zeros(self):
        data = [{'date': '2026-10-17', 'precinct': None, 'votes': 10}, {'date': '2026-10-19', 'precinct': None, 'votes': 15}]
        rows = nv.make_rows(data, nv.COUNTIES[0], 2026, 'mail', '2026-10-23')
        self.assertEqual([r['votes'] for r in rows if r['measure'] == 'cumulative'], [10, 25])
        self.assertFalse(any(r['date'] == '2026-10-18' for r in rows))

if __name__ == '__main__':
    unittest.main()
