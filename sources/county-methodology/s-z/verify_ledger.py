"""Independent checks for the53county pinned methodology review artifacts."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]

class CountyLedger(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.ledger=json.loads((ROOT/'analysis/county-methodology/s-z/ledger.json').read_text())
  cls.baseline=json.loads((ROOT/'analysis/county-methodology/baseline.json').read_text())
  cls.assigned=json.loads((ROOT/'analysis/county-methodology/s_z-counties.json').read_text())
 def test_exact_assignment_and_pinned_baseline(self):
  self.assertEqual([r['county'] for r in self.ledger['counties']],self.assigned)
  self.assertEqual(len(self.assigned),53)
  self.assertEqual(self.ledger['baseline_sha256'],hashlib.sha256((ROOT/'analysis/county-methodology/baseline.json').read_bytes()).hexdigest())
 def test_each_county_has_diagnosis_provenance_and_action(self):
  for row in self.ledger['counties']:
   with self.subTest(county=row['county']):
    self.assertIn(row['disposition'],{'healthy','real_source_gap','provenfix','rejected'})
    self.assertTrue(row['diagnosis']);self.assertTrue(row['next_action']);self.assertTrue(row['observations'])
    for observation in row['observations']:
     self.assertTrue(observation['source'].startswith('https://'));self.assertRegex(observation['sha256'],r'^[0-9a-f]{64}$')
 def test_every_published_observation_conserves_retained_counts(self):
  baseline={c['id']:c for c in self.baseline['counties']}
  for row in self.ledger['counties']:
   if not row['admitted']:continue
   known={(s['date'],s.get('cumulative',False),s['sha256']):s for s in baseline[row['county']]['sources']}
   for observation in row['observations']:
    with self.subTest(county=row['county'],date=observation['date'],cumulative=observation['cumulative']):
     source=known[(observation['date'],observation['cumulative'],observation['sha256'])]
     self.assertEqual(observation['votes'],sum(source['counts'].values()))
     self.assertEqual(observation['observed_labels'],len(source['counts']))
 def test_mail_only_and_empty_fresh_sources_never_certify_zero(self):
  for p in json.loads((ROOT/'analysis/county-methodology/s-z/fresh-sos-probes.json').read_text()):
   if p['status'] in ['no_in_person_rows','official_empty_body']:
    self.assertNotIn('complete',p);self.assertNotIn('zero_evidence',p)
 def test_unadmitted_ambiguous_codes_stay_rejected(self):
  rows={r['county']:r for r in self.ledger['counties']}
  for id in ['taylor','wood','upton']:self.assertFalse(rows[id]['admitted']);self.assertEqual(rows[id]['disposition'],'rejected')

if __name__=='__main__':unittest.main()
