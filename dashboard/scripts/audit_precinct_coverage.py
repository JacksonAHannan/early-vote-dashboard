#!/usr/bin/env python3
"""Independently reconstruct paired cumulative precinct coverage from aggregates.

No voter records or production matching imports. A pinned API snapshot contains
qualified source observations, geographic groups and published coverage. Run with
--require-complete to reproduce the incompleteness symptom as an assertion.
"""
import argparse,collections,csv,json
from datetime import date,timedelta
from pathlib import Path
START={2024:date(2024,10,21),2026:date(2026,10,19)}
def exact(sources,year,day,cumulative):
 stamp=str(START[year]+timedelta(days=day-1));rows=[s for s in sources if s['date']==stamp and s.get('cumulative',False)==cumulative]
 return max(rows,key=lambda s:s['retrieved_at']) if rows else None

def reconstruct(sources,year,day,universe):
 """Return count map plus fully corroborated entire-roster status, or missing."""
 cumulative=exact(sources,year,day,True)
 if cumulative:
  counts={p:n for p,n in cumulative['counts'].items() if p not in cumulative.get('unavailable_precincts',[])};complete=cumulative.get('complete',False) and not cumulative.get('unavailable_precincts') and all(n==0 or p in universe for p,n in counts.items())
  if complete:counts.update({id:0 for id in universe if id not in counts})
  return counts,complete
 daily=exact(sources,year,day,False)
 if not daily:return {},False
 now={p:n for p,n in daily['counts'].items() if p not in daily.get('unavailable_precincts',[])};complete=daily.get('complete',False) and not daily.get('unavailable_precincts') and all(n==0 or p in universe for p,n in now.items())
 if complete:now.update({id:0 for id in universe if id not in now})
 if day==1:return now,complete
 before,prior_complete=reconstruct(sources,year,day-1,universe)
 result={id:before.get(id,0)+now.get(id,0) for id in before.keys()|now.keys() if (prior_complete or id in before) and (complete or id in now)}
 return result,complete and prior_complete

def audit(snapshot,days=5,verify_published=True):
 rows=[];groups=[];summaries=[]
 for day in range(1,min(days,snapshot['days'])+1):
  totals=collections.Counter()
  for county in snapshot['counties']:
   ref=county['reference_groups'];oldids={id for g in ref for id in g['old']};newids={id for g in ref for id in g['new']}
   old,_=reconstruct(county['sources'],2024,day,oldids);new,_=reconstruct(county['sources'],2026,day,newids)
   stats=collections.Counter(total_precincts=len(newids),total_groups=len(ref))
   period=next((p for p in county['periods'] if p['day']==day),None)
   for index,g in enumerate(ref):
    missing_old=[id for id in g['old'] if id not in old];missing_new=[id for id in g['new'] if id not in new]
    cause='both_years' if missing_old and missing_new else 'historical_2024' if missing_old else 'current_2026' if missing_new else 'available'
    stats[cause+'_precincts']+=len(g['new']);stats[cause+'_groups']+=1
    if cause=='available' and g.get('bucket') is None:
     stats['partisan_bucket_excluded_precincts']+=len(g['new'])
     stats['mixed_margin_precincts' if g.get('reason')=='Mixed margin bands' else 'presidential_reference_missing_or_tied_precincts']+=len(g['new'])
    if cause!='available':groups.append({'county':county['id'],'day':day,'group_index':index,'precincts_2026':g['new'],'precincts_2024':g['old'],'missing_2024':missing_old,'missing_2026':missing_new,'cause':cause})
   if period and verify_published:
    assert stats['available_precincts']==period['coverage']['available_precincts'],(county['id'],day,'coverage')
    assert stats['available_groups']==period['coverage']['available_groups'],(county['id'],day,'groups')
    assert sum(sum(old[id] for id in g['old']) for g in ref if all(id in old for id in g['old']) and all(id in new for id in g['new']))==period['county_2024'],(county['id'],day,'baseline')
    assert sum(sum(new[id] for id in g['new']) for g in ref if all(id in old for id in g['old']) and all(id in new for id in g['new']))==period['county_2026'],(county['id'],day,'current')
   elif verify_published:assert stats['available_groups']==0,(county['id'],day,'missing period')
   stats['missing_precincts']=len(newids)-stats['available_precincts'];stats['wholly_unavailable_counties']=int(stats['available_groups']==0);stats['partial_counties']=int(0<stats['available_precincts']<len(newids))
   rows.append({'county':county['id'],'day':day,**dict(stats)});totals.update(stats)
  summaries.append({'day':day,**dict(totals)})
 return {'generated_at':snapshot['generated_at'],'verified_against_published':verify_published,'summaries':summaries,'counties':rows,'unavailable_groups':groups,'method':'Exact dated cumulative sources, otherwise independently accumulated known daily observations; complete publisher controls alone establish absent-row zeros. Published-pair reconciliation is checked when verified_against_published is true; source coverage is separate from partisan classification.'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--require-complete',action='store_true');a=p.parse_args()
 result=audit(json.loads(a.snapshot.read_text()));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result['summaries'],indent=2))
 if a.require_complete:assert not any(s['missing_precincts'] for s in result['summaries']),'Days 1–5 still have unpaired precinct geography; see attributed county/group report'
if __name__=='__main__':main()
