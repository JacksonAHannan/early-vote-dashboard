"""Recurring official-source discovery and conservative date-local aggregation."""
import importlib.util
import base64
import json
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('large_refresh', Path(__file__).resolve().parents[1] / 'scripts/collect_large_county_refresh.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture(day=27):
    return [
        {'A': 'Cameron County General Election'},
        {'A': 'For the November 3, 2026 Election'},
        {'A': date(2026, 10, day).strftime('%A, %B %d, %Y')},
        {'A': 'VUID', 'B': 'NAME', 'C': 'CHECK-IN', 'D': 'PRECINCT'},
        {'A': '1000000001', 'B': 'Synthetic person', 'C': f'10/{day}/2026', 'D': '001'},
    ]


class RefreshTests(unittest.TestCase):
    def test_denton_discovers_renamed_next_day_roster_and_excludes_mail(self):
        html = '<a href="/wp-content/uploads/2026/10/1126_10-27_Early-Voting-Roster.xlsx">daily</a><a href="/wp-content/uploads/2026/10/1126_10-28_Returned_Mail_Roster.xlsx">mail</a>'
        self.assertEqual(M.discover_denton(html, date(2026, 10, 28))[0], date(2026, 10, 27))
        html = '<a href="/wp-content/uploads/2026/10/1126_10-28_Early-Voting-Roster.xlsx">daily</a>'
        self.assertEqual(M.discover_denton(html, date(2026, 10, 28))[0], date(2026, 10, 28))

    def test_denton_explicit_excel_timestamps_keep_dates_and_residence_precinct(self):
        serial = (date(2026, 10, 27) - date(1899, 12, 30)).days
        rows = [M.DENTON_HEADER,
            {'A':'Synthetic', 'B':'1000000001', 'C':'Synthetic', 'D':f'{serial}.5', 'E':'01000', 'F':'', 'G':'GS'}]
        files = M.parse_denton(rows, date(2026, 10, 27), 'official', 'a'*64)
        self.assertEqual(list(files), [date(2026, 10, 27)])
        self.assertEqual(files[date(2026, 10, 27)]['rows'], [('1000000001', '1000')])

    def test_denton_aliases_require_exact_identity_and_new_date_conflict_revokes_alias(self):
        first, second = date(2026, 10, 27), date(2026, 10, 28)
        files = {first:{'rows':[('1000000001','100001'),('1000000002','100002')]}}
        def response(rows):
            raw = ('ID_VOTER,PRECINCT,VOTING_METHOD\n' + ''.join(f'{v},{p},IN-PERSON\n' for v,p in rows)).encode()
            return json.dumps({'upload':base64.b64encode(raw).decode()}).encode()
        responses = {'10/27/2026':response([('1000000001','1000')]), '10/28/2026':response([('1000000003','9999')])}
        def downloader(url):
            return next(raw for key,raw in responses.items() if key in url)
        aliases, _, _ = M.denton_aliases(files, {'1000'}, downloader)
        self.assertEqual(aliases, {'100001':'1000'})
        self.assertNotIn('100002', aliases)  # no string-based prefix inference
        files[second] = {'rows':[('1000000003','100001')]}
        aliases, targets, manifests = M.denton_aliases(files, {'1000'}, downloader)
        self.assertEqual(aliases, {})
        self.assertEqual(targets['100001'], {'1000','9999'})
        self.assertEqual(len(manifests), 2)

    def test_denton_transient_proof_failure_cannot_recognize_alias_from_reduced_evidence(self):
        files = {date(2026, 10, 27):{'rows':[('1000000001','100001')]}}
        with self.assertRaisesRegex(ValueError, 'identity proof incomplete'):
            M.denton_aliases(files, {'1000'}, lambda url: (_ for _ in ()).throw(TimeoutError()))

    def test_discovers_next_day_without_code_or_dated_manifest_change(self):
        def page(day):
            return f'<a href="/elections/wp-content/uploads/2026/10/01_Cameron_County10-{day}-2026.xlsx">County roster</a>'
        self.assertEqual(M.discover_cameron(page(27), date(2026, 10, 27))[0], date(2026, 10, 27))
        self.assertEqual(M.discover_cameron(page(28), date(2026, 10, 28))[0], date(2026, 10, 28))

    def test_future_foreign_local_entity_and_mail_links_cannot_be_selected(self):
        html = ''.join([
            '<a href="https://evil.example/elections/wp-content/uploads/2026/10/01_Cameron_County10-27-2026.xlsx">x</a>',
            '<a href="/elections/wp-content/uploads/2026/10/01_Cameron_County10-28-2026.xlsx">future</a>',
            '<a href="/elections/wp-content/uploads/2026/10/02_Cameron_Appraisal_District10-27-2026.xlsx">local</a>',
            '<a href="/elections/wp-content/uploads/2026/10/MAIL-GN26-Cameron-County-CC-2026-10-27.xlsx">mail</a>',
        ])
        with self.assertRaises(ValueError): M.discover_cameron(html, date(2026, 10, 27))

    def test_conflicting_same_date_links_are_rejected(self):
        html = ''.join(f'<a href="/elections/wp-content/uploads/2026/{month}/01_Cameron_County10-27-2026.xlsx">x</a>' for month in ['09','10'])
        with self.assertRaises(ValueError): M.discover_cameron(html, date(2026, 10, 27))

    def test_repeated_refresh_fetches_new_link_and_new_bytes_without_manifest_edits(self):
        requests = []
        published = [27]
        def downloader(url):
            requests.append(url)
            if url == M.CAMERON_LANDING:
                return f'<a href="/elections/wp-content/uploads/2026/10/01_Cameron_County10-{published[0]}-2026.xlsx">roster</a>'.encode()
            return str(published[0]).encode()
        with patch.object(M, 'xlsx_rows', side_effect=lambda raw: fixture(int(raw))):
            first = M.collect_cameron(date(2026, 10, 27), downloader)
            published[0] = 28
            second = M.collect_cameron(date(2026, 10, 28), downloader)
        self.assertEqual(requests.count(M.CAMERON_LANDING), 2)
        self.assertEqual(first[0]['date'], '2026-10-27')
        self.assertEqual(second[0]['date'], '2026-10-28')
        self.assertNotEqual(first[0]['source'], second[0]['source'])
        self.assertNotEqual(first[0]['sha256'], second[0]['sha256'])

    def aggregate(self, rows, through=date(2026, 10, 27)):
        return M.aggregate_cameron(rows, through, 'https://official.example/current.xlsx', 'a'*64, '2026-10-28T00:00:00Z')

    def test_exact_row_dates_native_codes_and_no_invented_missing_zeros(self):
        days = self.aggregate(fixture())
        self.assertEqual([(d['date'], d['counts']) for d in days], [('2026-10-27', {'1': 1})])
        self.assertFalse(days[0]['complete'])
        self.assertFalse(days[0]['cumulative'])

    def test_blank_or_conflicting_identity_withholds_whole_affected_cells(self):
        rows = fixture() + [
            {'A': '', 'B': 'Synthetic blank', 'C': '10/27/2026', 'D': '001'},
            {'A': '1000000002', 'B': 'Synthetic good', 'C': '10/27/2026', 'D': '002'},
            {'A': '1000000003', 'B': 'Synthetic conflict', 'C': '10/27/2026', 'D': '003'},
            {'A': '1000000003', 'B': 'Synthetic conflict', 'C': '10/27/2026', 'D': '004'},
        ]
        day = self.aggregate(rows)[0]
        self.assertEqual(day['counts'], {'2': 1})
        self.assertEqual(day['unavailable_precincts'], ['1','3','4'])

    def test_bad_new_date_does_not_throw_away_successful_earlier_date(self):
        rows = fixture() + [
            {'A': 'Wednesday, October 28, 2026'},
            {'A': 'VUID', 'B': 'NAME', 'C': 'CHECK-IN', 'D': 'PRECINCT'},
            {'A': '1000000002', 'B': 'Synthetic', 'C': 'broken', 'D': '002'},
        ]
        days = self.aggregate(rows, date(2026, 10, 28))
        self.assertEqual([d['date'] for d in days], ['2026-10-27'])

    def test_cross_date_identity_repeat_quarantines_both_cells(self):
        rows = fixture() + [
            {'A': 'Wednesday, October 28, 2026'},
            {'A': 'VUID', 'B': 'NAME', 'C': 'CHECK-IN', 'D': 'PRECINCT'},
            {'A': '1000000001', 'B': 'Synthetic', 'C': '10/28/2026', 'D': '001'},
            {'A': '1000000002', 'B': 'Synthetic independent', 'C': '10/28/2026', 'D': '002'},
        ]
        days = self.aggregate(rows, date(2026, 10, 28))
        self.assertEqual([d['date'] for d in days], ['2026-10-28'])
        self.assertEqual(days[0]['counts'], {'2':1})
        self.assertEqual(days[0]['unavailable_precincts'], ['1'])


if __name__ == '__main__': unittest.main()
