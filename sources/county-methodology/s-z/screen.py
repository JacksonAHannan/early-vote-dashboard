#!/usr/bin/env python3
"""Reproduce individual S-Z county methodology screens from the pinned API."""
import collections,hashlib,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
ORIGINAL=ROOT.parent/'texas-early-vote-2026-11-03'
ASSIGNED=ROOT/'analysis/county-methodology/s_z-counties.json'
BASE=ROOT/'analysis/county-methodology/baseline.json'
COVERAGE=ROOT/'analysis/county-methodology/coverage-before.json'


def main():
 assigned=json.loads(ASSIGNED.read_text());base=json.loads(BASE.read_text());coverage=json.loads(COVERAGE.read_text());by={c['id']:c for c in base['counties']};co={(c['county'],c['day']):c for c in coverage['counties']};catalog=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())['counties'];staged=json.loads((ROOT/'analysis/county-recovery/admission-additional/project/dashboard/data/reference.json').read_text());stage={c['id']:c for c in staged};controls=json.loads((ROOT/'dashboard/data/completeness.json').read_text())['controls'];ctrl={(c['county'],c['date']):c for c in controls if c.get('completed') and c.get('scope')=='in_person'}
 ledger=[]
 for id in assigned:
  c=by.get(id);r=dict(county=id,name=catalog[id]['name'],fips=catalog[id]['fips'],admitted=c is not None,baseline_generated_at=base['generated_at'],review='Individual source/date/native-ID/control/coverage and classification review of retained evidence; freshness separately marked.')
  if c:
   groups=c['reference_groups'];sources=c['sources'];rows=[co[id,d] for d in range(1,base['days']+1)];univ={2024:{p for g in groups for p in g['old']},2026:{p for g in groups for p in g['new']}}
   r['geography']=dict(groups=len(groups),old_native_precincts=len(univ[2024]),new_native_precincts=len(univ[2026]));r['coverage_by_day']=rows
   r['classification']=dict(missing_or_tied_groups=sum(g['reason']=='Missing or tied presidential return' for g in groups),mixed_groups=sum(g['reason']=='Mixed margin bands' for g in groups),classified_groups=sum(g['bucket'] is not None for g in groups));gaps=[g for g in coverage['unavailable_groups'] if g['county']==id];r['gap_causes']=dict(collections.Counter(g['cause'] for g in gaps));r['missing_native_ids']=dict(old=sorted({p for g in gaps for p in g['missing_2024']}),new=sorted({p for g in gaps for p in g['missing_2026']}))
  else:
   ref=stage[id];groups=ref['groups'];univ={2024:{p for g in groups for p in g['old']},2026:{p for g in groups for p in g['new']}};sources=[]
   for year,folder in [(2024,'history-cache'),(2026,'cache')]:
    path=ORIGINAL/f'dashboard/data/{folder}/{id}/{year}-series.json'
    if path.exists():sources.extend(json.loads(path.read_text()))
   r['geography']=dict(groups=len(groups),old_native_precincts=len(univ[2024]),new_native_precincts=len(univ[2026]),staged_reference_path=str(ROOT/'analysis/county-recovery/admission-additional/project/dashboard/data/reference.json'));r['coverage_by_day']=[];r['classification']=dict(presidential_native_precincts=len(ref['presidential']));r['gap_causes']={'unadmitted_native_identifier_mismatch':1}
  provenance=[]
  for s in sources:
   year=int(s['date'][:4]);outside={p:n for p,n in s['counts'].items() if p not in univ[year] and n};count=sum(s['counts'].values());control=ctrl.get((id,s['date']));expected=control.get('cumulative' if s.get('cumulative') else 'daily') if control else None
   provenance.append(dict(date=s['date'],cumulative=s.get('cumulative',False),source=s['source'],sha256=s['sha256'],retrieved_at=s.get('retrieved_at'),votes=count,observed_labels=len(s['counts']),unmapped_positive=outside,unavailable_precincts=s.get('unavailable_precincts',[]),complete=s.get('complete',False),independent_in_person_control=expected,delta=count-expected if expected is not None else None,zero_evidence=s.get('zero_evidence'),allow_daily_difference=s.get('allow_daily_difference',True),source_note=s.get('note','')))
  r['observations']=provenance;r['checked_observations']=len(provenance);r['source_dates_missing']={str(y):[d for d in range(1,9) if not any(s['date']==f'{y}-10-{(20 if y==2024 else 18)+d:02d}' for s in sources)] for y in [2024,2026]};r['official_source_urls']=sorted({s['source'] for s in sources});r['retained_evidence_only']=True
  if not c:r['disposition']='rejected';r['diagnosis']='County is catalogued but unadmitted because reported residence precinct IDs do not yet have an independently proved map to the staged native geometry.';r['next_action']={'taylor':'Find official 2024 native precinct report proving literal trailing-dot labels are formatting only; retain every digit and reject nonliteral/ambiguous suffixes.','wood':'Seek official decimal-subprecinct to native precinct crosswalk; no truncation and no inferred allocation.','upton':'Find official current 1–7 reported-label crosswalk to 1-1/1-5/2-2/2-6/3-3/4-4 native boundaries; do not guess parent numbers.'}[id]
  elif any(x['missing_precincts'] for x in rows):r['disposition']='real_source_gap';r['diagnosis']='Retained dated sources leave specific cumulative native groups unpaired; observed groups remain included independently each day. No county-wide exclusion or missing-row zero fill is warranted.';r['next_action']='Check official reports for specifically attributed missing dates/IDs; seek native returns separately where classification is incomplete; preserve scope and unknowns until corroborated.'
  elif r['classification']['missing_or_tied_groups']:
   r['disposition']='real_source_gap';r['diagnosis']='All current geographic turnout comparisons are available; remaining exclusion is missing/tied presidential reference classification, not missing turnout.';r['next_action']='Seek certified native 2024 presidential results with all-native and county-total conservation; retain genuine ties/zero-return/mixed groups.'
  else:r['disposition']='healthy';r['diagnosis']='Every admitted native geography group is paired on every published day; any mixed-band exclusion is an explicit classification rule, not a missing turnout record.';r['next_action']='Retain existing source/date/method/cell-level qualification; monitor later publisher revisions without adding inferred zeros.'
  notes_path=ROOT/'sources/county-methodology/s-z/review-notes.json'
  if notes_path.exists():
   notes=json.loads(notes_path.read_text()).get(id,{})
   for key in ['retained_evidence_only','fresh_findings','candidate_review','next_action','disposition']:
    if key in notes:r[key]=notes[key]
  ledger.append(r)
 out=dict(schema_version=1,assignment_count=len(assigned),baseline_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),coverage_sha256=hashlib.sha256(COVERAGE.read_bytes()).hexdigest(),counties=ledger)
 dest=ROOT/'analysis/county-methodology/s-z/ledger.json';dest.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(dict(counties=len(ledger),observations=sum(r['checked_observations'] for r in ledger),dispositions=dict(collections.Counter(r['disposition'] for r in ledger))),indent=2))
if __name__=='__main__':main()
