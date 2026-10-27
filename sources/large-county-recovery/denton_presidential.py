#!/usr/bin/env python3
"""Audit native-ID Denton official 2024 presidential returns; no allocation."""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from pathlib import Path
PDF_SHA256='eb531fbe7489d43c34222b612f05216dba62fbc7091cac273c848b61c57c5191'
SUMMARY_SHA256='82647a8409d390e8d1348ace3b846034a3b6b6e818239fbdeeb67f88d7b6ded5'
ZIP_SHA256='696dda44fa4afabd7ac1c3f9d7b5bacaed70478321b1f6e95711985e14051c48'
URL='https://assets01.aws.connect.clarityelections.com/Assets/Connect/RootPublish/denton-tx.connect.clarityelections.com/ElectionResults/2024/1124/2024_General_Election_Results_Reports.zip'
MEMBER='Stamped/Denton County Canvass-16-11-2024 12.59.52.pdf'


def parse_text(text:str, reference:dict):
    required=['Denton County Canvass','Official Results','11/5/2024','11/16/2024','President/Vice President','United States Senator','Donald J. Trump / JD Vance, REP','Kamala D. Harris / Tim Walz, DEM','Cast Votes','Undervotes','Overvotes','Total Ballots Cast']
    if any(v not in text for v in required) or not re.search(r'240 of 240\s*=\s*100\.00%',text):
        raise ValueError('Wrong/incomplete Denton presidential election or report scope')
    if reference['id']!='denton':raise ValueError('Wrong county reference')
    expected={p for g in reference['groups'] for p in g['old']}
    if len(expected)!=240:raise ValueError('Unexpected 2024 native precinct universe')
    section=text.split('United States Senator',1)[0];rows={};totals=None
    for line in section.splitlines():
        t=line.split()
        if len(t)!=20 or not re.fullmatch(r'[\d.]+%',t[-1]) or any(not re.fullmatch(r'[\d,]+',v) for v in t[1:-1]):continue
        if t[0]!='Totals' and not re.fullmatch(r'\d+',t[0]):raise ValueError('Unknown precinct label')
        values=[int(v.replace(',','')) for v in t[1:-1]]
        # Ten candidate columns, cast, under, over, absentee, early, ED, total,
        # registered. Column order visually verified in the pinned signed PDF.
        if sum(values[:10])!=values[10] or sum(values[10:13])!=values[16] or sum(values[13:16])!=values[16]:
            raise ValueError('Precinct ballot arithmetic fails')
        if t[0]=='Totals':
            if totals is not None:raise ValueError('Duplicate county totals')
            totals=values;continue
        p=t[0].lstrip('0') or '0'
        if p in rows:raise ValueError('Duplicate normalized native precinct')
        rows[p]=values
    if set(rows)!=expected:raise ValueError('Native precinct labels do not exactly match 2024 reference universe')
    if totals is None or any(sum(v[i] for v in rows.values())!=totals[i] for i in range(18)):
        raise ValueError('Precinct rows do not conserve all county total columns')
    if totals[:2]!=[250521,191503] or totals[16]!=452553:
        raise ValueError('Official county presidential/ballot controls differ')
    presidential={p:{'trump':v[0],'harris':v[1]} for p,v in sorted(rows.items())}
    for p,v in reference.get('presidential',{}).items():
        if p not in presidential or any(presidential[p][k]!=v[k] for k in ['trump','harris']):
            raise ValueError('New county return conflicts with an existing classified native precinct')
    return {'county':'denton','election':'2024-11-05','race':'President/Vice President','status':'official_final','source':URL,'archive_sha256':ZIP_SHA256,'member':MEMBER,'sha256':PDF_SHA256,'precincts':len(rows),'existing_classified_precincts':len(reference.get('presidential',{})),'additional_native_returns':len(rows)-len(reference.get('presidential',{})),'presidential':presidential,'county_totals':{'trump':totals[0],'harris':totals[1],'all_candidate_votes':totals[10],'undervotes':totals[11],'overvotes':totals[12],'mail_ballots':totals[13],'early_in_person_ballots':totals[14],'election_day_ballots':totals[15],'all_ballots':totals[16],'registered_voters':totals[17]},'zero_ballot_precincts':sorted(p for p,v in rows.items() if v[16]==0),'qualification':'Official signed November16 county canvass, November5,2024 President/Vice President. Exact same 240 native precinct IDs as official 2024 geographic universe. All18 numeric columns conserve printed county totals; each row reconciles candidate votes, undervotes, overvotes and all voting methods. All94 existing TLC-derived classified precinct returns agree exactly. No geographic allocation; zero/tied presidential returns remain unclassified.'}


def validate_county_summary(text:str, result:dict):
    if any(v not in text for v in ['Denton County Cumulative','Official Results','11/5/2024','11/16/2024','President/Vice President','United States Senator']):
        raise ValueError('Wrong independent county summary scope')
    section=text.split('United States Senator',1)[0]
    for key, label, party in [('trump','Donald J. Trump / JD Vance','REP'),('harris','Kamala D. Harris / Tim Walz','DEM')]:
        matches=re.findall(r'^'+re.escape(label)+r'\s+'+party+r'\s+(.+)$',section,re.M)
        if len(matches)!=1:raise ValueError('Independent county candidate row missing/duplicated')
        t=matches[0].split()
        if len(t)!=8 or any(not re.fullmatch(r'[\d,]+',t[i]) for i in [0,2,4,6]):raise ValueError('Independent county candidate columns changed')
        counts=[int(t[i].replace(',','')) for i in [0,2,4,6]]
        if sum(counts[:3])!=counts[3] or counts[3]!=result['county_totals'][key]:raise ValueError('Independent county candidate totals differ')
    return {'member':'Stamped/Denton County Cumulative-16-11-2024 12.42.02.pdf','sha256':SUMMARY_SHA256,'status':'Both candidate totals independently reconcile by mail + early in-person + Election Day and exactly equal the precinct canvass totals.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--summary-pdf',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if hashlib.sha256(a.pdf.read_bytes()).hexdigest()!=PDF_SHA256:raise ValueError('Unreviewed source PDF edition')
    reference=next(r for r in json.loads(a.reference.read_text()) if r['id']=='denton')
    text=subprocess.check_output(['pdftotext','-layout',str(a.pdf),'-'],text=True);result=parse_text(text,reference)
    if a.summary_pdf:
        if hashlib.sha256(a.summary_pdf.read_bytes()).hexdigest()!=SUMMARY_SHA256:raise ValueError('Unreviewed county summary edition')
        result['independent_county_summary']=validate_county_summary(subprocess.check_output(['pdftotext','-layout',str(a.summary_pdf),'-'],text=True),result)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='presidential'}))
if __name__=='__main__':main()
