#!/usr/bin/env python3
"""Exact-cutoff cumulative in-person anchor; no backwards daily allocation.

All voter rows/IDs stay in memory. Only Daily precinct aggregates and optional
anonymous source/alias diagnostics reach disk/stdout.
"""
import argparse,base64,collections,csv,hashlib,io,json,re,subprocess,sys,zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
BASE='https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/'
ZIP_URL=BASE+'Early_voting_in_person_report.zip'
CONTROL_URL=BASE+'Early_Voting_Daily_Totals.pdf'
START=date(2026,10,19)
ZONE=ZoneInfo('America/Chicago')


def download(url):
    from curl_cffi import requests
    with requests.Session(impersonate='chrome') as session:
        response=session.get(url,timeout=60)
    if response.status_code!=200:raise ValueError('official source unavailable')
    return response.content,{k.lower():v for k,v in response.headers.items()}


def cutoff_control(text,through):
    if 'November 3, 2026' not in text or 'Early Voting In Person Totals' not in text:
        raise ValueError('wrong election or voting scope')
    generated_dates=re.findall(r'([A-Z][a-z]+ \d{1,2}, 2026)',text)
    stamp=re.search(r'(\d{1,2}):(\d{2}):(\d{2})(AM|PM)',text)
    dates=re.search(r'^\s*Total\s+((?:\d{2}/\d{2}\s*)+)\n',text,re.M)
    values=re.search(r'^Total\s+([\d,]+(?:\s+[\d,]+)+)\s*$',text,re.M)
    if not generated_dates or not stamp or not dates or not values:raise ValueError('control layout changed')
    generated=datetime.strptime(generated_dates[-1]+' '+stamp[0],'%B %d, %Y %I:%M:%S%p').replace(tzinfo=ZONE)
    days=[datetime.strptime(v+'/2026','%m/%d/%Y').date() for v in dates[1].split()]
    counts=[int(v.replace(',','')) for v in values[1].split()]
    if generated.date()!=through or generated.hour<19 or days!=[START+timedelta(days=i) for i in range((through-START).days+1)]:
        raise ValueError('control is not the exact completed cutoff')
    if len(counts)!=len(days)+1 or sum(counts[1:])!=counts[0]:raise ValueError('control arithmetic mismatch')
    sites=[]
    for line in text.splitlines():
        match=re.match(r'^(.+?)\s{2,}([\d,]+(?:\s+[\d,]+)+)\s*$',line)
        if not match or match[1].strip()=='Total':continue
        nums=[int(v.replace(',','')) for v in match[2].split()]
        if len(nums)==len(counts):
            if sum(nums[1:])!=nums[0]:raise ValueError('control location arithmetic mismatch')
            sites.append(nums)
    if not sites or [sum(row[i] for row in sites) for i in range(len(counts))]!=counts:
        raise ValueError('independent location totals do not reconcile')
    return generated,counts[0]


def prove_archive_cutoff(headers,member,generated,through):
    modified=parsedate_to_datetime(headers.get('last-modified','')).astimezone(ZONE)
    archived=datetime(*member.date_time,tzinfo=ZONE)
    if modified.date()!=through or archived.date()!=through or not generated<=archived<=modified:
        raise ValueError('county archive metadata does not prove exact cutoff')
    if modified-archived>timedelta(minutes=30) or archived-generated>timedelta(minutes=30):
        raise ValueError('archive/control timestamps do not describe one publication')
    return dict(last_modified=modified.isoformat(),zip_member_modified=archived.isoformat(),control_generated=generated.isoformat())


def parse_native(raw,through,headers,generated,total):
    identities={};county_ids=set();invalid=collections.Counter();rawcounts=collections.Counter()
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        members=[book.getinfo(n) for n in book.namelist() if n.lower().endswith('.txt')]
        if len(members)!=1:raise ValueError('county archive layout changed')
        metadata=prove_archive_cutoff(headers,members[0],generated,through)
        rows=csv.DictReader(io.TextIOWrapper(book.open(members[0]),encoding='utf-8-sig'),delimiter='\t')
        if not {'ID Number','SOS Voter ID','Precinct','Election Code','Party of Ballot Issued'}<=set(rows.fieldnames or []):raise ValueError('county roster columns changed')
        for row in rows:
            label=row['Precinct'].strip();voter=row['SOS Voter ID'].strip();county_id=row['ID Number'].strip()
            if not re.fullmatch(r'\d{6}',label) or row['Election Code']!='522' or row['Party of Ballot Issued']!='NPA':raise ValueError('county election/precinct scope changed')
            rawcounts[label]+=1
            if not voter or not county_id:invalid[label]+=1;continue
            if not voter.isdigit() or not county_id.isdigit() or voter in identities or county_id in county_ids:raise ValueError('county identity is invalid or repeated')
            identities[voter]=label;county_ids.add(county_id)
    if sum(rawcounts.values())!=total:raise ValueError('county roster does not reconcile exact-cutoff control')
    return identities,invalid,rawcounts,metadata


def state(when):
    url=('https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat'
         f'?type=EVR_EARLYVOTING&electionId=53815&electionDate={when:%m/%d/%Y}&county=TARRANT&countyId=220&format=csv')
    response,_=download(url)
    if not response:return dict(date=str(when),source=url,status='not-published',identities={})
    obj=json.loads(response);raw=base64.b64decode(obj['upload'].split(',')[-1],validate=True)
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not {'ID_VOTER','PRECINCT','VOTING_METHOD'}<=set(reader.fieldnames or []):raise ValueError('SOS schema changed')
    identities={}
    for row in reader:
        if row['VOTING_METHOD']=='MAIL-IN':continue
        if row['VOTING_METHOD']!='IN-PERSON':raise ValueError('unknown SOS method')
        voter=row['ID_VOTER'].strip();p=row['PRECINCT'].strip().upper();p=str(int(p)) if p.isdigit() else p or 'UNASSIGNED'
        if not voter or voter in identities:raise ValueError('SOS identity invalid or repeated')
        identities[voter]=p
    return dict(date=str(when),source=url,status='reported',sha256=hashlib.sha256(raw).hexdigest(),identities=identities)


def aggregate(identities,invalid,results,universe):
    """Resolve individual county rows before considering a label-level fallback.

    A native target comes from the same voter ID in an official dated SOS file.
    Label aliases are used only for unmatched county identities and must have
    exactly one observed target, including foreign targets in the ambiguity set.
    An unresolved/invalid row quarantines all native targets associated with its
    county label, so other resolved rows cannot leak a partial native cell.
    """
    associations=collections.defaultdict(collections.Counter)
    state_ids={}
    for result in results:
        if state_ids.keys() & result['identities'].keys():
            raise ValueError('SOS identity repeated across dates')
        state_ids.update(result['identities'])
        for voter,target in result['identities'].items():
            if voter in identities:associations[identities[voter]][target]+=1
    aliases={label:next(iter(targets)) for label,targets in associations.items()
             if len(targets)==1 and next(iter(targets)) in universe}
    counts=collections.Counter();unknown=collections.Counter();bad=set()
    direct=collections.defaultdict(collections.Counter);fallback=collections.Counter()
    for voter,label in identities.items():
        target=state_ids.get(voter)
        if target in universe:
            counts[target]+=1;direct[label][target]+=1
        elif target is None and label in aliases:
            counts[aliases[label]]+=1;fallback[label]+=1
        else:
            unknown[label]+=1;bad.update(set(associations[label])&universe)
    for label in invalid:bad.update(set(associations[label])&universe)
    for label,n in unknown.items():counts['UNRESOLVED '+label]+=n
    withheld=sum(counts.pop(p,0) for p in bad)
    unavailable=sorted(bad|{'UNRESOLVED '+label for label in invalid})
    proof={label:dict(target=aliases.get(label),matches=dict(values),
           directly_matched_native_rows=dict(direct[label]),
           unmatched_identity_alias_rows=fallback[label],unresolved_rows=unknown[label])
           for label,values in sorted(associations.items())}
    if sum(counts.values())+withheld!=len(identities):
        raise ValueError('identified county row conservation failed')
    return dict(sorted(counts.items())),unavailable,proof,withheld


def collect(through):
    if not START<=through<=date(2026,10,30):raise ValueError('outside early voting calendar')
    raw_control,_=download(CONTROL_URL)
    if not raw_control.startswith(b'%PDF'):raise ValueError('control is not PDF')
    text=subprocess.run(['pdftotext','-layout','-','-'],input=raw_control,capture_output=True,check=True,timeout=30).stdout.decode()
    generated,total=cutoff_control(text,through)
    raw,headers=download(ZIP_URL);identities,invalid,rawcounts,metadata=parse_native(raw,through,headers,generated,total)
    reference=next(c for c in json.loads((ROOT/'dashboard/data/reference.json').read_text()) if c['id']=='tarrant');universe={p for g in reference['groups'] for p in g['new']}
    dates=[START+timedelta(days=i) for i in range((through-START).days+1)]
    def safe_state(when):
        try:return state(when)
        except Exception:return dict(date=str(when),status='unavailable',identities={})
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(safe_state,dates))
    counts,unavailable,proof,withheld=aggregate(identities,invalid,results,universe)
    if not any(p in universe and n>0 for p,n in counts.items()):raise ValueError('no verified native anchor cells')
    if sum(counts.values())+withheld+sum(invalid.values())!=sum(rawcounts.values()):raise ValueError('raw county row conservation failed')
    source_hash=hashlib.sha256(raw).hexdigest();control_hash=hashlib.sha256(raw_control).hexdigest()
    state_proof=[{k:v for k,v in r.items() if k!='identities'} for r in results]
    manifest=dict(method='tarrant-exact-cutoff-individual-native-identity-then-unique-all-target-alias-v2',native_sha256=source_hash,control_sha256=control_hash,cutoff=str(through),state=state_proof,metadata=metadata)
    digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    note=('Exact-cutoff cumulative in-person county roster only. Undated rows are never backallocated into daily observations; daily differencing is disabled. '
          'Individual county rows use a unique exact-voter official SOS native residence target through the actual cutoff day. An unmatched row uses a six-digit-label alias only when every observed target agrees on one native precinct, including foreign targets in ambiguity checks. '
          'Unresolved rows and blank identity cells quarantine every potentially affected native precinct. Native rows reconcile the independently dated completed in-person total before local quarantine. '
          f'Raw county source SHA256 {source_hash}; independent control {CONTROL_URL} SHA256 {control_hash}; publication metadata {json.dumps(metadata,sort_keys=True)}. '
          'Derived SHA256 hashes canonical input-hash/method manifest. SOS alias evidence '+json.dumps(state_proof,sort_keys=True)+'. No voter identities or raw rosters retained.')
    daily=dict(county='tarrant',date=str(through),counts=counts,source=ZIP_URL,sha256=digest,retrieved_at=datetime.now(timezone.utc).isoformat(),cumulative=True,complete=False,allow_daily_difference=False,unavailable_precincts=unavailable,note=note)
    evidence=dict(schema_version=1,manifest=manifest,raw_rows=sum(rawcounts.values()),valid_identified_rows=len(identities),blank_identity_rows=sum(invalid.values()),invalid_labels=dict(invalid),withheld_identified_rows=withheld,native_precincts=sum(p in universe for p in counts),all_cutoff_dates_included=[str(d) for d in dates],aliases=proof)
    return daily,evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--through',type=date.fromisoformat,required=True);parser.add_argument('--evidence',type=Path);args=parser.parse_args()
    daily,evidence=collect(args.through)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True,exist_ok=True);args.evidence.write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps([daily],sort_keys=True))

if __name__=='__main__':main()
