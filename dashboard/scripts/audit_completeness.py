#!/usr/bin/env python3
"""Independent, completed-day in-person controls. Never read or persist voter rosters.

python dashboard/scripts/audit_completeness.py [--through 2026-10-23] [--offline]
Only official aggregate HTML/PDF reports and aggregate JSON reach disk. Current
SOS reports alone do not establish completion. Missing controls fail closed.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT.parent / 'sources/completeness'
OUT = ROOT / 'data/completeness.json'
STAMP = datetime.now(timezone.utc).isoformat()
NUM = r'[\d,]+'


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def fetch(url, name, offline=False):
    """name identifies a previously inspected aggregate report, never a roster."""
    path = EVIDENCE / name
    if offline:
        raw = path.read_bytes()
    else:
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0 TexasTurnout aggregate audit'}), timeout=45) as response:
                if response.status != 200:
                    raise ValueError(f'official aggregate HTTP {response.status}')
                raw = response.read()
        except Exception:
            # Reuse the project's browser challenge transport for this official
            # aggregate host. No new browser profile or account is introduced.
            if 'www.dallascountyvotes.org/' not in url:
                raise
            result = subprocess.run(['uv','run','--with','curl-cffi==0.16.3','--with','playwright',
                                     'python',str(ROOT/'scripts/transport.py')],
                                    input=json.dumps({'url':url}).encode(),capture_output=True,timeout=100,check=True)
            raw=result.stdout
        if not raw:
            raise ValueError('empty official aggregate')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    archive = EVIDENCE / 'raw' / (hashlib.sha256(raw).hexdigest() + path.suffix)
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(raw)
    return raw


def pdf(raw):
    if not raw.startswith(b'%PDF'):
        raise ValueError('not an aggregate PDF')
    result = subprocess.run(['pdftotext', '-layout', '-', '-'], input=raw, capture_output=True, timeout=30, check=True)
    return result.stdout.decode()


def record(county, year, when, daily, cumulative, source, raw, note):
    if when.year != year or daily is not None and daily < 0 or cumulative is not None and cumulative < 0:
        raise ValueError('invalid aggregate control')
    return dict(county=county, year=year, date=when.isoformat(), daily=daily,
                cumulative=cumulative, source=source, sha256=hashlib.sha256(raw).hexdigest(),
                retrieved_at=STAMP, scope='in_person', completed=True, note=note,
                precinct_total=None, precinct_source=None, precinct_sha256=None)


def sequence(county, year, values, source, raw, through, note):
    first = date(year, 10, 21 if year == 2024 else 19)
    last = first + timedelta(days=11)
    values = {when: n for when, n in values.items() if first <= when <= last}
    if not values or min(values) != first:
        raise ValueError('missing start of election series')
    rows, total, missing = [], 0, False
    for i in range(12):
        when = first + timedelta(days=i)
        if when not in values:
            missing = True
            continue
        n = values[when]
        if year == 2026 and n == 0:
            # Native tables often pre-fill all twelve future dates with zero.
            # A later wall-clock date cannot promote that stale placeholder.
            missing = True
            continue
        if n < 0:
            raise ValueError('negative count')
        total += n
        if year == 2026 and when > through:
            continue
        # A gap cannot silently turn a partial sum into a cumulative control.
        rows.append(record(county, year, when, n, None if missing else total, source, raw, note))
    return rows


def harris(through, offline):
    source = 'https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf'
    raw = fetch(source, 'harris.pdf', offline)
    text = pdf(raw)
    if 'November 3, 2026' not in text:
        raise ValueError('wrong Harris election')
    row = re.search(r'Early In[- ]Person Voters:\s*(.*)', text, re.I)
    if not row:
        raise ValueError('Harris in-person row missing; never substitute total early voters')
    values = [int(n.replace(',', '')) for n in re.findall(NUM, row[1])]
    if len(values) != 13 or sum(values[:12]) != values[12]:
        raise ValueError('Harris daily/cumulative arithmetic')
    return sequence('harris', 2026, {date(2026,10,19)+timedelta(days=i):n for i,n in enumerate(values[:12])}, source, raw, through,
                    'Independent county early in-person check-ins row only; mail and combined early-voter rows excluded. Prior calendar days only; unofficial administrative revisions remain possible.')


def tarrant(through, offline, year=2026):
    source = f'https://www.tarrantcountytx.gov/content/dam/main/elections/{year}/11{year%100:02}/ev_reports/Early_Voting_Daily_Totals.pdf'
    raw = fetch(source, f'tarrant{year}.pdf', offline)
    text = pdf(raw)
    if f'November {3 if year == 2026 else 5}, {year}' not in text or 'Early Voting In Person Totals' not in text:
        raise ValueError('wrong Tarrant election or scope')
    dates = re.search(r'^\s*Total\s+((?:\d{2}/\d{2}\s*)+)\n', text, re.M)
    counts = re.search(r'^Total\s+('+NUM+r'(?:\s+'+NUM+r')+)\s*$', text, re.M)
    if not dates or not counts:
        raise ValueError('Tarrant aggregate table changed')
    days = [datetime.strptime(f'{d}/{year}', '%m/%d/%Y').date() for d in dates[1].split()]
    numbers = [int(n.replace(',', '')) for n in counts[1].split()]
    if len(numbers) != len(days)+1 or sum(numbers[1:]) != numbers[0]:
        raise ValueError('Tarrant daily/cumulative arithmetic')
    # Same-date report must be generated after the 7pm closing hour; a previous-day
    # publication is sufficient regardless of its time. Never accept an evening-in-progress report.
    generated_dates = re.findall(r'([A-Z][a-z]+ \d{1,2}, '+str(year)+r')', text)
    generated_time = re.search(r'(\d{1,2}):(\d{2}):(\d{2})(AM|PM)', text)
    if not generated_dates or not generated_time:
        raise ValueError('Tarrant report generation time absent')
    generated_day = datetime.strptime(generated_dates[-1], '%B %d, %Y').date()
    hour = int(generated_time[1]) % 12 + (12 if generated_time[4] == 'PM' else 0)
    values = {d:n for d,n in zip(days,numbers[1:]) if d < generated_day or d == generated_day and hour >= 19}
    return sequence('tarrant', year, values, source, raw, through,
                    'Independent county polling-place in-person totals; report generated after the included day closed. Residence precinct exports with missing records are not certified by this report.')


def fortbend(through, offline):
    landing = 'https://www.fortbendcountytx.gov/government/departments/elections-voter-registration/early-voting-statistics'
    page = fetch(landing, 'fortbendpage.html', offline).decode()
    links = re.findall(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', page, re.I|re.S)
    matches = [urljoin(landing,html.unescape(u)) for u,label in links if 'Early Voting by Personal Appearance Statistics' in re.sub('<[^>]+>', '', label)]
    if len(set(matches)) != 1:
        raise ValueError('Fort Bend dedicated in-person report link missing or ambiguous')
    source = matches[0]
    if '/2026/' not in source or not source.endswith('.pdf'):
        raise ValueError('wrong Fort Bend election link')
    raw = fetch(source, 'fortbend.pdf', offline)
    text = pdf(raw)
    if 'November 3, 2026 General Election' not in text or 'Early Voting by Personal Appearance' not in text:
        raise ValueError('wrong Fort Bend PDF election/scope')
    section = text.split('Grand Totals',1)[1].split('TOTALS BY JURISDICTION',1)[0]
    pairs = re.findall(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d\d/\d\d/\d\d)\s+(\d[\d,]*)\s*$',section,re.M)
    values = {datetime.strptime(d,'%m/%d/%y').date():int(n.replace(',','')) for d,n in pairs}
    site_values={}
    for d,numbers in re.findall(r'^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d\d/\d\d/\d\d)\s+([\d,]+(?:[ \t]+[\d,]+)+)[ \t]*$', text.split('Grand Totals',1)[0], re.M):
        when=datetime.strptime(d,'%m/%d/%y').date()
        site_values[when]=site_values.get(when,0)+sum(int(n.replace(',','')) for n in numbers.split())
    if any(site_values.get(d)!=n for d,n in values.items() if n>0):
        raise ValueError('Fort Bend site totals disagree with grand total')
    total = re.search(r'^TOTAL\s+('+NUM+r')\s*$', section,re.M)
    if not total or sum(values.values()) != int(total[1].replace(',','')):
        raise ValueError('Fort Bend grand total arithmetic')
    return sequence('fortbend',2026,values,source,raw,through,
                    'Dedicated county personal-appearance grand totals, reconciled to daily site table and total; prior calendar days only. Zero future placeholders are never accepted.')


def bexar(through, offline):
    source = 'https://earlyvotecounts.bexar.org/'
    raw = fetch(source,'bexar.html',offline)
    text = raw.decode()
    found = re.search(r'BALLOTS CAST THIS DATE\s+(\d\d/\d\d/\d{4})',text)
    if not found or 'November 3, 2026' not in text or 'Total in Person' not in text:
        raise ValueError('wrong Bexar date/election/scope')
    when = datetime.strptime(found[1],'%m/%d/%Y').date()
    if when > through:
        return []
    body = re.search(r'<tbody>(.*?)</tbody>',text,re.S)[1]
    totals = [0,0,0]
    rows = re.findall(r'<tr>(.*?)</tr>',body,re.S)
    if len(rows) < 10:
        raise ValueError('Bexar site table unexpectedly short')
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>',row,re.S)
        if len(cells) != 4:
            raise ValueError('Bexar site columns changed')
        numbers = [int(re.sub('<[^>]+>','',c).strip().replace(',','')) for c in cells[1:]]
        if numbers[0] + numbers[1] != numbers[2]:
            raise ValueError('Bexar site arithmetic')
        totals = [a+b for a,b in zip(totals,numbers)]
    # The source footer contains zero placeholders. Only validated site rows count.
    return [record('bexar',2026,when,totals[0],totals[2],source,raw,
                   f'Independent county in-person polling-location report; {len(rows)} site rows individually reconcile daily + previous = cumulative. Unpopulated footer ignored. Earlier dates are not inferred from this cumulative report.')]


def vendor(county, year, through, offline):
    source=f'https://updates.electionlink.net/widgets/{county}tx/{year}-11-{3 if year==2026 else 5:02}/EarlyVotingGraphs.html'
    raw=fetch(source,f'{county}-{year}.html',offline)
    text=raw.decode('utf-8-sig')
    pairs=re.findall(r"evData.push\(\['([^']+)',(\d+)\]\)",text)
    values={datetime.strptime(d,'%m/%d/%Y').date():int(n) for d,n in pairs}
    if len(values)!=len(pairs) or any(d.year!=year for d in values):
        raise ValueError('duplicate/wrong vendor election dates')
    if f'{year}-11-' not in source or not values:
        raise ValueError('vendor daily series missing')
    return sequence(county,year,values,source,raw,through,
                    'County-linked ElectionLink ordinary Early Vote daily graph; separate provisional and mail arrays excluded. Active calendar day and future days excluded, even when the live graph has positive counts.')


def workbook(raw):
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared=[''.join(e.itertext()) for e in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        result=[]
        for row in ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).findall('.//m:row',ns):
            values={}
            for cell in row:
                value=cell.find('m:v',ns)
                value=value.text if value is not None else ''
                if cell.get('t')=='s':value=shared[int(value)]
                elif cell.get('t')=='inlineStr':value=''.join(cell.find('m:is',ns).itertext())
                if value:values[re.sub(r'\d+','',cell.get('r'))]=value
            result.append(values)
        return result


def dallas(through,offline,year=2026):
    if year==2024:
        source='https://www.dallascountyvotes.org/wp-content/uploads/2024/11/Early-Voting-Turnout-By-Date-Location-Report_11.01.24.xlsx'
        # Immutable aggregate already acquired and verified by the historical
        # collector, distinct from the residence-precinct workbook.
        path=ROOT.parent/'sources/refresh-2026-10-23/county-a/dallas-2024-location-totals.xlsx'
        raw=path.read_bytes()
    else:
        landing='https://www.dallascountyvotes.org/election-results/historical/november-3-2026-general-and-joint-election/'
        page=fetch(landing,'dallaspage.html',offline).decode()
        links=re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',page,re.S|re.I)
        selected=[html.unescape(u) for u,label in links if 'Daily Cumulative Early Voting Totals by Vote Center' in re.sub('<[^>]+>','',label)]
        if len(set(selected))!=1:raise ValueError('Dallas aggregate link missing or ambiguous')
        source=urljoin(landing,selected[0])
        if not re.search(r'/2026/.*Early-Voting-Turnout-By-Date[^/]*\.xlsx$',source,re.I):raise ValueError('wrong Dallas aggregate filename')
        raw=fetch(source,'dallas.xlsx',offline)
    rows=workbook(raw)
    if not any(f'{year} General' in v for row in rows for v in row.values()):raise ValueError('wrong Dallas workbook election')
    header=next(row for row in rows if row.get('A') in ('Vote Center Name','Vote Center'))
    totals=next(row for row in rows if row.get('A')=='Daily Unofficial Total')
    columns={c:(date(1899,12,30)+timedelta(days=int(float(v)))) for c,v in header.items() if re.fullmatch(r'\d{5}',v)}
    values={d:int(totals[c]) for c,d in columns.items()}
    cumulative_column=next(c for c,v in header.items() if v=='Cumulative Total')
    if len(values)!=12 or sum(values.values())!=int(totals[cumulative_column]):raise ValueError('Dallas date/cumulative arithmetic')
    totalindex=rows.index(totals)
    sites=[row for row in rows[totalindex+1:] if row.get('A')]
    if len(sites)<10:raise ValueError('Dallas vote center universe unexpectedly short')
    for c in columns:
        if sum(int(row.get(c,'0')) for row in sites)!=int(totals[c]):raise ValueError('Dallas daily site sum mismatch')
    for row in sites:
        if sum(int(row.get(c,'0')) for c in columns)!=int(row[cumulative_column]):raise ValueError('Dallas site cumulative mismatch')
    # Dated daily report filenames identify a closed reporting cutoff; never
    # certify zeros after that cutoff, even if a caller asks for a later day.
    match=re.search(r'_(\d{2}\.\d{2}\.\d{2})\.xlsx$',source)
    if not match:raise ValueError('Dallas dated report cutoff absent')
    cutoff=datetime.strptime(match[1],'%m.%d.%y').date()
    values={d:n for d,n in values.items() if d<=cutoff}
    return sequence('dallas',year,values,source,raw,through,
                    f'Official dated county in-person location workbook through {cutoff}; every site and daily total reconciled. Mail excluded; future zero placeholders excluded. County administrative revisions can change prior dates.')


def historical():
    """Closed 2024 official SOS aggregate reports, fetched in 2026, not live 2026 SOS."""
    statewide=json.loads((ROOT/'data/statewide.json').read_text())
    ids={c['state_id']:c['id'] for c in statewide['counties']}
    if len(ids)!=254:
        raise ValueError('historical county universe incomplete')
    result=[]
    for path in sorted((ROOT/'data/statewide-cache/2024').glob('*.json')):
        cache=json.loads(path.read_text())
        source=cache['source']; when=date.fromisoformat(cache['date'])
        if cache['year']!=2024 or when.year!=2024 or source['year']!=2024 or source['date']!=str(when) or len(cache['rows'])!=254:
            raise ValueError('historical aggregate cache election/date/universe mismatch')
        if len({r['state_id'] for r in cache['rows']})!=254 or source['status']!='current':
            raise ValueError('historical aggregate county identity/status mismatch')
        for row in cache['rows']:
            if row['votes'] is None or row['cumulative'] is None:
                continue
            out=record(ids[row['state_id']],2024,when,row['votes'],row['cumulative'],source['url'],b'',
                       'Closed 2024 election official Texas SOS in-person aggregate retrieved in 2026. Source POST form and transport hash remain in the immutable statewide aggregate cache. This does not certify the live 2026 SOS feed.')
            out['sha256']=source['sha256'];out['retrieved_at']=source['retrieved_at'];result.append(out)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    yesterday=datetime.now(ZoneInfo('America/Chicago')).date()-timedelta(days=1)
    parser.add_argument('--through',type=date.fromisoformat,default=min(yesterday,date(2026,10,30)))
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    if args.through>yesterday:
        parser.error('an active calendar day cannot be certified complete')
    # Retain prior exact-date controls if a rotating report fails or ceases to
    # expose old days. Never carry a prior total into a later date.
    previous=json.loads(OUT.read_text()) if OUT.exists() else {'controls':[]}
    controls={(r['county'],r['year'],r['date']):r for r in previous['controls'] if r.get('scope')=='in_person' and r.get('completed') is True and date.fromisoformat(r['date'])<=args.through}
    for row in historical():controls[(row['county'],row['year'],row['date'])]=row
    jobs={
        'harris':lambda:harris(args.through,args.offline),
        'tarrant-2026':lambda:tarrant(args.through,args.offline),
        'tarrant-2024':lambda:tarrant(args.through,args.offline,2024),
        'fortbend':lambda:fortbend(args.through,args.offline),
        'bexar':lambda:bexar(args.through,args.offline),
        'dallas':lambda:dallas(args.through,args.offline),
        'dallas-2024':lambda:dallas(args.through,args.offline,2024),
        **{f'{c}-{y}':(lambda c=c,y=y:vendor(c,y,args.through,args.offline)) for c in ['travis','montgomery'] for y in [2024,2026]},
    }
    errors=[]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures={name:executor.submit(fn) for name,fn in jobs.items()}
        for name,future in futures.items():
            try:
                rows=future.result()
                for row in rows:controls[(row['county'],row['year'],row['date'])]=row
            except Exception as error:
                errors.append({'collector':name,'error':type(error).__name__+': '+str(error),'retained_exact_dates':True})
    rows=sorted(controls.values(),key=lambda r:(r['county'],r['year'],r['date']))
    payload={'schema_version':1,'generated_at':STAMP,'controls':rows}
    atomic(OUT,payload)
    coverage={c:sorted(r['date'] for r in rows if r['county']==c and r['year']==2026) for c in sorted({r['county'] for r in rows if r['year']==2026})}
    audit={'generated_at':STAMP,'through':str(args.through),'current_counties':len(coverage),'current_controls':sum(map(len,coverage.values())),'historical_controls':sum(r['year']==2024 for r in rows),'current_coverage':coverage,'errors':errors,'policy':'Only independent official aggregate controls; current SOS alone is insufficient. Active dates excluded. No self-certification from precinct rosters, extrapolation, voter data retention or geographic allocation. Unlisted county/date remains unqualified.'}
    atomic(EVIDENCE/'audit.json',audit)
    print(json.dumps(audit))

if __name__=='__main__':main()
