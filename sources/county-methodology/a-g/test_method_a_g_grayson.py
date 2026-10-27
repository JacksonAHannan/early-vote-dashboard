import copy,importlib.util,json,subprocess,unittest
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[2];spec=importlib.util.spec_from_file_location('grayson',P/'grayson_returns.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class GraysonTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.text=subprocess.check_output(['pdftotext','-layout',str(P/'grayson-2024-precinct.pdf'),'-'],text=True);cls.summary=subprocess.check_output(['pdftotext','-layout',str(P/'grayson-2024-summary.pdf'),'-'],text=True);cls.ref=next(x for x in json.loads((ROOT/'dashboard/data/reference.json').read_text())if x['id']=='grayson')
 def test_exact_full_partition_and_existing_agreement(self):
  x=mod.parse_text(self.text,self.summary,self.ref);self.assertEqual(len(x['presidential']),41);self.assertEqual(x['additional_native_returns'],41-len(self.ref['presidential']));self.assertEqual(x['county_totals']['trump'],50556);self.assertEqual(x['county_totals']['harris'],14800)
 def test_unofficial_scope_rejected(self):
  with self.assertRaises(ValueError):mod.parse_text(self.text.replace('OFFICIAL RESULTS','UNOFFICIAL RESULTS'),self.summary,self.ref)
 def test_missing_native_precinct_rejected(self):
  with self.assertRaises(ValueError):mod.parse_text(self.text.replace('Precinct 101','Precinct 999'),self.summary,self.ref)
 def test_changed_candidate_or_method_column_rejected(self):
  with self.assertRaises(ValueError):mod.parse_text(self.text.replace('672          58.03%','673          58.03%',1),self.summary,self.ref)
 def test_independent_county_total_conflict_rejected(self):
  with self.assertRaises(ValueError):mod.parse_text(self.text,self.summary.replace('50,556','50,557',1),self.ref)
 def test_existing_presidential_conflict_rejected(self):
  ref=copy.deepcopy(self.ref);p=next(iter(ref['presidential']));ref['presidential'][p]['trump']+=1
  with self.assertRaises(ValueError):mod.parse_text(self.text,self.summary,ref)
if __name__=='__main__':unittest.main()
