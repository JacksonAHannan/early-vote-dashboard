"""Later Denton publications may contain earlier complete, explicitly dated rows."""
from datetime import date,datetime,timedelta,timezone
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/collect_large_county_refresh.py'
spec=importlib.util.spec_from_file_location('denton_refresh',SCRIPT)
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def row(day,identity='1000000001'):
 serial=(date(2026,10,day)-date(1899,12,30)).days
 return {'A':'SYNTHETIC','B':identity,'C':'TEST','D':f'{serial}.5','E':'100001','F':'TEST','G':'TEST'}

class DentonPublicationCutoff(unittest.TestCase):
 def freeze(self):
  frozen=mock.Mock(wraps=datetime);frozen.now.side_effect=lambda tz:datetime(2026,10,30,23,tzinfo=timezone.utc).astimezone(tz)
  return mock.patch.object(M,'datetime',frozen)
 def test_later_current_publication_can_supply_completed_prior_dates(self):
  html='<a href="/wp-content/uploads/2026/10/1126_10-30_Early-Voting-Roster.xlsx">latest</a>'
  with self.freeze():published,url=M.discover_denton(html,date(2026,10,29))
  self.assertEqual(published,date(2026,10,30));self.assertIn('10-30_',url)
 def test_explicit_current_day_rows_excluded_from_earlier_requested_cutoff(self):
  files=M.parse_denton([M.DENTON_HEADER,row(29),row(30,'1000000002')],date(2026,10,29),'official','a'*64,published_through=date(2026,10,30))
  self.assertEqual(set(files),{date(2026,10,29)})
  self.assertEqual(files[date(2026,10,29)]['rows'],[('1000000001','100001')])
 def test_unreviewed_foreign_mail_wrong_election_or_future_publication_rejected(self):
  urls=['https://other.example/wp-content/uploads/2026/10/1126_10-30_Early-Voting-Roster.xlsx','/wp-content/uploads/2024/10/1124_10-30_Early-Voting-Roster.xlsx','/wp-content/uploads/2026/10/1126_10-30_Returned-Mail-Roster.xlsx','/wp-content/uploads/2026/10/1126_10-31_Early-Voting-Roster.xlsx']
  with self.freeze():
   for url in urls:
    with self.subTest(url=url),self.assertRaises(ValueError):M.discover_denton(f'<a href="{url}">x</a>',date(2026,10,29))
 def test_row_date_after_declared_publication_and_bad_schema_still_rejected(self):
  with self.assertRaises(ValueError):M.parse_denton([M.DENTON_HEADER,{**row(30),'D':'46326'}],date(2026,10,29),'official','a'*64,published_through=date(2026,10,30))
  with self.assertRaises(ValueError):M.parse_denton([{'A':'wrong'},row(29)],date(2026,10,29),'official','a'*64,published_through=date(2026,10,30))
 def test_collector_clamps_current_day_and_passes_only_completed_dates_to_identity_proof(self):
  html=b'<a href="/wp-content/uploads/2026/10/1126_10-30_Early-Voting-Roster.xlsx">latest</a>'
  calls=[]
  def proof(files,universe,downloader):
   calls.append(set(files));self.assertNotIn(date(2026,10,30),files)
   return {'100001':'1000'},{'100001':{'1000'}},[]
  with self.freeze(),mock.patch.object(M,'xlsx_rows',return_value=iter([M.DENTON_HEADER,row(29),row(30,'1000000002')])),mock.patch.object(M,'denton_aliases',side_effect=proof):
   output=M.collect_denton(date(2026,10,30),lambda url:html if url==M.DENTON_LANDING else b'syntheticbook')
  self.assertEqual([d['date'] for d in output],['2026-10-29']);self.assertEqual(calls,[{date(2026,10,29)}])
if __name__=='__main__':unittest.main()
