"""Synthetic public-source fixtures for final-date native recovery."""
import base64
import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock
import tempfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('collect_final_county_recovery', SCRIPTS / 'collect_final_county_recovery.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def document(when, rows):
    def fixed(value):
        return value.ljust(1090)
    records = [fixed(f'HDIMMIT         064VRH     {when:%Y%m%d}200516')]
    for identity, label in rows:
        row = [' '] * 1090
        for offset, value in [(0, 'DDIMMIT         064'), (19, identity.ljust(10)),
                              (37, '53815'), (677, 'EV    EV '), (686, f'{when:%Y%m%d}'),
                              (1003, '2'), (1064, label)]:
            row[offset:offset + len(value)] = value
        records.append(''.join(row))
    records.append(fixed(f'TDIMMIT         064{len(rows)}'))
    return ('\n'.join(records) + '\n').encode()


def file(rows):
    return {'rows': rows, 'source': 'https://dimmitcounty.org/synthetic.txt', 'sha256': 'native-input', 'trailer': len(rows)}


def encoded(csv):
    return json.dumps({'upload': base64.b64encode(csv.encode()).decode()}).encode()


class FinalRecoveryTests(unittest.TestCase):
    def test_fixed_vrh_checks_date_county_election_method_and_trailer(self):
        when = date(2026, 10, 30)
        raw = document(when, [('1000000001', 'S 1.7'), ('', 'P 10')])
        self.assertEqual(m.parse_dimmit(raw, when), ([('1000000001', 'S1.7'), ('', 'P10')], 2))
        for broken in [raw.replace(b'53815', b'99999'), raw.replace(b'EV    EV ', b'EV    ED '),
                       raw.replace(b'DDIMMIT', b'DOTHER!'), raw.replace(b'20261030', b'20261029'),
                       raw.replace(b'TDIMMIT         0642', b'TDIMMIT         0643'), raw[:-20]]:
            with self.assertRaises(ValueError):
                m.parse_dimmit(broken, when)

    def test_html_base_and_exact_advertised_dates_are_required(self):
        page = '<base href="https://dimmitcounty.org/"><p>2026-11-03</p>'
        page += '<a href="day19.txt">EV Oct 19, 2026</a><a href="day20.txt">EV Oct 20, 2026</a>'
        links = m.discover(page, date(2026, 10, 20))
        self.assertEqual(links[date(2026, 10, 20)], 'https://dimmitcounty.org/day20.txt')
        for broken in [page.replace('2026-11-03', '2024-11-05'), page.replace('day20.txt', 'https://foreign.example/day20.txt'),
                       page.replace('<a href="day20.txt">EV Oct 20, 2026</a>', '')]:
            with self.assertRaises(ValueError):
                m.discover(broken, date(2026, 10, 20))

    def test_state_empty_mail_schema_and_identity_are_not_zero(self):
        for response in [b'', b'   ', b'{}', b'{"upload":null}', b'{"upload":""}']:
            rows, _, methods = m.state_records(response)
            self.assertEqual((rows, methods), ([], {}))
        for bad in [b'not json', b'{"upload":false}', b'{"upload":0}', b'{"upload":[]}', b'{"error":"unavailable"}']:
            with self.assertRaises(ValueError):
                m.state_records(bad)
        self.assertEqual([m.normalize(value) for value in ['000','001A','\ufeff001','']],['0','1A','1','UNASSIGNED'])
        rows, _, methods = m.state_records(encoded('ID_VOTER,VOTING_METHOD,PRECINCT\n1000000001,MAIL-IN,101\n'))
        self.assertEqual(rows, [])
        self.assertEqual(methods, {'MAIL-IN': 1})
        for csv in ['ID_VOTER,PRECINCT\n1000000001,101\n',
                    'ID_VOTER,VOTING_METHOD,PRECINCT\n1000000001,UNKNOWN,101\n',
                    'ID_VOTER,VOTING_METHOD,PRECINCT\n,IN-PERSON,101\n',
                    'ID_VOTER,VOTING_METHOD,PRECINCT\n1000000001,IN-PERSON,101\n1000000001,IN-PERSON,101\n']:
            with self.assertRaises(ValueError):
                m.state_records(encoded(csv))

    def test_only_missing_sos_dates_recover_by_full_code_alias(self):
        first, final = date(2026, 10, 19), date(2026, 10, 30)
        files = {first: file([('1000000001', 'S1.7')]), final: file([('1000000002', 'S1.7')])}
        state = {first: [('1000000001', '101')], final: []}
        reports, proof = m.stage(copy.deepcopy(files), state, {'101'}, {})
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['date'], str(final))
        self.assertEqual(reports[0]['counts'], {'101': 1})
        self.assertFalse(reports[0]['complete'])
        self.assertFalse(reports[0]['cumulative'])
        self.assertEqual(proof['aliases'][0]['native'], 'S1.7')
        state[final] = [('1000000002', '101')]
        self.assertEqual(m.stage(copy.deepcopy(files), state, {'101'}, {})[0], [])

    def test_duplicate_and_cross_source_date_conflicts_reject(self):
        first, final = date(2026, 10, 19), date(2026, 10, 30)
        base = {first: file([('1000000001', 'S1.7')]), final: file([('1000000002', 'S1.7')])}
        native_duplicate = copy.deepcopy(base)
        native_duplicate[final]['rows'][0] = ('1000000001', 'S1.7')
        for files, state in [(native_duplicate, {first: [('1000000001', '101')], final: []}),
                             (base, {first: [('1000000001', '101')], final: [('1000000001', '101')]}),
                             (base, {first: [('1000000002', '101')], final: []})]:
            with self.assertRaises(ValueError):
                m.stage(copy.deepcopy(files), state, {'101'}, {})

    def test_live_collection_isolates_bad_native_file_and_validates_empty_final_sos(self):
        first, second, final = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)
        page = '<base href="https://dimmitcounty.org/"><p>2026-11-03</p>'
        page += ''.join(f'<a href="day{d.day}.txt">EV Oct {d.day}, 2026</a>' for d in [first, second, final])
        native_rows = {first: [('1000000001', 'S 1.7')], second: [('1000000002', 'S 1.7')], final: [('1000000003', 'S 1.7')]}
        requested_sos = []
        def downloader(url):
            if url == m.LANDING:
                return page.encode()
            if 'getFileByFormat' in url:
                requested_sos.append(url)
                if '10%2F21%2F2026' in url:
                    return b''  # Actual Dimmit final HTTP200 empty-body pattern.
                identity = '1000000001' if '10%2F19%2F2026' in url else '1000000002'
                return encoded(f'ID_VOTER,VOTING_METHOD,PRECINCT\n{identity},IN-PERSON,101\n')
            day = next(d for d in native_rows if f'day{d.day}.txt' in url)
            raw = document(day, native_rows[day])
            return raw.replace(b'EV    EV ', b'EV    PE ') if day == first else raw
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dashboard/data').mkdir(parents=True)
            (root / 'dashboard/data/reference.json').write_text(json.dumps([{'id':'dimmit','groups':[{'new':['101']}]}]))
            with mock.patch.object(m, 'ROOT', root):
                reports, proof = m.collect(final, downloader)
        self.assertEqual(len(requested_sos), 3, 'rejected native day still requires its SOS identity audit')
        self.assertEqual([(r['date'],r['counts']) for r in reports], [(str(d),{'101':1}) for d in [first,second,final]])
        for report, source in zip(reports[:2], proof['state_sources'][:2]):
            self.assertEqual((report['counts'],report['source'],report['sha256']),
                             (source['counts'],source['source'],source['sha256']))
        self.assertEqual(proof['fallback_dates'],[str(final)])
        self.assertEqual(proof['rejected_native_sources'][0]['date'], str(first))
        self.assertEqual(proof['state_sources'][-1]['availability'], 'empty_http_200_body')
        self.assertFalse(proof['state_sources'][-1]['zero_certified'])
        self.assertEqual(len(proof['native_sources']), 2)

    def test_foreign_targets_and_blank_cells_never_certify_precincts(self):
        first, second, final = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 30)
        files = {first: file([('1000000001', 'S1.7')]), second: file([('1000000002', 'S1.7')]),
                 final: file([('1000000003', 'S1.7')])}
        state = {first: [('1000000001', '101')], second: [('1000000002', 'FOREIGN')], final: []}
        reports, proof = m.stage(copy.deepcopy(files), state, {'101'}, {})
        self.assertEqual(reports, [])
        self.assertEqual(proof['aliases'][0]['observed_targets'], ['101', 'FOREIGN'])
        self.assertFalse(proof['aliases'][0]['accepted'])
        files.pop(second)
        state.pop(second)
        files[final]['rows'].append(('', 'S1.7'))
        self.assertEqual(m.stage(copy.deepcopy(files), state, {'101'}, {})[0], [])


if __name__ == '__main__':
    unittest.main()
