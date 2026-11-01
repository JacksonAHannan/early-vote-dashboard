"""WordPress revision suffixes preserve the dated Dallas reporting cutoff."""
import importlib.util,unittest
from unittest.mock import patch
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('controls',ROOT/'dashboard/scripts/audit_completeness.py')
controls=importlib.util.module_from_spec(spec);spec.loader.exec_module(controls)
class CountyCutoff(unittest.TestCase):
 def test_wordpress_revision_is_not_a_missing_report(self):
  self.assertEqual(controls.dated_workbook_cutoff('https://www.dallascountyvotes.org/wp-content/uploads/2026/10/Early-Voting-Turnout-By-Date-Location_10.25.26-1.xlsx',2026),date(2026,10,25))
 def test_original_dates_and_election_year_remain_checked(self):
  self.assertEqual(controls.dated_workbook_cutoff('https://official.example/Report_11.01.24.xlsx',2024),date(2024,11,1))
  for url,year in [('https://official.example/Report.xlsx',2026),('https://official.example/Report_10.25.24-1.xlsx',2026),('https://official.example/Report_10.32.26.xlsx',2026),('https://official.example/Report_10.25.26-final.xlsx',2026)]:
   with self.subTest(url=url):
    with self.assertRaises(ValueError):controls.dated_workbook_cutoff(url,year)

class TravisOrdinaryControl(unittest.TestCase):
 def report(self, ordinary=None, site_value='1'):
  ordinary=ordinary or [10]*12
  header='November 03, 2026 General Election: Early Voting In Person and By Mail Totals\n'
  dates=' '.join(f'{day}-Oct' for day in range(19,31))
  line=lambda label,values:label+'  '+' '.join(map(str,values))+'\n'
  report=header+dates+'\n'+line('Early Voting Location Voters',ordinary+[sum(ordinary)])
  report+=line('Limited Ballots',[2]*12+[24])+line('Mail Ballots Received',[3]*12+[36])
  report+=line('Cumulative',[15]*12+[180])
  report+=''.join(line(f'Polling place {i}',[site_value]*12+[12]) for i in range(10))
  return report
 def collect(self, text, landing=None, through=date(2026,10,30)):
  landing=landing or '<a href="/wp-content/uploads/G26-Daily-Totals-10302026.pdf">Daily Check-in Totals by site</a>'
  with patch.object(controls,'fetch',side_effect=[landing.encode(),b'%PDF official aggregate']) as fetch,patch.object(controls,'pdf',return_value=text):
   result=controls.travis(through,False)
  return result,fetch
 def test_county_pdf_ordinary_series_excludes_limited_and_mail(self):
  result,fetch=self.collect(self.report(),through=date(2026,10,27))
  self.assertEqual(len(result),9)
  self.assertEqual(result[-1]['daily'],10)
  self.assertEqual(result[-1]['cumulative'],90)
  self.assertIn('G26-Daily-Totals-10302026.pdf',result[-1]['source'])
  self.assertNotIn('electionlink',result[-1]['source'])
  self.assertEqual(fetch.call_count,2)
 def test_discovery_uses_latest_dated_county_pdf_and_rejects_ambiguity(self):
  landing='<a href="/wp-content/uploads/G26-Daily-Totals-10292026.pdf">old</a><a href="/wp-content/uploads/G26-Daily-Totals-10302026.pdf">latest</a>'
  result,_=self.collect(self.report(),landing)
  self.assertEqual(result[-1]['cumulative'],120)
  with self.assertRaises(ValueError):
   self.collect(self.report(),landing+'<a href="/wp-content/uploads/G26-Daily-Totals-10302026-1.pdf">conflict</a>')
 def test_wrong_election_dates_and_polling_place_disagreement_fail_closed(self):
  for report in [self.report().replace('2026 General','2024 General'),self.report().replace('30-Oct','31-Oct'),self.report(site_value='2')]:
   with self.subTest(report=report[:100]):
    with self.assertRaises(ValueError):self.collect(report)
if __name__=='__main__':unittest.main()
