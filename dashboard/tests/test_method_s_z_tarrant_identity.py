import importlib.util
from pathlib import Path
import unittest
PATH=Path(__file__).resolve().parents[2]/'sources/county-methodology/s-z/tarrant_identity_anchor.py'
spec=importlib.util.spec_from_file_location('method_s_z_anchor',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class TarrantExactIdentity(unittest.TestCase):
 def test_individually_proved_native_rows_survive_conflicting_label(self):
  county={'synthetic-a':'100101','synthetic-b':'100101','synthetic-c':'200101'}
  sources=[{'identities':{'synthetic-a':'1001','synthetic-b':'2001','synthetic-c':'2001'}}]
  counts,bad,proof,withheld=m.aggregate(county,{},sources,{'1001','2001'})
  self.assertEqual(counts,{'1001':1,'2001':2});self.assertEqual(bad,[]);self.assertEqual(withheld,0)
 def test_unmatched_row_quarantines_every_possible_native_cell(self):
  county={'synthetic-a':'100101','synthetic-b':'100101','synthetic-unmatched':'100101','synthetic-d':'300101'}
  sources=[{'identities':{'synthetic-a':'1001','synthetic-b':'2001','synthetic-d':'3001'}}]
  counts,bad,proof,withheld=m.aggregate(county,{},sources,{'1001','2001','3001'})
  self.assertNotIn('1001',counts);self.assertNotIn('2001',counts);self.assertEqual(counts['3001'],1)
  self.assertTrue({'1001','2001'}<=set(bad));self.assertEqual(withheld,2);self.assertEqual(counts['UNRESOLVED 100101'],1)
 def test_foreign_target_is_not_ignored_or_repaired_by_native_majority(self):
  county={'synthetic-a':'100101','synthetic-foreign':'100101','synthetic-unmatched':'100101'}
  sources=[{'identities':{'synthetic-a':'1001','synthetic-foreign':'99'}}]
  counts,bad,proof,withheld=m.aggregate(county,{},sources,{'1001'})
  self.assertNotIn('1001',counts);self.assertIsNone(proof['100101']['target']);self.assertEqual(proof['100101']['matches'],{'1001':1,'99':1});self.assertEqual(withheld,1)
 def test_invalid_identity_quarantines_cell_even_when_other_rows_directly_proved(self):
  county={'synthetic-a':'100101','synthetic-b':'200101'}
  sources=[{'identities':{'synthetic-a':'1001','synthetic-b':'2001'}}]
  counts,bad,proof,withheld=m.aggregate(county,{'100101':1},sources,{'1001','2001'})
  self.assertNotIn('1001',counts);self.assertEqual(counts['2001'],1);self.assertIn('1001',bad);self.assertEqual(withheld,1)
 def test_duplicate_sos_identity_across_dates_rejected(self):
  with self.assertRaisesRegex(ValueError,'repeated'):
   m.aggregate({'synthetic-a':'100101'},{},[{'identities':{'synthetic-a':'1001'}},{'identities':{'synthetic-a':'1001'}}],{'1001'})

if __name__=='__main__':unittest.main()
