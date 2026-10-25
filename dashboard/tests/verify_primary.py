#!/usr/bin/env python3
"""Independent aggregate-artifact and geographic-join checks (stdlib only)."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
DATA=json.loads((ROOT/'dashboard/data/primary.json').read_text())
REFERENCE={c['id']:c for c in json.loads((ROOT/'dashboard/data/reference.json').read_text())}
EXPECTED={'dallas':(791,280326,103818),'montgomery':(121,31510,80092),
          'hays':(88,33914,18643),'ellis':(60,18894,25994),
          'mclennan':(95,15093,23727),'madison':(4,419,1887)}

class PrimaryVerification(unittest.TestCase):
    def test_sources_unchanged(self):
        for source in DATA['sources']:
            with self.subTest(source=source['path']):
                self.assertEqual(hashlib.sha256((ROOT/source['path']).read_bytes()).hexdigest(),source['sha256'])

    def test_actual_ballot_totals_and_native_ids(self):
        self.assertEqual(set(DATA['counties']),set(REFERENCE))
        for slug,(n,dem,rep) in EXPECTED.items():
            county=DATA['counties'][slug];precincts=county['precincts']
            native={p for g in REFERENCE[slug]['groups'] for p in g['new']}
            with self.subTest(county=slug):
                self.assertEqual(len(precincts),n)
                self.assertLessEqual(set(precincts),native)
                sums={'primary_dem':0,'primary_rep':0,'primary_total':0}
                for precinct in precincts.values():
                    counts=precinct['counts']
                    self.assertEqual(counts['primary_total'],counts['primary_dem']+counts['primary_rep'])
                    for key,value in counts.items():
                        self.assertIsInstance(value,int);self.assertGreaterEqual(value,0);sums[key]+=value
                self.assertEqual(sums,{'primary_dem':dem,'primary_rep':rep,'primary_total':dem+rep})
                self.assertEqual(county['coverage']['complete_groups'],sum(set(g['new'])<=set(precincts) for g in REFERENCE[slug]['groups']))

    def test_missing_is_not_zero(self):
        self.assertNotIn('1023',DATA['counties']['ellis']['precincts'])
        self.assertEqual(DATA['counties']['ellis']['coverage']['missing_precincts'],['1023'])
        for slug in ['travis','bell','hockley']:
            self.assertEqual(DATA['counties'][slug]['precincts'],{})
            self.assertEqual(DATA['counties'][slug]['coverage']['status'],'unavailable')

    def test_hays_special_ballots_reconcile_without_allocation(self):
        county=DATA['counties']['hays']
        for party,excluded in [('dem',135),('rep',43)]:
            quality=county['coverage']['party_reports'][party]
            self.assertEqual(sum(quality['excluded_records'].values()),excluded)
            self.assertEqual(quality['native_ballots']+excluded,quality['reported_ballots'])

    def test_madison_transcription_tied_to_raw_canvass_and_signed_control(self):
        path=ROOT/'sources/primary-participation/madison-transcription.json'
        transcription=json.loads(path.read_text())
        self.assertEqual(sum(transcription['dem']['precincts'].values()),419)
        self.assertEqual(sum(transcription['rep']['precincts'].values()),1887)
        self.assertEqual(transcription['reconciliation']['value'],2306)
        self.assertEqual(hashlib.sha256((path.parent/transcription['source']).read_bytes()).hexdigest(),transcription['source_sha256'])
        self.assertEqual(hashlib.sha256((path.parent/transcription['reconciliation']['source']).read_bytes()).hexdigest(),transcription['reconciliation']['source_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
