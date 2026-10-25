"""Independent Python audit against independently fetched county/state aggregates."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[2]
SOURCES=ROOT/'sources/refresh-2026-10-23'

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        result={}
        for r in csv.DictReader(f):
            key=str(int(r['precinct'])) if r['precinct'].isdigit() else r['precinct'].upper()
            result[key]=result.get(key,0)+int(r['early_vote'])
        return result

def independent_counts(county,year,day):
    end=(19 if year==2026 else 21)+day-1
    if county in ['travis','dallas','montgomery']:
        return read(SOURCES/f'county-a/{county}-cumulative-{year}-10-{end}.csv')
    if county=='hays' and year==2026:
        return read(SOURCES/f'county-b/hays-county-cumulative-2026-10-{end}.csv')
    if county=='ellis' and year==2026:
        assert day==4
        return read(SOURCES/'county-b/ellis-county-2026-10-22.csv')
    folder='county-b' if county in ['bell','hays','ellis'] else 'county-c'
    prefix=f'{county}-' if folder=='county-b' else f'{county}-turnout-'
    result={}
    for date in range(19 if year==2026 else 21,end+1):
        for p,v in read(SOURCES/f'{folder}/{prefix}{year}-10-{date}.csv').items():
            result[p]=result.get(p,0)+v
    return result

def classify(p):
    h,t=p['harris'],p['trump']
    if h==t:return None
    m=abs(h-t)*100
    band=2 if m>=30*(h+t) else 1 if m>=15*(h+t) else 0
    return 2-band if h>t else 3+band

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=ROOT/'dashboard/data/latest.json')
    snapshot=json.loads(parser.parse_args().snapshot.read_text())
    # Revisions are independent fresh-download deltas against the preserved audit
    # CSVs. Only apply an explicitly recorded revision to identical source bytes.
    revisions={}
    applied=[]
    for path in sorted(SOURCES.glob('county-*/*-revision-*.json')):
        audit=json.loads(path.read_text())
        for entry in audit['days']:
            if entry.get('original_audit_delta_by_precinct'):
                revisions[(audit['county'],entry['date'],entry['sha256'])]=(entry,path)

    refs={r['id']:r for r in json.loads((ROOT/'dashboard/data/reference.json').read_text())}
    total_buckets=0;total_periods=0;totals={}
    assert snapshot['days']==4 and snapshot['through']=='2026-10-22'
    for county in snapshot['counties']:
        assert county['status']=='current',(county['id'],county['error'])
        ref=refs[county['id']]
        for item in ref['references'].values():assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
        for period in county['periods']:
            day=period['day'];old=independent_counts(county['id'],2024,day);new=independent_counts(county['id'],2026,day)
            for source in county['sources']:
                if not source['date'].startswith('2026') or int(source['date'][-2:])>18+day:continue
                revision=revisions.get((county['id'],source['date'],source['sha256']))
                if revision:
                    entry,path=revision
                    for key,delta in entry['original_audit_delta_by_precinct'].items():new[key]=new.get(key,0)+delta
                    if str(path.relative_to(ROOT)) not in applied:applied.append(str(path.relative_to(ROOT)))
            assert sum(old.values())==period['county_2024'],(county['id'],day,'old')
            assert sum(new.values())==period['county_2026'],(county['id'],day,'new')
            for year,counts in [(2024,old),(2026,new)]:
                safe={}
                ds=[s for s in county['sources'] if s['date'].startswith(str(year))]
                cumul=[s for s in ds if s.get('cumulative') and s['date'].endswith(f'-{(19 if year==2026 else 21)+day-1}')]
                if cumul:safe=cumul[0]['counts']
                else:
                    for d in ds:
                        if int(d['date'][-2:])<=(19 if year==2026 else 21)+day-1:
                            for p,v in d['counts'].items():safe[p]=safe.get(p,0)+v
                assert {p:v for p,v in safe.items() if v}=={p:v for p,v in counts.items() if v},(county['id'],day,year,'precinct totals differ')
            expected=[{'matched':[0,0,0],'unchanged':[0,0,0]} for _ in range(6)]
            exact={tuple(p) for p in ref['exact_pairs']}
            assert len(period['groups'])==len(ref['groups'])
            for g,reported in zip(ref['groups'],period['groups']):
                assert g['old']==reported['old'] and g['new']==reported['new']
                v24=sum(old.get(p,0) for p in g['old']);v26=sum(new.get(p,0) for p in g['new'])
                assert (v24,v26)==(reported['votes_2024'],reported['votes_2026'])
                bands={classify(ref['presidential'][p]) if p in ref['presidential'] else None for p in g['old']}
                b=next(iter(bands)) if len(bands)==1 and None not in bands else None
                assert b==reported['bucket']
                if b is None:continue
                strict=len(g['old'])==len(g['new'])==1 and (g['old'][0],g['new'][0]) in exact
                for method in ['matched']+(['unchanged'] if strict else []):
                    target=expected[b][method];target[0]+=1;target[1]+=v24;target[2]+=v26
            for bucket,expected_bucket in zip(period['buckets'],expected):
                for method in ['matched','unchanged']:
                    c=bucket[method];n,v24,v26=expected_bucket[method]
                    assert (c['groups'],c['votes_2024'],c['votes_2026'])==(n,v24,v26)
                    assert c['ratio'] is None if not v24 else math.isclose(c['ratio'],v26/v24,rel_tol=1e-14)
                    total_buckets+=1
            total_periods+=1
        last=county['periods'][-1];totals[county['id']]=[last['county_2024'],last['county_2026']]
    hashes=json.loads((ROOT/'dashboard/data/original-hashes.json').read_text())
    for path,digest in hashes.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path
    report={'counties':len(snapshot['counties']),'periods':total_periods,'bucket_cohorts':total_buckets,'preserved_artifacts':len(hashes),'totals_2024_2026':totals,'status':'passed','independently_verified_source_revisions':applied,'generated_at':snapshot['generated_at']}
    output=ROOT/'analysis/updated-through-2026-10-22';output.mkdir(exist_ok=True,parents=True)
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
