"""WordPress revision suffixes preserve the dated Dallas reporting cutoff."""
import importlib.util,unittest
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
if __name__=='__main__':unittest.main()
