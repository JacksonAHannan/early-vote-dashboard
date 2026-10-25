#!/usr/bin/env python3
"""Independent aggregate-artifact and geographic-join checks (stdlib only)."""
import hashlib
import json
from pathlib import Path
import unittest
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
DATA=json.loads((ROOT/'dashboard/data/primary.json').read_text())
REFERENCE={c['id']:c for c in json.loads((ROOT/'dashboard/data/reference.json').read_text())}
EXPECTED={'dallas':(791,280326,103818),'montgomery':(121,31510,80092),
          'hays':(88,33914,18643),'ellis':(60,18894,25994),
          'mclennan':(95,15093,23727),'madison':(4,419,1887),
          'tarrant':(707,189583,147471),'harris':(1157,366703,200312),
          'bexar':(806,194683,96460),'collin':(270,95808,104149),
          'denton':(252,83001,88195)}

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

    def test_new_counties_reconcile_without_allocating_missing_ballots(self):
        for slug in ['tarrant','harris','bexar','collin','denton']:
            county=DATA['counties'][slug]
            for party in ['dem','rep']:
                report=county['coverage']['party_reports'][party]
                native=sum(p['counts']['primary_'+party] for p in county['precincts'].values())
                self.assertEqual(native+sum(report['excluded_records'].values())+report.get('unlocated_ballots',0),report['reported_ballots'])
        self.assertEqual(DATA['counties']['tarrant']['coverage']['status'],'complete')
        self.assertEqual(DATA['counties']['bexar']['coverage']['status'],'complete')
        self.assertEqual(len(DATA['counties']['harris']['coverage']['missing_precincts']),67)
        self.assertEqual(DATA['counties']['collin']['coverage']['missing_precincts'],['202','266','267'])
        for party,residual in [('dem',15),('rep',11)]:
            report=DATA['counties']['collin']['coverage']['party_reports'][party]
            self.assertEqual(report['unlocated_ballots'],residual)
            self.assertEqual(report['reconciliation'],'precinct_report_short_of_summary')

    def test_versioned_edition_matches_rebuild(self):
        self.assertEqual((ROOT/'dashboard/primary/2026.json').read_bytes(),(ROOT/'dashboard/data/primary.json').read_bytes())

    def test_tarrant_independent_xml_ballot_accounting(self):
        # Independently check every explicit PDF ballot header against a second
        # county publication's complete vote/undervote/overvote accounting.
        # The production data still comes from explicit ballots cast, not votes.
        with zipfile.ZipFile(ROOT/'sources/primary-participation/raw/tarrant-detailxml.zip') as archive:
            election=ET.fromstring(archive.read('detail.xml'))
        contests=[c for c in election.findall('Contest') if c.attrib['text']=='United States Senator']
        self.assertEqual(len(contests),2)
        for contest in contests:
            party=contest.find('Choice').attrib['party'].lower()
            totals=Counter()
            for record in contest.findall('./Choice/VoteType/Precinct')+contest.findall('./VoteType/Precinct'):
                match=re.fullmatch(r'(\d+)(?: - F99)?',record.attrib['name'])
                self.assertIsNotNone(match,record.attrib['name'])
                totals[str(int(match[1]))]+=int(record.attrib['votes'])
            actual={pid:p['counts']['primary_'+party] for pid,p in DATA['counties']['tarrant']['precincts'].items()}
            self.assertEqual(dict(totals),actual)
        combined=Counter()
        for p in election.findall('./VoterTurnout/Precincts/Precinct'):
            match=re.fullmatch(r'(\d+)(?: - F99)?',p.attrib['name'])
            self.assertIsNotNone(match,p.attrib['name'])
            combined[str(int(match[1]))]+=int(p.attrib['ballotsCast'])
        self.assertEqual(combined,{pid:p['counts']['primary_total'] for pid,p in DATA['counties']['tarrant']['precincts'].items()})

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
