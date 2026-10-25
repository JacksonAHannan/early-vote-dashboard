#!/usr/bin/env python3
"""A six-county retained cache must not replace the published March edition.

Run against an isolated native QA server; temporarily changes its legacy fixture.
"""
import json,os
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2]
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8747')
legacy=ROOT/'dashboard/data/primary.json';saved=legacy.read_bytes()
def get(path):
 with urlopen(BASE+path,timeout=120) as r:return json.load(r)
try:
 stale=json.loads(saved)
 for cid in ['bexar','collin','denton','harris','tarrant']:
  stale['counties'][cid]['precincts']={}
 assert sum(len(c['precincts']) for c in stale['counties'].values())==1159
 legacy.write_text(json.dumps(stale))
 raw=get('/api/primary');assert sum(len(c['precincts']) for c in raw['counties'].values())==4351
 view=get('/api/demographic-view?day=3&cohort=matched&view=primary&metric=primary_dem_share')
 assert view['views']['tarrant']['points']
 daily=get('/api/trends?county=tarrant&cohort=matched&view=primary&metric=primary_dem_share')
 assert daily['coverage']['included_counties']==['tarrant']
 print('PASS: six-county legacy cache cannot roll back primary data, regression/buckets or daily participation')
finally:legacy.write_bytes(saved)
