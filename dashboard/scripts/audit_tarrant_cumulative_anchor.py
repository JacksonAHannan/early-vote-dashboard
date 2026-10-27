#!/usr/bin/env python3
"""Aggregate-only audit of an EXACT-CUTOFF county Tarrant in-person anchor.

Not a daily allocation. County source timestamp and independent dated totals
must establish the cutoff before any emitted candidate can be approved.
"""
import argparse,base64,collections,csv,hashlib,io,json,subprocess,zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
import re
from collect_bexar_native_recovery import download,parse_state
ROOT=Path(__file__).resolve().parents[2]
URL='https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_voting_in_person_report.zip'


def state(when):
    source=('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'
            f'?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}&county=TARRANT&countyId=220&format=csv')
    response=download(source)
    if not response:
        return dict(date=str(when),source=source,sha256=hashlib.sha256(response).hexdigest(),identities={},error='official SOS body empty; not zero')
    raw=base64.b64decode(json.loads(response)['upload'].rsplit(',',1)[-1],validate=True)
    return dict(date=str(when),source=source,sha256=hashlib.sha256(raw).hexdigest(),identities=parse_state(raw))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--through',type=date.fromisoformat,default=date(2026,10,26));p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if not date(2026,10,19)<=args.through<=date(2026,10,30):raise ValueError('outside early-voting period')
    raw=download(URL);county={};invalid=collections.Counter();rawcounts=collections.Counter();seen_county=set();archive=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.txt')]
        if len(names)!=1:raise ValueError('county archive layout changed')
        i=z.getinfo(names[0]);archive.append(dict(member=i.filename,modified=list(i.date_time),size=i.file_size))
        rd=csv.DictReader(io.TextIOWrapper(z.open(names[0]),encoding='utf-8-sig'),delimiter='\t')
        if not {'ID Number','SOS Voter ID','Precinct','Election Code','Party of Ballot Issued'}.issubset(rd.fieldnames):raise ValueError('county schema changed')
        for row in rd:
            label=row['Precinct'].strip();identity=row['ID Number'].strip();vuid=row['SOS Voter ID'].strip()
            if not re.fullmatch(r'\d{6}',label) or row['Election Code']!='522' or row['Party of Ballot Issued']!='NPA':raise ValueError('county precinct/election scope changed')
            rawcounts[label]+=1
            if not identity or not vuid:invalid[label]+=1;continue
            if not identity.isdigit() or identity in seen_county or vuid in county:raise ValueError('county identity changed or repeated')
            seen_county.add(identity);county[vuid]=label
    ref=next(c for c in json.loads((ROOT/'dashboard/data/reference.json').read_text()) if c['id']=='tarrant');native={p for g in ref['groups'] for p in g['new']}
    dates=[date(2026,10,19)+timedelta(days=i) for i in range((args.through-date(2026,10,19)).days+1)]
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(state,dates))
    proof=collections.defaultdict(collections.Counter);seen=set()
    for r in results:
        if seen.intersection(r['identities']):raise ValueError('SOS identity repeated across dates')
        seen.update(r['identities'])
        for voter,target in r['identities'].items():
            label=county.get(voter)
            if label and target in native:proof[label][target]+=1
    aliases={label:next(iter(values)) for label,values in proof.items() if len(values)==1}
    counts=collections.Counter();unresolved=collections.Counter()
    for label in county.values():
        target=aliases.get(label)
        if target:counts[target]+=1
        else:counts[f'UNRESOLVED {label}']+=1;unresolved[label]+=1
    unavailable=sorted({aliases.get(label,f'UNRESOLVED {label}') for label in invalid})
    withheld=sum(counts.pop(label,0) for label in unavailable)
    candidate=dict(county='tarrant',date=str(args.through),counts=dict(sorted(counts.items())),source=URL,sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),cumulative=True,complete=False,unavailable_precincts=unavailable,
        note='AUDIT CANDIDATE: exact-cutoff cumulative county Early Voting in Person roster only; cannot allocate backward into daily observations. Six-digit county labels resolve only through unique same-voter official SOS native-precinct joins. Invalid identity cells quarantined locally, unresolved labels explicit. Source cutoff requires separately retained dated county control + official archive timestamp; no blanket completeness is granted.')
    out=dict(schema_version=1,cutoff_requires_independent_approval=True,candidate=candidate,raw_rows=sum(rawcounts.values()),valid_identified_rows=len(county),invalid_identity_rows=sum(invalid.values()),invalid_county_labels=dict(sorted(invalid.items())),withheld_identified_rows=withheld,native_precincts=sum(p in native for p in counts),archive=archive,unresolved=dict(sorted(unresolved.items())),aliases={label:dict(target=aliases.get(label),matches=dict(values)) for label,values in sorted(proof.items())},state_provenance=[{k:r[k] for k in ['date','source','sha256']} for r in results])
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:out[k] for k in ['raw_rows','valid_identified_rows','invalid_identity_rows','withheld_identified_rows','native_precincts','unresolved']}))

if __name__=='__main__':main()
