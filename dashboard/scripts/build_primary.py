#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["curl-cffi>=0.13,<1"]
# ///
"""Build aggregate March 3, 2026 party-primary participation from county reports.

uv run dashboard/scripts/build_primary.py [--offline]
Only public aggregate reports are fetched or retained. No voter records are read.
Requires installed pdftotext (Poppler). Source snapshots are cached and hashed.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from curl_cffi import requests

ROOT=Path(__file__).resolve().parents[2]
STORE=ROOT/'sources/primary-participation'
RAW=STORE/'raw'
OUTPUT=ROOT/'dashboard/data/primary.json'
BASE='https://results.enr.clarityelections.com/TX/'
SOURCES={
 'dallas-dem-detailxml.zip':BASE+'Dallas/126006/368801/reports/detailxml.zip',
 'dallas-rep-detailxml.zip':BASE+'Dallas/126007/368732/reports/detailxml.zip',
 'montgomery-dem.pdf':'https://elections.mctx.org/results/2026_March_Democratic_Canvass_Report.pdf',
 'montgomery-rep.pdf':'https://elections.mctx.org/results/2026_March_Republican_Canvass_Report.pdf',
 'hays-dem.pdf':'https://www.egovlink.com/public_documents300/hayscounty/published_documents/departments/elections/results/2026/0303%20Primaries/Canvass%20Results%20-%20Democratic%20Party%20-%20official.pdf',
 'hays-rep.pdf':'https://www.egovlink.com/public_documents300/hayscounty/published_documents/departments/elections/results/2026/0303%20Primaries/Canvass%20Results%20-%20Republican%20Party%20-%20official.pdf',
 'mclennan-dem.pdf':'https://tx-mclennancounty.civicplus.com/DocumentCenter/View/18208/Democratic-Party---Canvass-Results-3-10-2026-01-03-40-PM',
 'mclennan-rep.pdf':'https://tx-mclennancounty.civicplus.com/DocumentCenter/View/18205/Republican-Party---Canvass-Results-3-10-2026-01-27-39-PM',
 'ellis-dem.pdf':'https://www.elliscountytx.gov/DocumentCenter/View/23025/260303_Democratic-Primary-Election_Final-PctbyRace_Totals?bidId=',
 'madison-canvass.pdf':'https://www.co.madison.tx.us/upload/page/0407/March%203%202%2026%20Canvass.pdf',
 'madison-reconciliation.pdf':'https://www.co.madison.tx.us/upload/page/0407/March%203%202026%20Official%20reconcilliation.pdf',
 'ellis-index.pdf':'https://www.elliscountytx.gov/DocumentCenter/View/23023/260303_Republican-Primary-Election_Final-PctbyRace_Totals?bidId=',
}
CONTROLS={'dallas':{'dem':280326,'rep':103818},'montgomery':{'dem':31510,'rep':80092},
          'hays':{'dem':34049,'rep':18686},'mclennan':{'dem':15093,'rep':23727},
          'ellis':{'dem':18894,'rep':25994},'madison':{'dem':419,'rep':1887}}
METHOD=('March 3, 2026 Democratic and Republican primary ballots cast, all voting modes, '
        'from county-published aggregate reports. Democratic share is Democratic ballots / '
        '(Democratic + Republican ballots), summed over complete native 26P precincts before '
        'forming common-geographic-group percentages. This is primary participation, not '
        'party registration or November party preference. Dallas uses Clarity VoterTurnout '
        'ballotsCast with explicit party suffixes removed; Montgomery, Hays, and McLennan '
        'use the explicit Total Ballots Cast column; Ellis uses party Ballots Cast statistics. '
        'Madison uses visually verified explicit Total Ballots Cast columns from a scanned '
        'canvass, reconciled to the signed official combined total; its stale page header is not used. '
        'Candidate-vote sums are never substituted. Limited/federal-only records without a '
        'native precinct match and missing precincts are excluded, never assigned by area '
        'or assumed zero. No voter-level records are read or retained.')


def normalize(value):
    value=str(value).strip().upper()
    return str(int(value)) if value.isdigit() else value


def fetch(name,offline):
    path=RAW/name
    if path.exists(): return path
    if offline: raise FileNotFoundError(f'Uncached source: {name}')
    response=requests.get(SOURCES[name],impersonate='chrome',timeout=120)
    response.raise_for_status()
    if not response.content: raise ValueError(f'Empty aggregate source {name}')
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(response.content)
    temporary.replace(path)
    return path


def integer(value):
    return int(value.replace(',',''))


def parse_dallas(party):
    filename=f'dallas-{party}-detailxml.zip'
    with zipfile.ZipFile(RAW/filename) as archive:
        root=ET.fromstring(archive.read('detail.xml'))
    assert root.findtext('ElectionDate')=='3/3/2026'
    assert ('Democratic' if party=='dem' else 'Republican') in root.findtext('ElectionName')
    turnout=root.find('VoterTurnout')
    rows={}
    suffix='D' if party=='dem' else 'R'
    for precinct in turnout.findall('./Precincts/Precinct'):
        name=precinct.attrib['name']
        assert name.endswith(suffix), name
        identity=normalize(name[:-1])
        assert identity not in rows, identity
        rows[identity]=integer(precinct.attrib['ballotsCast'])
    total=integer(turnout.attrib['ballotsCast'])
    assert sum(rows.values())==total==CONTROLS['dallas'][party]
    return rows, {'reported_ballots':total,'source_records':len(rows),'excluded_records':{}}


def pdf_text(name):
    # First 20 pages contain each statewide-senator canvass table, including the
    # right-hand continuation pages of Montgomery's 8-candidate Republican race.
    result=subprocess.check_output(['pdftotext','-layout','-f','1','-l','20',str(RAW/name),'-'],text=True)
    (STORE/(name.removesuffix('.pdf')+'-extract.txt')).write_text(result)
    return result


def parse_canvass(county,party):
    name=f'{county}-{party}.pdf'
    text=pdf_text(name)
    assert '3/3/2026' in text
    assert 'Total Ballots Cast' in text
    assert ('Democratic' if party=='dem' else 'Republican') in text
    # Stop before the next contest rather than counting repeated precincts from
    # local contests. Ballots cast are explicit, independent of candidate votes.
    text=re.split(r'(?:United States|U\.S\.) Representative',text,maxsplit=1)[0]
    rows={}; excluded={}; source_total=None
    for line in text.splitlines():
        tokens=line.split()
        if len(tokens)<4 or not re.fullmatch(r'[\d.]+%',tokens[-1]):continue
        if tokens[0]=='Totals' and all(re.fullmatch(r'[\d,]+',t) for t in tokens[1:-1]):
            source_total=integer(tokens[-3]); continue
        numeric=re.fullmatch(r'\d+(?:-[A-Z]+)?',tokens[0])
        if numeric and all(re.fullmatch(r'[\d,]+',t) for t in tokens[1:-1]):
            identity=normalize(tokens[0].split('-')[0])
            assert identity not in rows, (county,party,identity)
            rows[identity]=integer(tokens[-3])
        elif county=='hays':
            # Five explicitly labelled federal/limited-ballot pseudo-precincts.
            match=re.match(r'^\s*(Fed\s+\d+|Lim-State Only|Lim-US\s+\d+)\s+(.+)$',line)
            if match:
                values=match.group(2).split()
                assert all(re.fullmatch(r'[\d,]+',t) for t in values[:-1])
                excluded[match.group(1)]=integer(values[-3])
    expected=CONTROLS[county][party]
    assert source_total==expected, (county,party,source_total,expected)
    assert sum(rows.values())+sum(excluded.values())==source_total,(county,party,'reconcile')
    return rows,{'reported_ballots':source_total,'source_records':len(rows)+len(excluded),
                'excluded_records':excluded,'native_ballots':sum(rows.values())}


def parse_ellis(party):
    name='ellis-dem.pdf' if party=='dem' else 'ellis-index.pdf'
    text=pdf_text(name)
    assert 'March 3, 2026' in text and 'OFFICIAL RESULTS FOR CANVASS' in text
    assert 'Ballots Cast -' in text and ('Democratic' if party=='dem' else 'Republican') in text
    # Two statistics pages precede candidate contests; use Ballots Cast directly.
    text='\n'.join(text.split('\f')[:2])
    rows={}; total=None
    for line in text.splitlines():
        values=line.split()
        if len(values)==4 and values[0].isdigit() and values[-1].endswith('%'):
            assert values[0] not in rows
            rows[normalize(values[0])]=integer(values[2])
        elif len(values)==3 and values[0]=='Totals': total=integer(values[-1])
    assert sum(rows.values())==total==CONTROLS['ellis'][party]
    return rows,{'reported_ballots':total,'source_records':len(rows),'excluded_records':{}}


def parse_madison(party):
    transcription=json.loads((STORE/'madison-transcription.json').read_text())
    assert hashlib.sha256((STORE/transcription['source']).read_bytes()).hexdigest()==transcription['source_sha256'], 'Madison transcription requires reinspection'
    control=transcription['reconciliation']
    assert hashlib.sha256((STORE/control['source']).read_bytes()).hexdigest()==control['source_sha256'], 'Madison control requires reinspection'
    report=transcription[party]
    rows=report['precincts']
    assert sum(rows.values())==report['printed_total']==CONTROLS['madison'][party]
    assert sum(CONTROLS['madison'].values())==transcription['reconciliation']['value']==2306
    return rows,{'reported_ballots':report['printed_total'],'source_records':len(rows),
                 'excluded_records':{},'pdf_page':report['pdf_page'],
                 'transcription':'visually_verified_explicit_ballot_column',
                 'source_header_caveat':transcription['source_caveat']}


def build(offline=False):
    RAW.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda n:fetch(n,offline),SOURCES))
    reference=json.loads((ROOT/'dashboard/data/reference.json').read_text())
    data={'schema_version':1,'metrics':[{'id':'primary_dem_share','label':'2026 Democratic primary',
          'unit':'percent','numerator':'primary_dem','denominator':'primary_total','cuts':[20,40,60,80],
          'source':'County-published March 3, 2026 party-primary ballots cast',
          'vintage':'March 3, 2026 / 2026 primary precincts'}],'counties':{},'sources':[],'method':METHOD}
    validation={'passed':True,'election_date':'2026-03-03','counties':{},'included_precincts':0,
                'candidate_vote_proxy_used':False,'voter_level_records_used':False}
    for county in reference:
        slug=county['id']; expected={p for group in county['groups'] for p in group['new']}
        if slug not in CONTROLS:
            coverage={'status':'unavailable','expected_precincts':len(expected),'included_precincts':0,
                      'missing_precincts':sorted(expected),
                      'reason':'No verified party-specific precinct ballot totals acquired; combined turnout and candidate totals cannot substitute.'}
            data['counties'][slug]={'precincts':{},'coverage':coverage}
            validation['counties'][slug]=coverage
            continue
        parse=parse_dallas if slug=='dallas' else parse_ellis if slug=='ellis' else parse_madison if slug=='madison' else lambda party:parse_canvass(slug,party)
        dem,dem_quality=parse('dem'); rep,rep_quality=parse('rep')
        common=expected & set(dem) & set(rep)
        assert not ((set(dem)|set(rep))-expected), (slug,'unexpected native precinct')
        precincts={p:{'counts':{'primary_dem':dem[p],'primary_rep':rep[p],'primary_total':dem[p]+rep[p]},
                        'quality':{'status':'county_published_aggregate_ballots','election_date':'2026-03-03',
                                   'boundary_vintage':'26P','all_voting_modes':True,'geographic_join':'normalized_precinct_id'}}
                   for p in sorted(common)}
        totals={'primary_dem':sum(dem[p] for p in common),'primary_rep':sum(rep[p] for p in common)}
        totals['primary_total']=sum(totals.values())
        coverage={'status':'complete' if common==expected else 'partial','expected_precincts':len(expected),
                  'included_precincts':len(common),'missing_precincts':sorted(expected-common),
                  'complete_groups':sum(set(g['new'])<=common for g in county['groups']),
                  'expected_groups':len(county['groups']),'party_reports':{'dem':dem_quality,'rep':rep_quality}}
        data['counties'][slug]={'precincts':precincts,'coverage':coverage,'assigned_totals':totals}
        validation['counties'][slug]={'coverage':coverage,'totals':totals}
        validation['included_precincts']+=len(common)
        print(slug,len(common),'/',len(expected),totals,flush=True)
    for name,url in SOURCES.items():
        path=RAW/name
        data['sources'].append({'url':url,'path':str(path.relative_to(ROOT)),
          'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    transcription=STORE/'madison-transcription.json'
    data['sources'].append({'path':str(transcription.relative_to(ROOT)), 'sha256':hashlib.sha256(transcription.read_bytes()).hexdigest(), 'type':'visually_verified_transcription'})
    encoded=json.dumps(data,separators=(',',':'),sort_keys=True,allow_nan=False)+'\n'
    OUTPUT.write_text(encoded)
    validation['output_sha256']=hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    (STORE/'validation.json').write_text(json.dumps(validation,indent=2,sort_keys=True)+'\n')
    print(f"Validated {validation['included_precincts']} native precincts; missing stays absent")


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true')
    build(parser.parse_args().offline)
