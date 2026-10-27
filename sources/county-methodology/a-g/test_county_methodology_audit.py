import copy,importlib.util,json,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'audit_counties.py';spec=importlib.util.spec_from_file_location('county_audit',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
SHA='a'*64
class AuditTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.data=self.root/'dashboard/data';self.data.mkdir(parents=True)
  self.catalog={f'county{i:03}':{'name':f'County {i}','fips':str(48000+i)}for i in range(254)}
  self.write('county-reference.json',{'counties':self.catalog})
  self.ref={'id':'county000','groups':[{'old':[str(i)],'new':[str(i)]}for i in range(1,4)],'presidential':{'1':{'harris':2,'trump':1},'2':{'harris':0,'trump':0}}}
  self.write('reference.json',[self.ref]);self.write('completeness.json',{'controls':[{'county':'county000','year':2026,'date':'2026-10-19','daily':10,'cumulative':10,'scope':'in_person','completed':True,'source':'https://official.example/control','sha256':'b'*64}]})
  def source(year,counts,**extra):return {'county':'county000','date':f'{year}-10-'+('21'if year==2024 else'19'),'counts':counts,'complete':False,'source':'https://official.example/roster','sha256':SHA,'retrieved_at':'2026-10-27T00:00:00+00:00','note':'Anonymous aggregate',**extra}
  self.sources=[source(2024,{'1':1,'2':1,'3':1}),source(2026,{'1':2,'2':0,'3':0,'FOREIGN':1})]
  groups=[{'old':[str(i)],'new':[str(i)],'bucket':0 if i==1 else None,'harris':2 if i==1 else 0,'trump':1 if i==1 else 0,'reason':''}for i in range(1,4)]
  self.snapshot={'generated_at':'2026-10-27T00:00:00+00:00','through':'2026-10-19','days':1,'counties':[{'id':'county000','name':'County 0','reference_groups':groups,'sources':self.sources,'periods':[{'day':1,'coverage':{'available_precincts':3,'available_groups':3},'county_2024':3,'county_2026':2}]}]}
  folder=self.data/'cache/county001';folder.mkdir(parents=True);(folder/'2026-series.json').write_text(json.dumps([source(2026,{'7':4})]))
 def write(self,name,obj):(self.data/name).write_text(json.dumps(obj))
 def run_audit(self,**kw):return mod.build(self.root,self.snapshot,**kw)
 def county(self,result,cid='county000'):return next(r for r in result['counties']if r['county']==cid)
 def test_all254_including_unadmitted_and_retained_source(self):
  x=self.run_audit();self.assertEqual(len(x['counties']),254);r=self.county(x,'county001');self.assertFalse(r['admitted']);self.assertEqual(r['sources'][0]['total_votes'],4);self.assertIsNone(r['sources'][0]['unknown_positive_labels']);self.assertEqual(r['evidence_freshness'],'retained_only')
 def test_unknown_positive_not_zero_and_control_mismatch_not_certified(self):
  s=self.county(self.run_audit())['sources'][1];self.assertEqual(s['unknown_positive_labels'],{'FOREIGN':1});self.assertFalse(s['omitted_zero_certified']);self.assertEqual(s['controls'][0]['difference'],-7)
 def test_quarantine_overrides_count_and_changes_paired_coverage(self):
  self.sources[1]['unavailable_precincts']=['1'];p=self.snapshot['counties'][0]['periods'][0];p['coverage']={'available_precincts':2,'available_groups':2};p['county_2024']=2;p['county_2026']=0;r=self.county(self.run_audit());self.assertEqual(r['coverage_by_day'][0]['available_precincts'],2);self.assertEqual(r['sources'][1]['quarantined_precincts'],['1'])
 def test_future_source_excluded_from_comparison_and_flagged(self):
  future=copy.deepcopy(self.sources[1]);future['date']='2026-10-20';future['counts']={'1':999};self.sources.append(future);r=self.county(self.run_audit());self.assertFalse(r['sources'][-1]['within_comparison_window']);self.assertEqual(r['coverage_by_day'][0]['available_precincts'],3)
 def test_hash_provenance_and_absent_vs_tied_classification(self):
  r=self.county(self.run_audit());self.assertEqual(r['sources'][0]['sha256'],SHA);self.assertTrue(r['sources'][0]['valid_sha256']);self.assertEqual(r['classification']['missing_native_2024_ids'],['3']);self.assertEqual(r['classification']['tied_native_2024_ids'],['2'])
 def test_bad_catalog_duplicate_snapshot_and_unknown_review_rejected(self):
  self.snapshot['counties'].append(copy.deepcopy(self.snapshot['counties'][0]))
  with self.assertRaises(ValueError):self.run_audit()
  self.snapshot['counties'].pop();self.write('county-reference.json',{'counties':dict(list(self.catalog.items())[:-1])})
  with self.assertRaises(ValueError):self.run_audit()
 def test_partial_review_coverage_and_unknown_ids_rejected(self):
  p=self.root/'reviews.json';p.write_text(json.dumps({'counties':[{'county':'not_a_county','disposition':'healthy'}]}))
  with self.assertRaises(ValueError):self.run_audit(reviews=[p])
  p.write_text(json.dumps({'counties':[{'county':'county000','disposition':'healthy'}]}))
  with self.assertRaises(ValueError):self.run_audit(reviews=[p])
 def test_all_county_reviews_retained_and_fresh_distinguished(self):
  rows=[{'county':cid,'disposition':'healthy','next_action':'Continue strict source checks.'}for cid in self.catalog];rows[0]['fresh_evidence']={'source':'https://official.example/independently-checked','sha256':SHA};p=self.root/'reviews.json';p.write_text(json.dumps({'county_count':254,'counties':rows}));x=self.run_audit(reviews=[p]);self.assertEqual(self.county(x)['evidence_freshness'],'freshly_verified_review');self.assertEqual(self.county(x,'county001')['evidence_freshness'],'retained_only')
 def test_demographics_primary_place_missing_vs_zero_denominators(self):
  record=lambda value:{'counts':{'vap':value,'primary_total':value}}
  self.write('demographics.json',{'counties':{'county000':{'precincts':{'1':record(10),'2':record(0)}}}})
  self.write('primary.json',{'counties':{'county000':{'precincts':{}}}})
  places=self.root/'dashboard/places';places.mkdir();(places/'texas.json').write_text(json.dumps({'counties':{'county000':{'precincts':{'1':record(10),'2':record(0),'3':record(0)}}}}))
  r=self.county(self.run_audit());v=r['view_coverage'];self.assertEqual(v['demographics']['missing_records'],1);self.assertEqual(v['demographics']['zero_denominator'],1);self.assertEqual(v['primary']['missing_records'],3);self.assertEqual(v['place']['missing_records'],0);self.assertEqual(v['place']['zero_denominator'],2);self.assertFalse(r['all_views_complete'])
 def test_primary_audit_uses_the_active_versioned_edition_before_legacy_cache(self):
  self.write('primary.json',{'counties':{'county000':{'precincts':{}}}})
  folder=self.root/'dashboard/primary';folder.mkdir()
  (folder/'2026.json').write_text(json.dumps({'counties':{'county000':{'precincts':{'1':{'counts':{'primary_total':20}}}}}}))
  primary=self.county(self.run_audit())['view_coverage']['primary']
  self.assertEqual(primary['records_present'],1);self.assertEqual(primary['positive_denominator'],1)
  self.assertEqual(primary['path'],str(folder/'2026.json'))
 def test_empty_primary_prevents_all_view_healthy_claim(self):
  self.write('primary.json',{'counties':{'county000':{'precincts':{}}}})
  r=self.county(self.run_audit());self.assertFalse(r['all_views_complete']);self.assertIn('primary',r['view_gaps'])
 def test_duplicate_json_catalog_keys_and_review_declared_counts_rejected(self):
  p=self.root/'reviews.json';p.write_text(json.dumps({'county_count':254,'counties':[{'county':'county000'}]}))
  with self.assertRaises(ValueError):self.run_audit(reviews=[p])
  path=self.data/'county-reference.json';text=path.read_text();path.write_text(text.replace('"county001":','"county000":',1))
  with self.assertRaises(ValueError):self.run_audit()
 def test_explicit_staged_native_universe_does_not_admit_county(self):
  staged=copy.deepcopy(self.ref);staged['id']='county001';p=self.root/'staged.json';p.write_text(json.dumps([staged]));r=self.county(self.run_audit(staged=[p]),'county001');self.assertFalse(r['admitted']);self.assertTrue(r['classification']['native_universe_known']);self.assertEqual(r['sources'][0]['unknown_positive_labels'],{'7':4})
 def test_data_and_input_artifacts_cannot_be_output_targets(self):
  with self.assertRaises(ValueError):mod.validate_output_paths(self.root,[self.data/'latest.json'],[])
  p=self.root/'snapshot.json'
  with self.assertRaises(ValueError):mod.validate_output_paths(self.root,[p],[p])
  mod.validate_output_paths(self.root,[self.root/'analysis/audit.json'],[p])
 def test_completed_control_agreement_does_not_promote_source(self):
  self.sources[1]['counts']={'1':10,'2':0,'3':0};self.snapshot['counties'][0]['periods'][0]['county_2026']=10;s=self.county(self.run_audit())['sources'][1];self.assertTrue(s['controls'][0]['exact_completed_match']);self.assertFalse(s['omitted_zero_certified'])
if __name__=='__main__':unittest.main()
