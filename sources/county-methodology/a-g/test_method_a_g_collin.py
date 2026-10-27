import importlib.util
from datetime import date
from pathlib import Path
import unittest
from unittest import mock
import contextlib,io,json
S=Path(__file__).resolve().parents[3]/'dashboard/scripts/collect_collin.py';spec=importlib.util.spec_from_file_location('collin',S);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
HEADER={'A':'VoterName','B':'VoterAddress','C':'CertificateNumber','D':'Precinct','E':'VoteDate','F':'VotedBallotStyle1','G':'VoteType','H':'VotedPhase','I':'Textbox51'}
def row(i='0000000001',p='001',d='10/26/2026',kind='Regular',phase='Early Voting'):
 return {'A':'SYNTHETIC PERSON','B':'SYNTHETIC ADDRESS','C':i,'D':p,'E':d,'F':'TEST','G':kind,'H':phase,'I':''}
def run(*rows):return mod.aggregate(iter([HEADER,*rows]),date(2026,10,26),'https://www.collincountytx.gov/test.xlsx','a'*64,'2026-10-27T00:00:00+00:00')
class CollinTests(unittest.TestCase):
 def test_regular_in_person_and_identical_dedup(self):
  out=run(row(),row(),row('0000000002','002',kind='Provisional'));self.assertEqual(out[0]['counts'],{'1':1});self.assertFalse(out[0]['complete']);self.assertFalse(out[0]['cumulative'])
 def test_blank_identity_withholds_whole_local_cell(self):
  out=run(row(),row('','001'),row('0000000002','002'));self.assertEqual(out[0]['counts'],{'2':1});self.assertEqual(out[0]['unavailable_precincts'],['1'])
 def test_global_cross_date_conflict_quarantines_both_cells(self):
  out=run(row(d='10/25/2026'),row(p='002'),row('0000000002','003'));self.assertEqual(out[0]['counts'],{});self.assertEqual(out[0]['unavailable_precincts'],['1']);self.assertEqual(out[1]['counts'],{'3':1});self.assertEqual(out[1]['unavailable_precincts'],['2'])
 def test_unknown_native_precinct_retained_without_guessing(self):
  out=run(row(p='001-A'));self.assertEqual(out[0]['counts'],{'1-A':1})
 def test_blank_precinct_keeps_unassigned_positive(self):self.assertEqual(run(row(p=''))[0]['counts'],{'UNASSIGNED':1})
 def test_missing_dates_not_manufactured_as_zero(self):self.assertEqual([x['date'] for x in run(row())],['2026-10-26'])
 def test_future_wrong_year_and_ambiguous_dates_rejected(self):
  for d in ['10/27/2026','10/18/2026','10/26/2024','26/10/2026','garbage']:
   with self.subTest(d=d),self.assertRaises(ValueError):run(row(d=d))
 def test_regular_mail_or_unrecognized_method_rejected(self):
  for kind,phase in [('Regular','Mail'),('MAIL-IN','Early Voting'),('Limited','Early Voting')]:
   with self.subTest(kind=kind,phase=phase),self.assertRaises(ValueError):run(row(kind=kind,phase=phase))
 def test_schema_change_rejected(self):
  with self.assertRaises(ValueError):mod.aggregate(iter([{'A':'different'},row()]),date(2026,10,26),'x','a'*64,'x')
 def test_no_regular_roster_is_not_completed_zero(self):
  with self.assertRaises(ValueError):run(row(kind='Provisional'))
 def test_excel_dates_and_timestamp_supported(self):
  out=run(row(d='46321'),row('0000000002','002',d='10/26/2026 8:14:00 AM'));self.assertEqual(sum(out[0]['counts'].values()),2)
class DiscoveryTests(unittest.TestCase):
 def test_latest_dated_same_official_host_only(self):
  html='<a href="/early-voters-through-october-25-2026.xlsx">a</a><a href="/early-voters-through-october-26-2026.xlsx">b</a><a href="https://other.example/early-voters-through-october-26-2026.xlsx">c</a><a href="/early-voters-through-october-27-2026.xlsx">d</a>'
  cutoff,url=mod.discover(html,date(2026,10,26));self.assertEqual(cutoff,date(2026,10,26));self.assertEqual(url,'https://www.collincountytx.gov/early-voters-through-october-26-2026.xlsx')
 def test_ambiguous_latest_source_rejected(self):
  with self.assertRaises(ValueError):mod.discover('<a href="/early-voters-through-october-26-2026.xlsx?a=1">a</a><a href="/early-voters-through-october-26-2026.xlsx?a=2">b</a>',date(2026,10,26))
 def test_wrong_election_and_missing_links_rejected(self):
  with self.assertRaises(ValueError):mod.discover('<a href="/early-voters-through-october-26-2024.xlsx">a</a>',date(2026,10,26))
class CliTests(unittest.TestCase):
 def test_stdout_daily_array_for_generic_native_adapter(self):
  daily=[{'county':'collin','date':'2026-10-26','counts':{'1':1}}];out=io.StringIO()
  with mock.patch.object(mod,'collect',return_value=daily),mock.patch('sys.argv',['collect_collin.py','--county','collin','--through','2026-10-26']),contextlib.redirect_stdout(out):mod.main()
  self.assertEqual(json.loads(out.getvalue()),daily)
if __name__=='__main__':unittest.main()
