#!/usr/bin/env python3
"""Certify only native precincts with ZERO ALL-METHOD final 2024 ballots.

The official final report's all-method totals give an upper bound of zero for
any early-vote subperiod. Positive final totals are never allocated backwards.
Input PDF is public aggregate results, not a voter roster.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

SOURCE='https://www.tarrantcountytx.gov/content/dam/main/elections/2024/1124/reports/precinct.pdf'
ROOT=Path(__file__).resolve().parents[2]


def parse_zero_precincts(text,expected_precincts=844):
    required=['Official Results','Tarrant County','Joint General and Special Election','11/5/2024']
    if any(value not in text for value in required):raise ValueError('wrong election or nonfinal report')
    if not re.search(r'Precincts Reporting\s+844 of 844 = 100\.00%',text):raise ValueError('final precinct coverage changed')
    if not re.search(r'828544 of 1299023 = 63\.78%',text):raise ValueError('official county ballots control changed')
    values={}
    for match in re.finditer(r'^(\d{4})\s+([\d,]+) of ([\d,]+) registered voters = [\d.]+%',text,re.M):
        precinct=match[1];value=tuple(int(match[i].replace(',','')) for i in (2,3))
        if precinct in values and values[precinct]!=value:raise ValueError('conflicting native precinct totals')
        values[precinct]=value
    if len(values)!=expected_precincts:raise ValueError('native precinct count changed')
    if sum(v[0] for v in values.values())!=828544 or sum(v[1] for v in values.values())!=1299023:
        raise ValueError('native precinct totals do not reconcile to official county controls')
    return {p:dict(ballots_cast=b,registered_voters=r) for p,(b,r) in sorted(values.items()) if b==0}


def certificate(raw,reference):
    text=subprocess.run(['pdftotext','-layout','-','-'],input=raw,check=True,capture_output=True).stdout.decode()
    zeros=parse_zero_precincts(text)
    old={p for g in reference['groups'] for p in g['old']}
    if not zeros.keys()<=old:raise ValueError('zero proof includes labels outside native 2024 reference')
    for p in zeros:
        v=reference.get('presidential',{}).get(p)
        if v and (v['harris']!=0 or v['trump']!=0):raise ValueError('zero ballots contradict presidential returns')
    return dict(schema_version=1,county='tarrant',year=2024,source=SOURCE,
        sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),
        election_date='2024-11-05',scope='all_methods_final_ballots_cast',
        official_county_ballots_cast=828544,official_county_registered_voters=1299023,
        native_precincts_checked=844,zero_precincts=zeros,
        applies_to_dates=[str(date(2024,10,21)+timedelta(days=i)) for i in range(12)],
        method='Zero final all-method ballots cast is an exact upper bound on in-person ballots for each 2024 general-election early-voting date. All 844 native precinct totals reconcile to the official 828544 county ballots and1299023 registrations. No positive final count is assigned to an earlier date; no county-wide completeness or absent-label zero inference is granted.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pdf',type=Path,required=True);parser.add_argument('--reference',type=Path,default=ROOT/'dashboard/data/reference.json');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    ref=next(c for c in json.loads(args.reference.read_text()) if c['id']=='tarrant')
    result=certificate(args.pdf.read_bytes(),ref);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(zero_precincts=len(result['zero_precincts']),native_precincts_checked=result['native_precincts_checked'],sha256=result['sha256'])))

if __name__=='__main__':main()
