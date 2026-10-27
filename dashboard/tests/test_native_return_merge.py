"""Reviewed native canvasses must preserve known votes and the exact partition."""
import copy,csv,hashlib,importlib.util,io,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_merge',ROOT/'sources/large-county-recovery/apply_native_returns.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class NativeReturnsMergeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);m.ROOT=self.root;self.folder=self.root/'returns/test';self.folder.mkdir(parents=True)
  self.reference=[{'id':'test','groups':[{'old':['1'],'new':['a']},{'old':['2'],'new':['b']}],'presidential':{'1':{'harris':1,'trump':2}},'references':{}},{'id':'other','presidential':{},'groups':[]}];self.controls={'test':{'harris':4,'trump':6}};self.write([('1',1,2),('2',3,4)])
 def write(self,rows):
  f=io.StringIO();w=csv.writer(f,lineterminator='\n');w.writerow(['precinct','harris','trump']);w.writerows(rows);raw=f.getvalue().encode();(self.folder/'presidential-2024.csv').write_bytes(raw);(self.folder/'source.json').write_text(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'totals':self.controls['test'],'method':'Reviewed final native precinct canvass'}))
 def test_exact_native_merge_preserves_geography_known_votes_and_other_counties(self):
  before=copy.deepcopy(self.reference);actual,changes=m.apply(self.reference,self.controls,self.root/'returns');self.assertEqual(actual[0]['groups'],before[0]['groups']);self.assertEqual(actual[0]['presidential']['1'],before[0]['presidential']['1']);self.assertEqual(actual[1],before[1]);self.assertEqual(self.reference,before);self.assertEqual(changes,[{'county':'test','before':1,'after':2}]);self.assertEqual(m.apply(actual,self.controls,self.root/'returns')[0],actual)
 def test_known_return_conflict_fails(self):
  self.reference[0]['presidential']['1']['harris']=7
  with self.assertRaises(AssertionError):m.apply(self.reference,self.controls,self.root/'returns')
 def test_missing_duplicate_or_foreign_native_ids_fail(self):
  for rows in [[('1',4,6)],[('1',1,2),('1',3,4)],[('1',1,2),('999',3,4)]]:
   self.write(rows)
   with self.assertRaises(AssertionError):m.apply(self.reference,self.controls,self.root/'returns')
 def test_source_tampering_or_county_nonconservation_fails(self):
  (self.folder/'presidential-2024.csv').write_text('tampered')
  with self.assertRaises(AssertionError):m.apply(self.reference,self.controls,self.root/'returns')
  self.write([('1',1,2),('2',3,5)])
  with self.assertRaises(AssertionError):m.apply(self.reference,self.controls,self.root/'returns')
if __name__=='__main__':unittest.main()
