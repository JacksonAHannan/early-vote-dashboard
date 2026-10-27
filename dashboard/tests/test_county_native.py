"""Synthetic county-roster contracts; no real voter fixtures."""
import base64
from datetime import date, datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/collect_county_native.py'
spec = importlib.util.spec_from_file_location('county_native', SCRIPT)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
DAY = date(2026, 10, 21)


class CountyNativeTests(unittest.TestCase):
    def test_waller_in_person_date_and_residence_precinct(self):
        text = ('WALLER COUNTY | 2026 GENERAL ELECTION Election date: 11/3/2026 | Roster dates: 10/21/2026\n'
                'Number Name of Early Voter Residence Address Date VUID\n'
                '101    0000000001    SYNTHETIC PERSON    99 TEST ST    10/21/2026\n')
        self.assertEqual(native.parse_waller(text, DAY), [('0000000001', '101')])
        with self.assertRaises(ValueError):
            native.parse_waller(text, date(2026, 10, 22))

    def test_sanpatricio_retains_split_label_until_proven(self):
        text = ('Wednesday, October 21, 2026\nVUID VOTER   NAME Precinct\n'
                '0000000001 SYNTHETIC PERSON 110-GPISD\n')
        self.assertEqual(native.parse_sanpatricio(text, DAY), [('0000000001', '110-GPISD')])

    def test_sanpatricio_blank_id_uses_name_column_not_page_footer(self):
        text = ('Wednesday, October 21, 2026\n'
                '  VUID       VOTER NAME                         Precinct\n'
                '             SYNTHETIC PERSON                   110\n'
                '             Page 103\n'
                ' Page 101\n'
                '                                       Page 102\n')
        self.assertEqual(native.parse_sanpatricio(text, DAY), [('', '110')])
        with self.assertRaises(ValueError):
            native.parse_sanpatricio(text, date(2026, 10, 22))

    def test_waller_blank_id_is_localized_without_inventing_identity(self):
        text = ('WALLER COUNTY | 2026 GENERAL ELECTION Election date: 11/3/2026 | Roster dates: 10/21/2026\n'
                'Number Name of Early Voter Residence Address Date VUID\n'
                '420                 SYNTHETIC PERSON    99 TEST ST    10/21/2026\n')
        self.assertEqual(native.parse_waller(text, DAY), [('', '420')])

    def test_aliases_with_matching_official_identity_are_accepted(self):
        csv = 'ID_VOTER,VOTING_METHOD,PRECINCT\n0000000001,IN-PERSON,413\n'
        raw = json.dumps({'upload': base64.b64encode(csv.encode()).decode()}).encode()
        aliases, proof, sha = native.derive_aliases([('0000000001', 'S 413.2')], raw, {'413'})
        self.assertEqual(aliases, {'S 413.2': '413'})
        self.assertEqual(proof[0]['matched_rows'], 1)

    def test_sparse_headerless_workbook_and_location_scope(self):
        def workbook(location):
            xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">'
                   '<c r="A1"><v>0000000001</v></c><c r="B1" t="inlineStr"><is><t>SYNTHETIC PERSON</t></is></c>'
                   '<c r="C1" t="inlineStr"><is><t>S 413.2</t></is></c>'
                   f'<c r="D1" t="inlineStr"><is><t>{location}</t></is></c>'
                   '</row></sheetData></worksheet>')
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as book:
                book.writestr('xl/worksheets/sheet1.xml', xml)
            return output.getvalue()
        raw = workbook('EV-EV Washington County Courthouse Annex')
        self.assertEqual(native.parse_washington(raw, DAY), [('0000000001', 'S 413.2')])
        with self.assertRaises(ValueError):
            native.parse_washington(workbook('MAIL'), DAY)

    def test_alias_requires_unambiguous_official_identity_evidence(self):
        csv = ('ID_VOTER,VOTING_METHOD,PRECINCT\n'
               '0000000001,IN-PERSON,413\n0000000002,IN-PERSON,418\n'
               '0000000003,MAIL-IN,101\n')
        raw = json.dumps({'upload': base64.b64encode(csv.encode()).decode()}).encode()
        rows = [('0000000001', 'S 413.2'), ('0000000002', 'S 413.2'), ('0000000003', 'P 101')]
        aliases, proof, sha = native.derive_aliases(rows, raw, {'413', '418', '101'})
        self.assertEqual(aliases, {})
        self.assertEqual(proof, [{'native': 'S 413.2', 'conflicting_targets': ['413', '418']}])

    def test_local_quarantine_deduplication_and_unknown_label(self):
        files = {DAY: dict(rows=[('1', '101'), ('1', '101'), ('', '102'), ('2', '102'),
                                ('3', 'UNREVIEWED 103')], source='official', sha256='synthetic')}
        result = native.aggregate('waller', files, {'101', '102', '103'})[0]
        self.assertEqual(result['counts'], {'101': 1, 'UNASSIGNED': 1})
        self.assertEqual(result['unavailable_precincts'], ['102'])
        self.assertEqual(result['unmapped_precincts'], ['UNREVIEWED 103'])
        self.assertFalse(result['complete'])

    def test_cross_date_conflict_quarantines_both_cells(self):
        tomorrow = date(2026, 10, 22)
        files = {DAY: dict(rows=[('1', '101'), ('2', '102')], source='official', sha256='synthetic'),
                 tomorrow: dict(rows=[('1', '103'), ('3', '102')], source='official', sha256='synthetic')}
        result = native.aggregate('waller', files, {'101', '102', '103'})
        self.assertEqual(result[0]['unavailable_precincts'], ['101'])
        self.assertEqual(result[1]['unavailable_precincts'], ['103'])
        self.assertEqual(result[0]['counts']['102'], 1)
        self.assertEqual(result[1]['counts']['102'], 1)

    def test_discovery_separates_mail_none_and_in_person(self):
        page = ('<a href="#">October 25, 2026 - NONE</a>'
                '<a href="/upload/page/0286/October 25.26 In Person.pdf">October 25, 2026</a>')
        found = native.discover('waller', page)
        self.assertEqual(list(found), [date(2026, 10, 25)])

    def test_discovery_rejects_wrong_election_host_and_workbook_date(self):
        folder = '/upload/page/10698/2026/2026 11 03/'
        page = (f'<a href="{folder}102226.xlsx">October 21</a>'
                '<a href="/upload/2024/2024 11 05/102124.xlsx">October 21</a>'
                f'<a href="https://other.example{folder}102126.xlsx">October 21</a>'
                f'<a href="{folder}10232026.xlsx">October 23</a>'
                f'<a href="{folder}103226.xlsx">October 32</a>')
        self.assertEqual(list(native.discover('washington', page)), [date(2026, 10, 23)])
        self.assertEqual(native.discover('sanpatricio',
                         '<a href="/2024/General Election/Voting Rosters/List of Voters October 21.pdf">Voters</a>'), {})

    def test_ambiguous_date_does_not_discard_other_sources(self):
        folder = '/upload/page/10698/2026/2026 11 03/'
        page = (f'<a href="{folder}102126.xlsx">October 21</a>'
                f'<a href="{folder}revised 102126.xlsx">October 21</a>'
                f'<a href="{folder}102226.xlsx">October 22</a>')
        with mock.patch('sys.stderr', new_callable=io.StringIO):
            found = native.discover('washington', page)
        self.assertEqual(list(found), [date(2026, 10, 22)])

    def test_missing_link_fetch_failure_and_bad_date_preserve_other_dates(self):
        days = [19, 20, 22, 23, 25, 26]  # October 21 is not advertised.
        page = ''.join(f'<a href="/upload/page/0286/October {d}.26 In Person.pdf">October {d}</a>' for d in days)
        fetched = []

        def downloader(url):
            fetched.append(url)
            if url == native.LANDINGS['waller']:
                return page.encode()
            day = int(url.split('October ')[1].split('.')[0])
            if day == 20:
                raise ValueError('synthetic unavailable source')
            row_day = 22 if day == 23 else day  # Wrong-date official PDF.
            return (f'WALLER COUNTY | 2026 GENERAL ELECTION Election date: 11/3/2026 | Roster dates: 10/{day}/2026\n'
                    'Number Name of Early Voter Residence Address Date VUID\n'
                    f'101 00000000{day:02} SYNTHETIC PERSON 99 TEST ST 10/{row_day}/2026\n').encode()

        frozen = mock.Mock(wraps=datetime)
        # At 04:30 UTC Oct 26 it is still Oct 25 in America/Chicago.
        frozen.now.side_effect = lambda tz: datetime(2026, 10, 26, 4, 30, tzinfo=timezone.utc).astimezone(tz)
        with mock.patch.object(native, 'datetime', frozen), \
             mock.patch.object(native, 'pdf_text', side_effect=lambda raw: raw.decode()), \
             mock.patch('sys.stderr', new_callable=io.StringIO) as diagnostics:
            result = native.collect('waller', date(2026, 10, 30), downloader)
        self.assertEqual([r['date'] for r in result], ['2026-10-19', '2026-10-22'])
        self.assertTrue(all(sum(r['counts'].values()) == 1 for r in result))
        self.assertFalse(any('October 25.' in u or 'October 26.' in u for u in fetched))
        self.assertIn('2026-10-20', diagnostics.getvalue())
        self.assertIn('2026-10-23', diagnostics.getvalue())


if __name__ == '__main__':
    unittest.main()
