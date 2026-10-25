"""Discover official SOS precinct early-vote reports; persist aggregates, never rosters.

uv run --with curl-cffi==0.16.3 python dashboard/scripts/collect_expansion_sos.py --probe
uv run --with curl-cffi==0.16.3 python dashboard/scripts/collect_expansion_sos.py --counties harris bexar
"""
from __future__ import annotations
import argparse, base64, collections, concurrent.futures, csv, datetime as dt, hashlib, io, json, pathlib, re, threading, time
from curl_cffi import requests
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'sources/precinct-expansion/discovery'
DATA=ROOT/'dashboard/data'
STATE=json.loads((DATA/'statewide.json').read_text())
COUNTIES={c['id']:c for c in STATE['counties']}
TARGETS='harris bexar collin denton fortbend williamson hidalgo elpaso nueces galveston brazoria cameron lubbock jefferson johnson comal guadalupe parker rockwall bastrop brazos grayson smith webb ector midland potter randall tomgreen wichita hunt kaufman'.split()
LOCK=threading.Lock()
EXACT_ROW_DEDUP={('elpaso','2024-10-22'):1,('elpaso','2024-10-23'):1,('nacogdoches','2024-10-21'):1,('willacy','2024-10-21'):1,('willacy','2024-10-23'):2}
def normalize(value):
    value=value.strip().lstrip('\ufeff').upper()
    return str(int(value)) if value.isdigit() else value

def fetch(county,date):
    c=COUNTIES[county];date=dt.date.fromisoformat(date)
    if date.year==2024:
        url='https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do'
        form=dict(idElection='49664',selectedDate=f'{date} 00:00:00.0',electionDate=',',earlyVoteFlag='true',downloadElectionFileCSVFlag='true',idTown=str(c['state_id']))
    else:
        url=f"https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat?type=EVR_EARLYVOTING&electionId=53815&electionDate={date:%m/%d/%Y}&county={c['name'].upper()}&countyId={c['state_id']}&format=csv"
        form=None
    response=requests.post(url,data=form,impersonate='chrome',timeout=45) if form else requests.get(url,impersonate='chrome',timeout=45)
    if response.status_code!=200:raise ValueError(f'HTTP {response.status_code}')
    raw=response.content
    if not form:
        obj=json.loads(raw)
        if not isinstance(obj,dict) or not obj.get('upload'):raise ValueError('no upload')
        raw=base64.b64decode(obj['upload'].split(',')[-1])
    text=raw.decode('utf-8-sig')
    reader=csv.DictReader(io.StringIO(text));headers=reader.fieldnames or []
    required={'ID_VOTER','VOTING_METHOD','PRECINCT'}
    if not required.issubset(headers):raise ValueError('roster fields unavailable')
    counts=collections.Counter();inperson=set();records=0;deduplicated=0
    known_duplicate_file=(county,str(date)) in EXACT_ROW_DEDUP
    original={} if known_duplicate_file else None
    raw_lines=text.splitlines(keepends=True) if known_duplicate_file else None
    last_line=1
    for row in reader:
        raw_record=''.join(raw_lines[last_line:reader.line_num]).rstrip('\r\n') if known_duplicate_file else None
        last_line=reader.line_num
        voter=row['ID_VOTER'].strip();records+=1
        if not voter:raise ValueError('blank voter identifier')
        if row['VOTING_METHOD'].strip()=='IN-PERSON':
            if voter in inperson:
                if known_duplicate_file and deduplicated<EXACT_ROW_DEDUP[(county,str(date))] and original[voter]==(tuple(row[k] for k in headers),raw_record):
                    deduplicated+=1
                    continue
                raise ValueError('duplicate IN-PERSON voter identifier within daily roster')
            if known_duplicate_file:original[voter]=(tuple(row[k] for k in headers),raw_record)
            inperson.add(voter);counts[normalize(row['PRECINCT']) or 'UNASSIGNED']+=1
        elif row['VOTING_METHOD'].strip()!='MAIL-IN':raise ValueError('unexpected voting method')
    if not counts:raise ValueError('no in-person records; not confirmed zero')
    control=next((r for r in c['days'] if r[f'date_{date.year}']==str(date)),{})
    expected=control.get(f'votes_{date.year}')
    delta=sum(counts.values())-expected if expected is not None else None
    note='Official Texas SOS daily IN-PERSON residence-precinct roster; mail excluded. Raw voter records decoded and aggregated only in memory.'
    if deduplicated:note+=f' {deduplicated} byte-identical repeated IN-PERSON CSV record(s) removed under the reviewed county/date-specific exact-row policy; each unique voter counted once in the original precinct.'
    if delta:note+=f' Roster total {sum(counts.values())} differs from separately published SOS county daily total {expected} by {delta:+}; no votes allocated to close the difference.'
    daily=dict(county=county,date=str(date),counts=dict(sorted(counts.items())),source=url if not form else f'{url}?idElection=49664&selectedDate={date}&idTown={c["state_id"]}',sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat(),note=note,cumulative=False)
    audit=dict(county=county,date=str(date),state_id=c['state_id'],records=records,deduplicated_exact_rows=deduplicated,in_person=sum(counts.values()),precincts=len(counts),county_daily_control=expected,control_delta=delta,sha256=daily['sha256'],source=daily['source'],status='available')
    return daily,audit,inperson

def persist(county,year,days,kind):
    path=DATA/kind/county/f'{year}-series.json';path.parent.mkdir(parents=True,exist_ok=True)
    old={r['date']:r for r in json.loads(path.read_text())} if path.exists() else {}
    old.update({r['date']:r for r in days})
    path.write_text(json.dumps([old[k] for k in sorted(old)],indent=2)+'\n')

def collect(county,probe=False):
    audits=[]
    for year in (2024,2026):
        start=dt.date(year,10,21 if year==2024 else 19)
        count=1 if probe else 12 if year==2024 else 5
        days=[];seen=set()
        for day in range(count):
            date=str(start+dt.timedelta(days=day))
            try:
                daily,audit,voters=fetch(county,date)
                if seen.intersection(voters):raise ValueError('repeated IN-PERSON identifiers across dates')
                seen.update(voters);days.append(daily);audits.append(audit)
            except Exception as error:
                audits.append(dict(county=county,date=date,status='unavailable',error=f'{type(error).__name__}: {error}'))
                if probe:break
        if days:
            persist(county,year,days,'cache')
            if year==2024:persist(county,year,days,'history-cache')
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/f'{county}.json').write_text(json.dumps(audits,indent=2)+'\n')
    with LOCK:print(json.dumps(dict(county=county,available=sum(x['status']=='available' for x in audits),errors=[x['error'] for x in audits if x['status']!='available'],precincts=[x['precincts'] for x in audits if x['status']=='available'],control_deltas=[x['control_delta'] for x in audits if x['status']=='available'])),flush=True)
    return audits

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true');parser.add_argument('--remaining',action='store_true');parser.add_argument('--remaining-full',action='store_true');parser.add_argument('--counties',nargs='+',default=TARGETS);parser.add_argument('--workers',type=int,default=6);args=parser.parse_args()
    if args.remaining or args.remaining_full:
        args.probe=args.remaining
        excluded=set(TARGETS)|set('travis dallas montgomery bell hays ellis mclennan hockley madison tarrant'.split())
        if args.remaining_full:excluded.update(['nacogdoches','willacy'])
        args.counties=[c for c in COUNTIES if c not in excluded]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(lambda c:collect(c,args.probe),args.counties))
    summary=OUT/('remaining-probe-summary.json' if args.remaining else 'probe-summary.json' if args.probe else 'collection-summary.json')
    previous={(a['county'],a['date']):a for a in json.loads(summary.read_text())} if summary.exists() else {}
    previous.update({(a['county'],a['date']):a for r in results for a in r})
    summary.write_text(json.dumps(list(previous.values()),indent=2)+'\n')
