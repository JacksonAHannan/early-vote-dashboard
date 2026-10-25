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
from functools import lru_cache
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
PUBLISHED=ROOT/'dashboard/primary/2026.json'
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
SOURCES.update({'tarrant-dem.pdf': 'https://www.tarrantcountytx.gov/content/dam/main/elections/2026/pm26/reports/precinct_dem.pdf',
 'tarrant-rep.pdf': 'https://www.tarrantcountytx.gov/content/dam/main/elections/2026/pm26/reports/precinct_rep.pdf',
 'harris-rep.pdf': 'https://hctxdnnstg.blob.core.windows.net/harrisvotes/prd/Reports/2026/Official%20Canvass%20Results%20Republican%20Party-3-10-2026%2006-22-52%20PM.pdf?sv=2017-04-17&sr=b&si=DNNFileManagerPolicy&sig=UnG%2F%2FoaSvaRFWJ3n5uVu1e7MK%2ByFQP%2F6%2BP86n7NTJNU%3D',
 'harris-dem.pdf': 'https://hctxdnnstg.blob.core.windows.net/harrisvotes/prd/Reports/2026/Official%20Canvass%20Results%20Democratic%20Party-3-10-2026%2006-22-52%20PM.pdf?sv=2017-04-17&sr=b&si=DNNFileManagerPolicy&sig=V3b0hsoWHHzJM%2Fd1LfVeKxLqeRqcKHb5znJCjLRZXPA%3D',
 'bexar-dem.pdf': 'https://elections.bexar.gov/DocumentCenter/View/1193/March-3-2026-Democratic---Official-Precinct-Report-PDF',
 'bexar-rep.pdf': 'https://elections.bexar.gov/DocumentCenter/View/1197/March-3-2026-Republican---Official-Precinct-Report-PDF',
 'collin-precinct.pdf': 'https://www.collincountytx.gov/docs/default-source/elections/results-archive/march-3-2026-primary-election-precinct-report-official-final.pdf?sfvrsn=6a9728bc_11',
 'collin-summary.pdf': 'https://www.collincountytx.gov/docs/default-source/elections/results-archive/march-3-2026-primary-election-summary-report-official-final.pdf?sfvrsn=13303697_9',
 'bexar-summary.pdf': 'https://elections.bexar.gov/DocumentCenter/View/1196/March-3-2026-Primary-Results-PDF'})
SOURCES['tarrant-detailxml.zip']='https://results.enr.clarityelections.com/TX/Tarrant/125924/368843/reports/detailxml.zip'
SOURCES.update({'denton-dem-reports.zip': 'https://assets01.aws.connect.clarityelections.com/Assets/Connect/RootPublish/denton-tx.connect.clarityelections.com/ElectionResults/2026/PM26/Dem/Democratic_Results_Reports.zip', 'denton-rep-reports.zip': 'https://assets01.aws.connect.clarityelections.com/Assets/Connect/RootPublish/denton-tx.connect.clarityelections.com/ElectionResults/2026/PM26/Rep/Republican_Results_Reports.zip'})
CONTROLS={'dallas':{'dem':280326,'rep':103818},'montgomery':{'dem':31510,'rep':80092},
          'hays':{'dem':34049,'rep':18686},'mclennan':{'dem':15093,'rep':23727},
          'ellis':{'dem':18894,'rep':25994},'madison':{'dem':419,'rep':1887},
          'tarrant':{'dem':189583,'rep':147471},'harris':{'dem':366703,'rep':200312},
          'denton':{'dem':83001,'rep':88195},
          'bexar':{'dem':194863,'rep':96502},'collin':{'dem':96078,'rep':104260}}
METHOD=('March 3, 2026 Democratic and Republican primary ballots cast, all voting modes, '
        'from county-published aggregate reports. Democratic share is Democratic ballots / '
        '(Democratic + Republican ballots), summed over complete native 26P precincts before '
        'forming common-geographic-group percentages. This is primary participation, not '
        'party registration or November party preference. Dallas uses Clarity VoterTurnout '
        'ballotsCast with explicit party suffixes removed; Montgomery, Hays, and McLennan '
        'use the explicit Total Ballots Cast column; Ellis uses party Ballots Cast statistics. '
        'Madison uses visually verified explicit Total Ballots Cast columns from a scanned '
        'canvass, reconciled to the signed official combined total; its stale page header is not used. '
        'Denton uses explicit Total Ballots Cast in its official party canvasses. '
        'Tarrant uses explicit precinct ballots-cast headers; Harris uses Total Ballots Cast; '
        'Bexar and Collin use party-specific Ballots Cast statistics. Collin publishes a '
        'precinct report short of its county summary by 15 Democratic and 11 Republican '
        'ballots; these unlocated ballots remain excluded. '
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


@lru_cache(maxsize=None)
def pdf_text(name, pages=20):
    # First 20 pages contain each statewide-senator canvass table, including the
    # right-hand continuation pages of Montgomery's 8-candidate Republican race.
    result=subprocess.check_output(['pdftotext','-layout']+(['-f','1','-l',str(pages)] if pages else [])+[str(RAW/name),'-'],text=True)
    (STORE/(name.removesuffix('.pdf')+'-extract.txt')).write_text(result)
    return result


def parse_canvass(county,party):
    name=f'{county}-{party}.pdf'
    text=pdf_text(name,65 if county=='harris' else 20)
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


def parse_denton(party):
    with zipfile.ZipFile(RAW/f'denton-{party}-reports.zip') as archive:
        name=('Democratic_Results_Reports/Dem_Canvass-Official.pdf' if party=='dem'
              else 'Republican_Results_Reports/Rep_Canvass-Official.pdf')
        (RAW/f'denton-{party}.pdf').write_bytes(archive.read(name))
    return parse_canvass('denton',party)


def parse_tarrant(party):
    text=pdf_text(f'tarrant-{party}.pdf',pages=None)
    assert '3/3/2026' in text and 'Official Results' in text
    assert ('DEM' if party=='dem' else 'REP')+' Precinct Report' in text
    rows={}
    for identity,value in re.findall(r'^\s*(\d+)\s+([\d,]+) ballots cast\s*$',text,re.M):
        identity=normalize(identity); value=integer(value)
        # Each precinct's explicit ballot header repeats on continuation pages.
        assert identity not in rows or rows[identity]==value,(party,identity)
        rows[identity]=value
    printed={integer(v) for v in re.findall(r'Ballots Cast\s*\n\s*([\d,]+)',text)}
    total=CONTROLS['tarrant'][party]
    assert printed=={total} and sum(rows.values())==total
    return rows,{'reported_ballots':total,'source_records':len(rows),'excluded_records':{}}


@lru_cache(maxsize=None)
def statistics_records(name,county):
    text=pdf_text(name,pages=None)
    assert 'March 3, 2026' in text
    assert ('OFFICIAL RESULTS' if county=='bexar' else 'FINAL RESULTS') in text
    records={}
    for page in text.split('\f'):
        if 'Statistics' not in page:continue
        label=page.split('Statistics',1)[0].strip().splitlines()[-1].strip()
        counts={}
        for party,title in [('dem','Democratic'),('rep','Republican'),('total','Total')]:
            match=re.search(r'Ballots Cast - '+title+(r' Party' if party!='total' else '')+r'\s+([\d,]+)',page)
            assert match,(name,label,party)
            counts[party]=integer(match[1])
        assert counts['dem']+counts['rep']==counts['total'],(name,label)
        assert label not in records or records[label]==counts,(name,label)
        records[label]=counts
    assert records,(name,'no statistics')
    return records


def parse_statistics(county,party,expected):
    # Both Bexar party reports repeat the same combined statistics. Require an
    # exact second-report check, rather than treating candidate totals as ballots.
    names=['bexar-dem.pdf','bexar-rep.pdf'] if county=='bexar' else ['collin-precinct.pdf']
    records=statistics_records(names[0],county)
    if county=='bexar':assert records==statistics_records(names[1],county)
    summary=pdf_text(f'{county}-summary.pdf',pages=1)
    control=re.search(r'Ballots Cast - '+('Democratic' if party=='dem' else 'Republican')+r' Party\s+([\d,]+)',summary)
    assert control and integer(control[1])==CONTROLS[county][party]
    rows={};excluded={}
    for label,values in records.items():
        match=re.fullmatch(r'\d+' if county=='bexar' else r'PCT (\d+)',label)
        identity=normalize(match[0] if county=='bexar' else match[1]) if match else None
        if identity in expected:
            assert identity not in rows,(county,identity)
            rows[identity]=values[party]
        else:excluded[label]=values[party]
    reported=sum(v[party] for v in records.values())
    # The published Collin precinct statistics omit 26 ballots found in the
    # county summary. Preserve the independently reported precinct rows and
    # disclose this exact source discrepancy; never spread the residual around.
    residual=CONTROLS[county][party]-reported
    assert residual==({'dem':15,'rep':11}[party] if county=='collin' else 0),(county,party,residual)
    assert sum(rows.values())+sum(excluded.values())+residual==CONTROLS[county][party]
    return rows,{'reported_ballots':CONTROLS[county][party],
                 'source_records':len(records),'precinct_report_ballots':reported,
                 'native_ballots':sum(rows.values()),'excluded_records':excluded,
                 'unlocated_ballots':residual,
                 'reconciliation':'precinct_report_short_of_summary' if residual else 'exact'}


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
        parsers={'dallas':parse_dallas,'ellis':parse_ellis,'madison':parse_madison,
                 'denton':parse_denton,'tarrant':parse_tarrant}
        if slug in parsers:parse=parsers[slug]
        elif slug in ('bexar','collin'):parse=lambda party:parse_statistics(slug,party,expected)
        else:parse=lambda party:parse_canvass(slug,party)
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
    PUBLISHED.parent.mkdir(parents=True,exist_ok=True)
    PUBLISHED.write_text(encoded)
    validation['output_sha256']=hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    (STORE/'validation.json').write_text(json.dumps(validation,indent=2,sort_keys=True)+'\n')
    print(f"Validated {validation['included_precincts']} native precincts; missing stays absent")


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true')
    build(parser.parse_args().offline)
