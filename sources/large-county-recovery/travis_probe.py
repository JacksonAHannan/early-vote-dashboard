#!/usr/bin/env python3
"""Inspect official Travis roster in memory; persist only precinct/date aggregates."""
from __future__ import annotations
import argparse, collections, hashlib, io, json, sys, zipfile
from pathlib import Path
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dashboard/scripts'))
from audit_completeness import workbook

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    url='https://votetravis.gov/wp-content/uploads/G26-Voter-Rosters.zip'
    raw=urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=90).read()
    output={'source':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'members':[]}
    previous={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in sorted(n for n in z.namelist() if 'Early Vote' in n and n.endswith('.xlsx')):
            rows=workbook(z.read(name));header=next((i,r) for i,r in enumerate(rows) if 'VUID' in r.values() and 'PCT' in r.values());i,h=header;keys={v:k for k,v in h.items()};ids={}; counts=collections.Counter();duplicates=conflicts=blanks=cross_date=0;raw_rows=0;blank_precinct=collections.Counter()
            for r in rows[i+1:]:
                if not any(r.values()):continue
                raw_rows+=1; id=r.get(keys['VUID'],'').strip();precinct=r.get(keys['PCT'],'').strip().lstrip('0') or 'UNASSIGNED'
                if not id:
                    blanks+=1;blank_precinct[precinct]+=1;continue
                if id in ids:
                    duplicates+=1;conflicts+=ids[id]!=precinct;continue
                if id in previous:cross_date+=1
                ids[id]=precinct;counts[precinct]+=1
            previous.update(ids)
            output['members'].append({'member':name,'raw_nonempty_rows':raw_rows,'unique_voters':len(ids),'identical_repeats':duplicates-conflicts,'conflicting_repeats':conflicts,'blank_ids':blanks,'blank_id_precinct_counts':dict(blank_precinct),'cross_date_ids':cross_date,'counts':dict(sorted(counts.items()))})
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'source':url,'sha256':output['sha256'],'members':[{k:v for k,v in r.items() if k!='counts'} for r in output['members']]}))
if __name__=='__main__':main()
