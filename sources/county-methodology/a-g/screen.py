#!/usr/bin/env python3
"""County-by-county audit of frozen anonymous observations; never infer missing zeros."""
from collections import Counter
from datetime import date,timedelta
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
P=ROOT/'analysis/county-methodology'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assigned=json.loads((P/'a_g-counties.json').read_text()); baseline=json.loads((P/'baseline.json').read_text()); coverage=json.loads((P/'coverage-before.json').read_text()); catalog=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())['counties']; refs={r['id']:r for r in json.loads((P/'a-g/reference-before.json').read_text())}; staged={r['id']:r for r in json.loads((ROOT/'analysis/county-recovery/admission-additional/project/dashboard/data/reference.json').read_text())}; bs={r['id']:r for r in baseline['counties']}; out=[]
 controls=json.loads((ROOT/'dashboard/data/completeness.json').read_text())['controls']
 for cid in assigned:
  ref=refs.get(cid,staged.get(cid)); old=set(p for g in ref['groups'] for p in g['old']);new=set(p for g in ref['groups'] for p in g['new']); county=bs.get(cid); series=county['sources'] if county else sum([json.loads((ROOT/f'dashboard/data/cache/{cid}/{y}-series.json').read_text()) for y in [2024,2026]],[])
  cv=sorted([r for r in coverage['counties'] if r['county']==cid],key=lambda r:r['day']); missing_native=sorted(old-set(ref['presidential'])); observations=[]
  for s in series:
   universe=old if s['date'][:4]=='2024' else new; unknown={p:v for p,v in s['counts'].items() if p not in universe and v>0};observations.append({k:s.get(k) for k in ['date','kind','complete','source','sha256','retrieved_at','note','unavailable_precincts'] if k in s}|{'total':sum(s['counts'].values()),'native_positive_precincts':sum(p in universe and v>0 for p,v in s['counts'].items()),'native_explicit_zero_precincts':sum(p in universe and v==0 for p,v in s['counts'].items()),'unknown_positive_labels':unknown,'missing_native_labels':sorted(universe-set(s['counts']))})
  dates={s['date'] for s in series if not s.get('cumulative')}; missing_dates=[str(date(2026,10,19)+timedelta(days=i)) for i in range(8) if str(date(2026,10,19)+timedelta(days=i)) not in dates]; latest=cv[-1] if cv else {}; deficient=[x for x in cv if x.get('missing_precincts',0)>0]; unknown=[x for x in observations if x['unknown_positive_labels']]; excludes=max([r.get('presidential_reference_missing_or_tied_precincts',0) for r in cv] or [0]); diagnosis=[]
  if not county: diagnosis.append('Not admitted: no proved both-cycle native common group in retained source edition.')
  if missing_dates:diagnosis.append('Current daily source date(s) absent; no zero fill: '+', '.join(missing_dates)+'.')
  if deficient:diagnosis.append('Per-day paired coverage incomplete; explicit missing cells remain unknown, with strict completed-source zero qualification.')
  if unknown:diagnosis.append('Positive source labels outside native universe prohibit blanket omitted-precinct zero certification.')
  if missing_native:diagnosis.append(f'{len(missing_native)} historical native precincts lack a unique native presidential reference; classification loss is distinct from turnout availability.')
  if any(r.get('mixed_margin_precincts',0)>0 for r in cv):diagnosis.append('Mixed historical partisan groups remain excluded by geography contract; do not assign county averages.')
  if not diagnosis:diagnosis=['All eight dates have full paired native coverage and classified references in frozen edition; retain strict per-day source/control checks.']
  action=[]
  if not county:action.append('Obtain official subdivision-to-native precinct relationship before admitting staged geometry; reject numeric truncation.')
  if missing_dates:action.append('Retrieve an explicitly dated ordinary in-person native county publication for missing dates and independently reconcile control.')
  if deficient:action.append('Check dated county ordinary-IP roster/control revision and explicit final2024/current-cumulative zero certificates, retaining known subsets.')
  if missing_native:action.append('Replace only missing/identically corroborated presidential references using full-universe certified native canvass and independent candidate totals.')
  if not action:action=['Continue hourly dated-source refresh and retain raw-hash provenance; no geography or zero-policy change justified.']
  row={'county':cid,'name':catalog[cid]['name'],'admitted':bool(county),'baseline_generated_at':baseline['generated_at'],'native_2024':len(old),'native_2026':len(new),'coverage_by_day':cv,'presidential_native_missing':missing_native,'source_observations':observations,'independent_controls':[x for x in controls if x['county']==cid],'diagnosis':diagnosis,'disposition':'real_source_gap' if deficient or not county or missing_native else 'healthy','next_action':action,'review':'Every assigned county individually screened against its complete eight-day paired coverage, all retained source dates, unknown-positive labels, presidential universe, and independent controls.'}
  out.append(row)
 result={'schema_version':1,'baseline_sha256':sha(P/'baseline.json'),'coverage_sha256':sha(P/'coverage-before.json'),'generated_at':baseline['generated_at'],'assigned_counties':len(assigned),'reviewed_counties':len(out),'counties':out};target=P/'a-g/ledger.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'counties':len(out),'dispositions':dict(Counter(x['disposition'] for x in out)),'ledger':str(target)}))
if __name__=='__main__':main()
