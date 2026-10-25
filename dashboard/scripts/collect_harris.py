"""Aggregate official Harris EV ZIP rosters in memory; never save voter records.

uv run --with curl-cffi==0.16.3 python dashboard/scripts/collect_harris.py
"""
import collections,concurrent.futures,csv,datetime as dt,hashlib,io,json,pathlib,zipfile
from curl_cffi import requests
ROOT=pathlib.Path(__file__).resolve().parents[2];DATA=ROOT/'dashboard/data';OUT=ROOT/'sources/precinct-expansion/discovery'
URLS={2024:'https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_1124.zip',2026:'https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_ToPost_1126.zip'}
def norm(v):
 v=v.strip().upper();return str(int(v)) if v.isdigit() else v or 'UNASSIGNED'
def parse_date(v):
 for fmt in ['%m/%d/%Y','%m/%d/%Y %H:%M:%S','%Y-%m-%d','%m/%d/%Y %I:%M:%S %p']:
  try:return dt.datetime.strptime(v.strip(),fmt).date()
  except ValueError:pass
 raise ValueError('unrecognized county activity date')
def run(year):
 url=URLS[year];response=requests.get(url,impersonate='chrome',timeout=90);response.raise_for_status();raw=response.content;archive=zipfile.ZipFile(io.BytesIO(raw))
 days=collections.defaultdict(collections.Counter);members=[];seen=set();county_ids=set();repeats=0;id_precinct={};conflicts=0;global_id_blanks=0;county_id_blanks=0;headers_seen=[]
 start=dt.date(year,10,21 if year==2024 else 19);end=dt.date(year,11,1) if year==2024 else dt.date(2026,10,23)
 for member in archive.namelist():
  if not member.lower().endswith('.csv'):continue
  payload=archive.read(member);reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')));headers=reader.fieldnames;headers_seen.append(headers)
  assert {'StateVoterID','IDNumber','Precinct','ActivityDate'}.issubset(headers),f'unsupported county fields: {headers}'
  date_counts=collections.Counter()
  for row in reader:
   date=parse_date(row['ActivityDate'])
   if not start<=date<=end:raise ValueError('unexpected activity date outside early-vote calendar')
   precinct=norm(row['Precinct']);identity=row['StateVoterID'].strip();county_id=row['IDNumber'].strip()
   global_id_blanks+=not bool(identity);county_id_blanks+=not bool(county_id)
   if not identity:raise ValueError('blank state voter ID')
   if identity in seen:
    repeats+=1
    if id_precinct[identity]!=(date,precinct):conflicts+=1
    raise ValueError('repeated in-person voter identifier in county archive')
   seen.add(identity);county_ids.add(county_id);id_precinct[identity]=(date,precinct);date_counts[str(date)]+=1;days[str(date)][precinct]+=1
  members.append(dict(name=member,sha256=hashlib.sha256(payload).hexdigest(),dates=dict(date_counts),fields=headers))
 wanted={str(start+dt.timedelta(days=i)) for i in range((end-start).days+1)}
 assert set(days)==wanted,'county archive has missing dates'
 stamp=dt.datetime.now(dt.timezone.utc).isoformat();sha=hashlib.sha256(raw).hexdigest();series=[]
 state=json.loads((DATA/'statewide.json').read_text());control=next(c for c in state['counties'] if c['id']=='harris');audit=[]
 sospath=DATA/f'cache/harris/{year}-series.json';saved=OUT/f'harris-sos-{year}-series.json'
 if sospath.exists() and not saved.exists():saved.write_bytes(sospath.read_bytes())
 for date,counts in sorted(days.items()):
  row=next(x for x in control['days'] if x[f'date_{year}']==date);expected=row[f'votes_{year}'];total=sum(counts.values());delta=total-expected if expected is not None else None
  note='Official Harris County in-person early-voting roster; mail and election-day archives excluded. CSV ActivityDate determines the daily vote; unique StateVoterID verified within and across all archive members. Raw voter records remain only in memory.'
  if delta:note+=f' Native county roster {total} versus SOS county daily total {expected} ({delta:+}); county source used consistently for this year and no votes allocated to close the difference.'
  series.append(dict(county='harris',date=date,counts=dict(sorted(counts.items())),source=url,sha256=sha,retrieved_at=stamp,note=note,cumulative=False))
  audit.append(dict(date=date,total=total,precincts=len(counts),sos_county_daily_control=expected,control_delta=delta))
 for kind in ['cache']+(['history-cache'] if year==2024 else []):
  p=DATA/f'{kind}/harris/{year}-series.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(series,indent=2)+'\n')
 result=dict(year=year,url=url,sha256=sha,retrieved_at=stamp,total_in_person=len(seen),unique_county_ids=len(county_ids),duplicate_identifiers=repeats,conflicting_identifiers=conflicts,global_id_blanks=global_id_blanks,county_id_blanks=county_id_blanks,members=members,days=audit)
 (OUT/f'harris-native-{year}-audit.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(dict(year=year,url=url,sha256=sha,total=len(seen),county_ids=len(county_ids),members=len(members),headers=headers_seen[0],days=audit)),flush=True)
 return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[2024,2026]))
