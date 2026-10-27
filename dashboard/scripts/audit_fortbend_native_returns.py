#!/usr/bin/env python3
"""Verify 2024 Fort Bend native presidential returns against two official PDFs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
BASE='https://www.fortbendcountytx.gov/sites/default/files/document-central/document-central/elections-documents/elections-results/2024/'
CANVASS=BASE+'FBC-Canvass2.pdf'
PRECINCT=BASE+'FBC-Precinct-Reports3.pdf'


def parse_canvass(text):
    if not all(s in text for s in ['OFFICIAL RESULTS','November 5, 2024','Fort Bend County Precinct Canvass Report']):raise ValueError('wrong or unofficial canvass')
    rows={};printed=None
    for page in text.split('\f'):
        if not all(s in page for s in ['President / Vice President','REP Donald J.','DEM Kamala','175 of 175 Precincts Reporting']):continue
        for line in page.splitlines():
            match=re.fullmatch(r'\s*(\d{4})(?:\s+-\s+\d+)?\s{2,}(.*)',line)
            if match:
                nums=[int(v.replace(',','')) for v in match[2].split()]
                if len(nums)!=14 or nums[4]!=sum(nums[5:13]) or nums[-1]!=sum(nums[:5]):raise ValueError('presidential canvass row arithmetic changed')
                if match[1] in rows:raise ValueError('repeated native precinct row')
                rows[match[1]]=dict(trump=nums[0],harris=nums[1])
            elif line.strip().startswith('Totals'):
                if printed is not None:raise ValueError('repeated presidential total')
                nums=[int(v.replace(',','')) for v in line.strip().split()[1:]]
                if len(nums)!=14:raise ValueError('presidential total columns changed')
                printed=dict(trump=nums[0],harris=nums[1])
    if len(rows)!=175 or printed!={k:sum(v[k] for v in rows.values()) for k in ['trump','harris']}:raise ValueError('native precinct conservation failed')
    return rows,printed


def parse_precinct_report(text):
    if not all(s in text for s in ['OFFICIAL RESULTS','General Election','November 5, 2024','Fort Bend County Precint Reports']):raise ValueError('wrong or unofficial native precinct report')
    rows={}
    for page in text.split('\f'):
        if not re.search(r'^President / Vice President\s*$',page,re.M):continue
        match=re.search(r'^(\d{4})(?:\s+-\s+\d+)?\s*$',page,re.M)
        if not match or match[1] in rows:raise ValueError('ambiguous native precinct heading')
        values={}
        for field,name in [('trump','REP Donald J. Trump / JD Vance'),('harris','DEM Kamala Harris / Tim Walz')]:
            lines=[line for line in page.splitlines() if line.startswith(name)]
            if len(lines)!=1:raise ValueError('candidate identity changed')
            tokens=re.sub(r'[\d.]+%','',lines[0][len(name):]).split()
            if len(tokens)!=4:raise ValueError('native candidate mode columns changed')
            nums=[int(v.replace(',','')) for v in tokens]
            if nums[0]!=sum(nums[1:]):raise ValueError('native candidate mode conservation failed')
            values[field]=nums[0]
        rows[match[1]]=values
    if len(rows)!=175:raise ValueError('native report must cover all175precincts')
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--canvass',type=Path,required=True);p.add_argument('--precinct-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    contents={k:path.read_bytes() for k,path in [('canvass',args.canvass),('precinct',args.precinct_report)]}
    texts={k:subprocess.run(['pdftotext','-layout','-','-'],input=raw,capture_output=True,check=True).stdout.decode() for k,raw in contents.items()}
    rows,totals=parse_canvass(texts['canvass']);independent=parse_precinct_report(texts['precinct'])
    if rows!=independent:raise ValueError('two official PDF formats disagree')
    ref=next(c for c in json.loads((ROOT/'dashboard/data/reference.json').read_text()) if c['id']=='fortbend')
    native={p for g in ref['groups'] for p in g['old']}
    if rows.keys()!=native:raise ValueError('native reference precinct identities differ')
    county=json.loads((ROOT/'dashboard/data/county-reference.json').read_text())['counties']['fortbend']
    if totals!={k:county[k] for k in totals}:raise ValueError('certified county conservation failed')
    if any(rows[p]!=v for p,v in ref['presidential'].items()):raise ValueError('new direct native returns contradict existing classified returns')
    out=dict(schema_version=1,county='fortbend',election_date='2024-11-05',scope='certified_presidential_all_voting_modes',
        presidential=rows,totals=totals,native_precincts=175,existing_precincts_unchanged=len(ref['presidential']),new_native_returns=len(rows)-len(ref['presidential']),
        sources=[dict(url=u,sha256=hashlib.sha256(contents[k]).hexdigest()) for k,u in [('canvass',CANVASS),('precinct',PRECINCT)]],
        method='Official native precinct canvass presidential rows, independently equal to official native precinct report TOTAL and sum ofElectionDay+Absentee+EarlyVoting for every candidate in all175precincts. Exact4digit native precinct headings agree with existing175oldreferenceIDs. Both county presidential totals conserve. No VTD interpolation, geographic allocation, or turnout alteration.')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:out[k] for k in ['native_precincts','existing_precincts_unchanged','new_native_returns','totals','sources']}))

if __name__=='__main__':main()
