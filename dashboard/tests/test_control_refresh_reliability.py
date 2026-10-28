"""Recurring controls retain qualified county editions across partial failures."""
from contextlib import ExitStack, redirect_stdout
from datetime import date, timedelta
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('refresh_controls', Path(__file__).resolve().parents[1] / 'scripts/audit_completeness.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SOS = 'https://earlyvoting.texas-election.com/Elections/getEVDetails.do'
COUNTY = 'https://www.dallascountyvotes.org/wp-content/uploads/2024/11/Early-Voting-Turnout-By-Date-Location-Report_11.01.24.xlsx'


def control(source, value, digest='a'):
    return dict(county='dallas', year=2024, date='2024-10-24', daily=value,
        cumulative=value, source=source, sha256=digest*64, retrieved_at='2026-10-28T00:00:00Z',
        scope='in_person', completed=True, note='Reviewed completed in-person aggregate')


class ControlRefresh(unittest.TestCase):
    def run_refresh(self, previous, historical, native=None):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            output = root / 'data/completeness.json'
            output.parent.mkdir(parents=True)
            output.write_text(json.dumps(dict(controls=previous)))
            stack.enter_context(patch.object(M, 'OUT', output))
            stack.enter_context(patch.object(M, 'EVIDENCE', root / 'evidence'))
            stack.enter_context(patch.object(M, 'historical', return_value=historical))
            for name in ['harris','tarrant','fortbend','bexar','vendor']:
                stack.enter_context(patch.object(M, name, return_value=[]))
            def dallas(through, offline, year=2026):
                if year == 2024:
                    if native is None:
                        raise FileNotFoundError('historical archive unavailable')
                    return native
                return []
            stack.enter_context(patch.object(M, 'dallas', side_effect=dallas))
            stack.enter_context(patch.object(sys, 'argv', ['audit_completeness.py','--through','2026-10-27']))
            with redirect_stdout(io.StringIO()):
                M.main()
            return json.loads(output.read_text())['controls']

    def test_failed_native_job_does_not_replace_reviewed_native_control_with_older_sos(self):
        previous = control(COUNTY, 50877)
        result = self.run_refresh([previous], [control(SOS,50876,'b')])
        self.assertEqual(result, [previous])

    def test_fresh_sos_edition_updates_an_older_sos_only_control(self):
        fresh = control(SOS, 50876, 'b')
        result = self.run_refresh([control(SOS,50870)], [fresh])
        self.assertEqual(result, [fresh])

    def test_fresh_successful_native_job_overrides_retained_native_and_sos(self):
        fresh = control(COUNTY, 50878, 'c')
        result = self.run_refresh([control(COUNTY,50877)], [control(SOS,50876,'b')], [fresh])
        self.assertEqual(result, [fresh])

    def test_historical_sos_supplies_an_uncovered_date(self):
        fresh = control(SOS,50876,'b')
        self.assertEqual(self.run_refresh([], [fresh]), [fresh])

    def test_missing_original_archive_downloads_official_aggregate_and_validates_all_sites(self):
        first = date(2024,10,21)
        header = {'A':'Vote Center Name', 'N':'Cumulative Total'}
        for offset in range(12):
            header[chr(ord('B')+offset)] = str((first + timedelta(days=offset) - date(1899,12,30)).days)
        totals = {'A':'Daily Unofficial Total', 'N':'120'}
        totals.update({chr(ord('B')+i):'10' for i in range(12)})
        sites = [{'A':f'Site{i}', 'N':'12', **{chr(ord('B')+j):'1' for j in range(12)}} for i in range(10)]
        rows = [{'A':'2024 General Election'}, header, totals, *sites]
        with tempfile.TemporaryDirectory() as temp, patch.object(M,'ROOT',Path(temp)/'dashboard'), patch.object(M,'fetch',return_value=b'official aggregate bytes') as fetched, patch.object(M,'workbook',return_value=rows):
            result = M.dallas(date(2026,10,27),False,2024)
        fetched.assert_called_once_with(COUNTY,'dallas-2024.xlsx',False)
        self.assertEqual(len(result),12)
        self.assertEqual(result[3]['daily'],10)
        self.assertEqual(result[-1]['cumulative'],120)
        self.assertTrue(all(r['completed'] and r['source']==COUNTY for r in result))


if __name__=='__main__': unittest.main()
