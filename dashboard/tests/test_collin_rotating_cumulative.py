"""Use explicit completed vote dates from a replaced cumulative publication."""
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('collin_rotating',Path(__file__).resolve().parents[1]/'scripts/collect_collin.py')
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return cls(2026,10,30,20,0,tzinfo=tz)

def row(identity,when,precinct='001'):
 return {'A':'Synthetic','B':'Synthetic','C':identity,'D':precinct,'E':when,'F':'test','G':'Regular','H':'Early Voting','I':''}

class RotatingCumulative(unittest.TestCase):
 def test_current_new_filename_is_discovered(self):
  html='<a href="/docs/default-source/elections/election-rosters/early-voting-through-october-30-2026.xlsx?sfvrsn=1">Early voters</a>'
  self.assertEqual(M.discover(html,date(2026,10,30))[0],date(2026,10,30))

 def collect(self,rows,through=date(2026,10,29)):
  landing=b'<a href="/docs/default-source/elections/election-rosters/early-voting-through-october-30-2026.xlsx">Early voters</a>'
  def downloader(url):return landing if url==M.LANDING else b'official cumulative workbook'
  with patch.object(M,'datetime',Clock),patch.object(M,'xlsx_rows',return_value=iter([M.HEADER,*rows])):
   return M.collect(through,downloader)

 def test_later_publication_yields_only_explicit_completed_dates(self):
  days=self.collect([row('1000000001','10/29/2026'),row('1000000002','10/30/2026','002')])
  self.assertEqual([(d['date'],d['counts']) for d in days],[('2026-10-29',{'1':1})])
  self.assertTrue(all(not d['complete'] and not d['cumulative'] for d in days))

 def test_active_day_request_is_capped_even_with_current_day_workbook(self):
  days=self.collect([row('1000000001','10/29/2026'),row('1000000002','10/30/2026','002')],date(2026,10,30))
  self.assertEqual([d['date'] for d in days],['2026-10-29'])

 def test_later_identity_contradiction_withholds_earlier_cell(self):
  days=self.collect([row('1000000001','10/29/2026'),row('1000000002','10/29/2026','003'),row('1000000001','10/30/2026','002')])
  self.assertEqual(days[0]['counts'],{'3':1})
  self.assertEqual(days[0]['unavailable_precincts'],['1'])

 def test_row_outside_publication_date_is_rejected(self):
  with self.assertRaises(ValueError):self.collect([row('1000000001','10/29/2026'),row('1000000002','10/31/2026','002')])

if __name__=='__main__':unittest.main()
