"""Stage explicit native certified 2024 EV ballots + fresh 2026 SOS observations.

No label aliases, inferred zeros, voter records, or production writes. Run from
repo root with uv run --with curl-cffi==0.16.3 python <this file>.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib, importlib.util, json, re, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'analysis/parity-repair/geography/staged/guadalupe-UNAPPROVED-canvass-alternative'
RAW=ROOT/'sources/parity-repair-geography/raw'
sys.path.insert(0,str(ROOT/'dashboard/scripts'))
import collect_expansion_sos as sos
from collect_tarrant_anchor import download
from audit_precinct_coverage import reconstruct

PRECINCT='https://www.guadalupetx.gov/upload/page/0210/docs/2024/11-5-24-GC_General-PrctbyPrct.pdf'
SUMMARY='https://www.guadalupetx.gov/upload/page/0210/docs/2024/11.5.24-GC_General-Official_Results.pdf'


def parse_precinct(text):
    assert all(s in text for s in ['OFFICIAL RESULTS','November 5, 2024','Guadalupe County'])
    rows={}
    for page in text.split('\f'):
        if 'Statistics' not in page:continue
        name=re.search(r'^([0-9]{3})[^\n]*\nStatistics',page,re.M)
        ballot=re.search(r'^Ballots Cast - Total\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$',page,re.M)
        assert name and ballot
        assert re.search(r'Early\s+Absentee\s*\n\s*Voting',page)
        values=[int(x.replace(',','')) for x in ballot.groups()]
        assert values[0]==sum(values[1:]) and name[1] not in rows
        rows[name[1]]=dict(total=values[0],election_day=values[1],early_in_person=values[2],absentee=values[3])
    return rows


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    raw=(RAW/'guadalupe-2024-precinct-results.pdf').read_bytes()
    text=subprocess.run(['pdftotext','-layout','-','-'],input=raw,capture_output=True,check=True).stdout.decode()
    rows=parse_precinct(text)
    project=ROOT/'analysis/county-recovery/admission-additional/project'
    reference=next(r for r in json.loads((project/'dashboard/data/reference.json').read_text()) if r['id']=='guadalupe')
    oldids={p for g in reference['groups'] for p in g['old']};newids={p for g in reference['groups'] for p in g['new']}
    assert rows.keys()==oldids and len(oldids)==76 and len(newids)==78
    summary,headers=download(SUMMARY)
    summarytext=subprocess.run(['pdftotext','-layout','-','-'],input=summary,capture_output=True,check=True).stdout.decode()
    assert all(s in summarytext for s in ['OFFICIAL RESULTS','November 5, 2024','Guadalupe County'])
    total=re.search(r'^Ballots Cast - Total\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$',summarytext,re.M)
    assert total
    totals=[int(v.replace(',','')) for v in total.groups()]
    assert totals==[sum(r[k] for r in rows.values()) for k in ['total','election_day','early_in_person','absentee']]
    assert totals==[85606,14959,67411,3236]
    (RAW/'guadalupe-2024-summary.pdf').write_bytes(summary)
    (RAW/'guadalupe-2024-summary.txt').write_text(summarytext)
    now=datetime.now(timezone.utc).isoformat();digest=hashlib.sha256(raw).hexdigest()
    anchor=dict(county='guadalupe',date='2024-11-01',counts={p:r['early_in_person'] for p,r in sorted(rows.items())},
        source=PRECINCT,sha256=digest,retrieved_at=now,cumulative=True,complete=False,allow_daily_difference=False,
        note='UNAPPROVED ALTERNATIVE: certified native precinct Early Voting ballots include accepted provisional ballots and are NOT ordinary early in-person participation. County reconciliation ordinary early counted ballots 67242 differs from native canvass Early Voting 67411 by 169; the corresponding Election Day difference45 sums to all214 accepted provisionals. Native allocation of provisional ballots is unavailable. Do not admit or substitute this source. Retained solely as an explicitly rejected alternative; no daily allocation, native aliases, inferred zeros or missing-vote allocation.')
    statewide=json.loads((ROOT/'analysis/official-total-gaps/input/statewide.json').read_text())
    county=next(c for c in statewide['counties'] if c['id']=='guadalupe')
    county=json.loads(json.dumps(county))
    for day in county['days']:day['votes_2026']=day['by_method']['in_person']['votes_2026']
    sos.COUNTIES['guadalupe']=county
    dates=[date(2026,10,19)+timedelta(days=i) for i in range(12)]
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda d:sos.fetch('guadalupe',str(d)),dates))
    seen=set();current=[];audits=[]
    for daily,audit,identities in results:
        assert not(seen&identities)
        seen.update(identities);daily['complete']=False;current.append(daily);audits.append(audit)
    old,_=reconstruct([anchor],2024,12,oldids);new,_=reconstruct(current,2026,12,newids)
    paired=[g for g in reference['groups'] if set(g['old'])<=old.keys() and set(g['new'])<=new.keys()]
    assert paired
    for rel,value in [('candidate-reference-NOT-admitted.json',[reference]),('UNAPPROVED-2024-canvass-alternative.json',[anchor]),('cache/guadalupe/2026-series.json',current)]:
        p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2)+'\n')
    for name,path in [('demographics','dashboard/data/demographics.json'),('primary','dashboard/data/primary.json'),('places','dashboard/places/texas.json')]:
        value=json.loads((project/path).read_text());value['counties']={'guadalupe':value['counties']['guadalupe']}
        (OUT/f'{name}-additions.json').write_text(json.dumps(value,separators=(',',':'))+'\n')
    maps=OUT/'maps';maps.mkdir(exist_ok=True);(maps/'guadalupe.geojson').write_bytes((project/'dashboard/data/maps/guadalupe.geojson').read_bytes())
    report=dict(checked_at=now,county='guadalupe',native_2024_precincts=len(oldids),native_2026_precincts=len(newids),groups=len(reference['groups']),current_known_native_cells=len(new.keys()&newids),current_known_native_votes=sum(v for p,v in new.items() if p in newids),paired_precincts=sum(len(g['new']) for g in paired),paired_groups=len(paired),paired_votes_2024=sum(old[p] for g in paired for p in g['old']),paired_votes_2026=sum(new[p] for g in paired for p in g['new']),county_certified_totals=dict(zip(['total','election_day','early_in_person','absentee'],totals)),county_minus_sos_historical=67411-66840,sources=[dict(url=PRECINCT,sha256=digest),dict(url=SUMMARY,sha256=hashlib.sha256(summary).hexdigest(),retrieved_at=now)],current_sources=audits,rows=rows,
        staging_only=True,admission_approved=False,block_reason='Native canvass early mode includes169 accepted provisionals; ordinary early participant/ballot scope is not separable by native precinct.',source_scope='2024 native canvass includes accepted provisional ballots and must not substitute for ordinary early participation. Current2026 native proof remains independently useful. No inferred native aliases or zeros.')
    for key in ['paired_precincts','paired_groups','paired_votes_2024','paired_votes_2026']:
        report['diagnostic_unapproved_'+key]=report.pop(key)
    (OUT/'guadalupe-proof.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['rows','current_sources','sources']},indent=2))

if __name__=='__main__':main()
