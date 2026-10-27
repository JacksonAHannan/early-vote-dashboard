#!/usr/bin/env python3
"""Audit official Bexar daily PDFs against same-date SOS IDs, in memory only.

Only aggregate observations and label-level proof counts are emitted. This is an
explicit recovery audit, not an unreviewed replacement for the production source.
"""
from __future__ import annotations
import argparse, base64, collections, csv, hashlib, io, json, re, subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = {19:1953,20:1957,21:1958,22:1961,23:1962,24:1965,25:1969,26:1972}
API = 'https://elections.bexar.gov/Admin/DocumentCenter/Home/Document_AjaxBinding?renderMode=0&loadSource=7'
ROW = re.compile(r'^.*?\s+(\d{8,12})\s+.+?\s+([PS])\s+(\d+(?:\.\d+)?)\s*$')


def download(url, form=None):
    from curl_cffi import requests
    with requests.Session(impersonate='chrome') as session:
        r = session.post(url,json=form,timeout=120) if form else session.get(url,timeout=120)
    r.raise_for_status()
    if r.status_code != 200: raise ValueError('official source not ready')
    return r.content


def parse_pdf_text(text):
    if not re.search(r'Name\s+VUID\s+Polling Place\s+Precinct',text):
        raise ValueError('Bexar roster header changed')
    identities={}; original_rows={}; tainted=set(); repeats=0; blanks=collections.Counter(); nonrows=collections.Counter()
    for line in text.splitlines():
        if not line.strip():continue
        match=ROW.fullmatch(line)
        if not match:
            if re.search(r'\d{8,}',line):raise ValueError('unparsed voter-shaped Bexar row')
            blank=re.fullmatch(r'.+?\s+([PS])\s+(\d+(?:\.\d+)?)\s*',line)
            if blank:
                blanks[f'{blank[1]} {blank[2]}']+=1
                continue
            if re.search(r'Name\s+VUID\s+Polling Place\s+Precinct',line):continue
            if re.fullmatch(r'\s*Page\s+\d+\s+of\s+\d+\s*',line):continue
            nonrows[re.sub(r'\d','0',line.strip())]+=1
            continue
        voter,prefix,precinct=match.groups();label=f'{prefix} {precinct}'
        if voter in tainted:
            blanks[label]+=1
        elif voter in identities:
            if identities[voter]!=label or original_rows[voter]!=' '.join(line.split()):
                blanks[identities.pop(voter)]+=1;blanks[label]+=1;tainted.add(voter)
            else:repeats+=1
        else:identities[voter]=label;original_rows[voter]=' '.join(line.split())
    if nonrows:raise ValueError('unreviewed Bexar footer/header shapes: '+str(collections.Counter(re.sub(r'[A-Za-z]', 'X', shape) for shape in nonrows)))
    if not identities:raise ValueError('no Bexar voters; absence is not zero')
    return identities,repeats,dict(blanks)


def parse_state(raw):
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not {'ID_VOTER','PRECINCT','VOTING_METHOD'}.issubset(reader.fieldnames or []):raise ValueError('SOS header changed')
    ids={}
    for row in reader:
        if row['VOTING_METHOD']=='MAIL-IN':continue
        if row['VOTING_METHOD']!='IN-PERSON':raise ValueError('unknown SOS method')
        voter=row['ID_VOTER'].strip();p=row['PRECINCT'].strip();p=str(int(p)) if p.isdigit() else p.upper()
        if not voter or voter in ids:raise ValueError('invalid SOS identity')
        ids[voter]=p or 'UNASSIGNED'
    return ids


def collect_day(when,doc):
    source=f'https://elections.bexar.gov/DocumentCenter/View/{doc}'
    raw=download(source)
    text=subprocess.run(['pdftotext','-layout','-','-'],input=raw,check=True,capture_output=True).stdout.decode()
    identities,repeats,blanks=parse_pdf_text(text)
    source_state=('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'
                  f'?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}&county=BEXAR&countyId=15&format=csv')
    encoded=json.loads(download(source_state))['upload'].rsplit(',',1)[-1]
    state_raw=base64.b64decode(encoded,validate=True);state=parse_state(state_raw)
    return dict(when=str(when),source=source,sha256=hashlib.sha256(raw).hexdigest(),
                state_source=source_state,state_sha256=hashlib.sha256(state_raw).hexdigest(),
                identities=identities,state=state,repeats=repeats,blank_labels=blanks,pages=text.count('\f'))


def aggregate(results,native_ids,metadata):
    # An identity repeated across dated county PDFs cannot establish county-day turnout.
    # Quarantine every affected residence cell; the SOS-only repair path retains its own date.
    occurrences=collections.defaultdict(list)
    for result in results:
        for voter,label in result['identities'].items():occurrences[voter].append((result,label))
    for voter,items in occurrences.items():
        if len(items)>1:
            for result,label in items:
                result['identities'].pop(voter,None)
                result['blank_labels'][label]=result['blank_labels'].get(label,0)+1
    proofs=collections.defaultdict(collections.Counter)
    for result in results:
        for voter,label in result['identities'].items():
            target=result['state'].get(voter)
            if target in native_ids:proofs[label][target]+=1
    aliases={label:next(iter(counts)) for label,counts in proofs.items() if len(counts)==1}
    observations=[];diagnostics=[];seen=set()
    for result in results:
        ids=result['identities']
        cross_date_ids=len(seen.intersection(ids))
        seen.update(ids)
        counts=collections.Counter();unresolved=collections.Counter()
        for label in ids.values():
            if label in aliases:counts[aliases[label]]+=1
            else:counts[f'UNRESOLVED {label}']+=1;unresolved[label]+=1
        unavailable=sorted({aliases.get(label,f'UNRESOLVED {label}') for label in result['blank_labels']})
        withheld=sum(counts.pop(label,0) for label in unavailable)
        repaired=collections.Counter(result['state'].values());reassignments=collections.Counter()
        for voter,p in result['state'].items():
            if p in native_ids:continue
            label=ids.get(voter);target=aliases.get(label)
            if target:
                repaired[p]-=1;repaired[target]+=1;reassignments[(p,label,target)]+=1
        repaired={p:n for p,n in sorted(repaired.items()) if n}
        result['repaired_counts']=repaired;result['reassignments']=[dict(source_label=a,county_label=label,native_precinct=b,votes=n) for (a,label,b),n in sorted(reassignments.items())]
        m=metadata[result['when']]
        observations.append(dict(county='bexar',date=result['when'],counts=dict(sorted(counts.items())),
            source=result['source'],sha256=result['sha256'],retrieved_at=datetime.now(timezone.utc).isoformat(),
            cumulative=False,complete=False,unavailable_precincts=unavailable,note=(
             'AUDIT ONLY: county ballot-method scope is unqualified for historical SOS comparisons; do not substitute this series. Official county dated Early Vote Ballots residence-precinct roster; every PDF row parsed in memory. '
             'P/S residence labels map only where same-date official SOS voter IDs independently demonstrate one unique native map precinct across this audit. '
             'Unproved labels remain explicit UNRESOLVED; no label truncation or absent-precinct zero inference. '
             f'Official document title: {m["DisplayName"]}. '
             f'Alias proof manifest includes SOS source hashes; {sum(unresolved.values())} votes retain unresolved residence labels.')))
        diagnostics.append(dict(date=result['when'],rows=len(ids),repeated_identical_rows=result['repeats'],
            cross_date_ids=cross_date_ids,state_rows=len(result['state']),shared_ids=len(ids.keys() & result['state'].keys()),
            county_only_ids=len(ids.keys()-result['state'].keys()),state_only_ids=len(result['state'].keys()-ids.keys()),
            native_precincts=sum(p in native_ids for p in counts),unusable_identity_rows=sum(result['blank_labels'].values()),unusable_identity_labels=result['blank_labels'],withheld_identified_rows=withheld,unavailable_precincts=unavailable,reassignments=result['reassignments'],repaired_unmapped={p:n for p,n in repaired.items() if p not in native_ids},unresolved=dict(sorted(unresolved.items())),
            source=result['source'],sha256=result['sha256'],state_source=result['state_source'],
            state_sha256=result['state_sha256'],pages=result['pages'],document_title=m['DisplayName']))
    return dict(schema_version=1,county='bexar',year=2026,scope='unqualified_county_early_vote_roster',county_observations_qualified_for_comparison=False,
        method='Same-date voter-ID joins; native target must be unique over all audited dates. No identifiers retained.',
        aliases={label:dict(target=aliases.get(label),matches=dict(counts)) for label,counts in sorted(proofs.items())},
        days=diagnostics,observations=observations,repaired_state_observations=[dict(county='bexar',date=r['when'],counts=r['repaired_counts'],source=r['state_source'],sha256=r['state_sha256'],cumulative=False,complete=False,retrieved_at=datetime.now(timezone.utc).isoformat(),note='Original SOS in-person observations, with unknown residence labels repaired ONLY through exact same-date voter-ID joins to official county PDF rows and independently unique native alias proofs. Source counts and all already-native SOS labels are preserved. See separate aggregate alias/source manifest.') for r in results if r['state']])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--through',type=date.fromisoformat,default=date(2026,10,26));parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    response=json.loads(download(API,dict(folderId=245,getDocuments=1,imageRepo=False,renderMode=0,loadSource=7,requestingModuleID=75,searchString='',pageNumber=1,rowsPerPage=100,sortColumn='DisplayName',sortOrder=0)))
    metadata={}
    for d in response['Documents']:
        m=re.search(r'Early Vote Ballots\s*-\s*(2026-10-\d\d)\s*-\s*November 3, 2026 General Election',d['DisplayName'])
        if m and date.fromisoformat(m[1])<=args.through:
            if m[1] in metadata:raise ValueError('duplicate date titles')
            metadata[m[1]]=d
    targets=[(date(2026,10,day),doc) for day,doc in DOCS.items() if date(2026,10,day)<=args.through]
    if {str(day) for day,_ in targets}!=metadata.keys():raise ValueError('official dated document inventory changed')
    for day,doc in targets:
        if metadata[str(day)]['ID']!=doc:raise ValueError('official document identity changed')
    refs=json.loads((ROOT/'dashboard/data/reference.json').read_text());ref=next(c for c in refs if c['id']=='bexar');native={p for g in ref['groups'] for p in g['new']}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda t:collect_day(*t),targets))
    bundle=aggregate(results,native,metadata);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(bundle,indent=2)+'\n')
    print(json.dumps({d['date']:{k:d[k] for k in ['rows','state_rows','shared_ids','county_only_ids','native_precincts','unresolved']} for d in bundle['days']},indent=2))

if __name__=='__main__':main()
