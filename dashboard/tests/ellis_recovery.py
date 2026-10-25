"""Check live recovery after the Ellis stalled-body/cumulative-rollover fix.

Run against the freshly restarted dashboard after capturing ellis-recovery-before.json.
Only aggregate snapshots and provenance are persisted; no raw rosters are retrieved here.
"""
import json,time,os,math
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'analysis/updated-through-2026-10-22/qa'
BASE=os.environ.get('TURNOUT_TEST_URL','http://127.0.0.1:8741')
before=json.loads((OUT/'ellis-recovery-before.json').read_text())
def get(path):
 with urlopen(BASE+path,timeout=15) as r:return json.load(r)
started=time.monotonic()
while True:
 state=get('/api/status');snapshot=get('/api/data')
 if not state['updating'] and snapshot['generated_at']!=before['generated_at']:break
 assert time.monotonic()-started<420,'Live refresh did not finish within seven minutes'
 time.sleep(2)
county=next(c for c in snapshot['counties'] if c['id']=='ellis')
assert county['status']=='current',county['error']
assert county['error'] is None
assert snapshot['through']==before['through']
def same_period(actual,expected):
 if isinstance(expected,float):
  # Last-good JSON round trips can shift ratios by one ULP; counts/IDs stay exact.
  assert math.isclose(actual,expected,rel_tol=1e-14,abs_tol=0),(actual,expected)
 elif isinstance(expected,dict):
  assert actual.keys()==expected.keys()
  for key in expected:same_period(actual[key],expected[key])
 elif isinstance(expected,list):
  assert len(actual)==len(expected)
  for a,b in zip(actual,expected):same_period(a,b)
 else:assert actual==expected,(actual,expected)
same_period(county['periods'],before['county']['periods'])
old_sources=[s for s in before['county']['sources'] if s['date'].startswith('2026')]
for old in old_sources:
 actual=next(s for s in county['sources'] if s['date']==old['date'])
 assert actual==old,'Cached cutoff counts and original provenance must remain intact'
newer=[s for s in county['sources'] if s['date']>snapshot['through']]
assert newer,'The newly published workbook must be retained with its actual later date'
assert all(s['cumulative'] for s in newer)
report={'status':'passed','generated_at':snapshot['generated_at'],'ellis_status':county['status'],'error':county['error'],'requested_cutoff':snapshot['through'],'preserved_cutoffs':[s['date'] for s in old_sources],'downloaded_cutoffs':[{'date':s['date'],'votes':sum(s['counts'].values()),'sha256':s['sha256'],'retrieved_at':s['retrieved_at']} for s in newer],'requested_votes':county['periods'][-1]['county_2026'],'all_nine_sources_current':all(c['status']=='current' for c in snapshot['counties']),'checks':['successful real native/compatible source download and workbook parsing','stale error cleared','exact prior period votes and IDs; ratios agree within floating-point round-trip precision','original cutoff provenance preserved','later cumulative counts not allocated backward']}
(OUT/'ellis-recovery-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
