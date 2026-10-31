"""Synthetic old/new Washington daily workbook schemas; no voter fixtures."""
from datetime import date
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/collect_county_native.py'
spec=importlib.util.spec_from_file_location('washington_native',SCRIPT)
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
LOCATION='EV-EV Washington County Courthouse Annex'
DAY=date(2026,10,28)

class WashingtonLayouts(unittest.TestCase):
 def parse(self,rows):
  with mock.patch.object(native,'xlsx_rows',return_value=iter(rows)):
   return native.parse_washington(b'synthetic workbook',DAY)
 def test_oct28_six_column_layout_preserves_full_native_residence_label(self):
  self.assertEqual(self.parse([{'A':'0000000001','B':'SYNTHETIC','C':'TEST METADATA','D':'S 413.2','E':LOCATION,'F':'TEST BALLOT STYLE'}]),[('0000000001','S 413.2')])
 def test_original_five_column_layout_still_supported(self):
  self.assertEqual(self.parse([{'A':'0000000001','B':'SYNTHETIC','C':'P 307','D':LOCATION,'E':'TEST STYLE'}]),[('0000000001','P 307')])
 def test_wide_layout_blank_identity_remains_a_quarantine_input(self):
  self.assertEqual(self.parse([{'B':'SYNTHETIC','C':'TEST METADATA','D':'S 413.2','E':LOCATION,'F':'TEST STYLE'}]),[('','S 413.2')])
 def test_unreviewed_layout_location_and_missing_precinct_rejected(self):
  valid={'A':'0000000001','B':'SYNTHETIC','C':'TEST METADATA','D':'S 413.2','E':LOCATION,'F':'TEST STYLE'}
  for changes in [{'G':'UNREVIEWED'},{'E':'MAIL'},{'D':''},{'D':'10/28/2026'},{'A':'not-an-id'},{'C':''}]:
   with self.subTest(changes=changes),self.assertRaises(ValueError):self.parse([{**valid,**changes}])
 def test_mixed_schema_workbook_is_not_silently_reinterpreted(self):
  old={'A':'0000000001','B':'SYNTHETIC','C':'P 307','D':LOCATION,'E':'TEST STYLE'}
  new={'A':'0000000002','B':'SYNTHETIC','C':'TEST METADATA','D':'S 413.2','E':LOCATION,'F':'TEST STYLE'}
  with self.assertRaises(ValueError):self.parse([old,new])
if __name__=='__main__':unittest.main()
