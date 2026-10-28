#!/usr/bin/env python3
"""Collin ordinary in-person residence-precinct aggregates; voter rows stay in memory.

The official dated workbook supplies vote date, residence precinct and Regular /
Provisional type separately. This adapter excludes provisional rows, never certifies
omitted precincts as zero, and withholds every cell affected by an unidentified or
conflicting ordinary voter record. Unknown precinct strings remain visible.
"""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
import argparse,hashlib,json,re,sys
from pathlib import Path
from urllib.parse import unquote,urljoin,urlparse
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dashboard/scripts'))
from collect_county_native import download,xlsx_rows
HEADER={'A':'VoterName','B':'VoterAddress','C':'CertificateNumber','D':'Precinct','E':'VoteDate','F':'VotedBallotStyle1','G':'VoteType','H':'VotedPhase','I':'Textbox51'}
LANDING='https://www.collincountytx.gov/Elections/rosters'

def vote_date(value):
 for fmt in ['%m/%d/%Y','%m/%d/%Y %I:%M:%S %p','%Y-%m-%d','%m/%d/%Y %H:%M:%S']:
  try:return datetime.strptime(value,fmt).date()
  except ValueError:pass
 if re.fullmatch(r'\d{5}(?:\.\d+)?',value):return date(1899,12,30)+timedelta(days=int(float(value)))
 raise ValueError('unrecognized county vote date')

def aggregate(rows,cutoff,source,sha256,retrieved_at):
 rows=iter(rows)
 header=next(rows,None)
 # The county removed its empty report-layout Textbox51 column on Oct27.
 # All eight analytical columns remain mandatory with their exact meanings.
 if header not in [HEADER,{k:v for k,v in HEADER.items() if k!='I'}]:raise ValueError('Collin workbook schema changed')
 if not date(2026,10,19)<=cutoff<=date(2026,10,30):raise ValueError('cutoff outside reviewed election calendar')
 counts=defaultdict(Counter);identities={};quarantine=set();dates=set();ordinary=Counter();provisional=Counter();duplicates=Counter();blank=Counter()
 for r in rows:
  if set(r)-set(HEADER):raise ValueError('unexpected county workbook columns')
  if r.get('G') not in {'Regular','Provisional'} or r.get('H')!='Early Voting':raise ValueError('unexpected county voting type or phase')
  when=vote_date(r.get('E','').strip())
  if not date(2026,10,19)<=when<=cutoff:raise ValueError('county row outside dated file window')
  if r['G']=='Provisional':
   provisional[when]+=1;continue
  dates.add(when);ordinary[when]+=1
  pct=r.get('D','').strip().upper().lstrip('0') or 'UNASSIGNED';identity=r.get('C','').strip();cell=(when,pct)
  if not identity:quarantine.add(cell);blank[when]+=1;continue
  if identity in identities:
   duplicates[when]+=1
   if identities[identity]!=cell:quarantine.update((identities[identity],cell))
   continue
  identities[identity]=cell;counts[when][pct]+=1
 if not dates:raise ValueError('no ordinary observations; not a confirmed zero roster')
 output=[]
 for when in sorted(dates):
  for d,p in quarantine:
   if d==when:counts[when].pop(p,None)
  unavailable=sorted(p for d,p in quarantine if d==when)
  output.append({'county':'collin','date':str(when),'counts':dict(sorted(counts[when].items())),'complete':False,'cumulative':False,'unavailable_precincts':unavailable,'source':source,'sha256':sha256,'retrieved_at':retrieved_at,'note':f'Official Collin dated ordinary Regular early in-person residence-precinct workbook through {cutoff}; Provisional rows excluded. Raw voter identities processed only in memory, globally deduplicated; blank/conflicting identity cells withheld. {ordinary[when]} ordinary source rows; {provisional[when]} provisional rows excluded; {duplicates[when]} repeated ordinary identities; {blank[when]} blank ordinary identities. Omitted precincts are unknown; no zero inference.'})
 return output

def discover_workbooks(html,through,strict_latest=False):
 candidates=defaultdict(set)
 for href in re.findall(r'href=["\']([^"\']+)',html,re.I):
  u=urljoin(LANDING,href.replace('&amp;','&'));p=urlparse(unquote(u))
  if p.hostname!='www.collincountytx.gov':continue
  m=re.fullmatch(r'.*/early-voters-through-october-(\d{1,2})-2026\.xlsx',p.path,re.I)
  if m and 19<=int(m[1])<=30:
   cutoff=date(2026,10,int(m[1]))
   if cutoff<=through:candidates[cutoff].add(u)
 if not candidates:raise ValueError('no dated county workbook link within requested cutoff')
 if strict_latest and len(candidates[max(candidates)])!=1:raise ValueError('ambiguous county workbook links for latest cutoff')
 return [(cutoff,next(iter(urls))) for cutoff,urls in sorted(candidates.items(),reverse=True) if len(urls)==1]

def discover(html,through):
 # Preserve the strict discovery contract for callers inspecting one edition.
 workbooks=discover_workbooks(html,through,strict_latest=True)
 if not workbooks:raise ValueError('ambiguous county workbook links for latest cutoff')
 return workbooks[0]

def collect(through,downloader=download):
 through=min(through,datetime.now(ZoneInfo('America/Chicago')).date()-timedelta(days=1))
 workbooks=discover_workbooks(downloader(LANDING).decode(),through)
 for cutoff,url in workbooks:
  try:
   raw=downloader(url)
   return aggregate(xlsx_rows(raw),cutoff,url,hashlib.sha256(raw).hexdigest(),datetime.now(timezone.utc).isoformat())
  except Exception as error:
   print(json.dumps({'county':'collin','date':str(cutoff),'status':'unavailable','error':type(error).__name__}),file=sys.stderr)
 raise ValueError('no usable completed Collin workbook publication')

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--county',choices=['collin'],default='collin')
 p.add_argument('--through',type=date.fromisoformat,required=True)
 p.add_argument('--output',type=Path)
 a=p.parse_args();out=collect(a.through)
 if a.output:
  a.output.parent.mkdir(parents=True,exist_ok=True)
  a.output.write_text(json.dumps(out,indent=2)+'\n')
  print(json.dumps({'county':'collin','days':len(out),'sha256':out[0]['sha256'],'daily':[{'date':s['date'],'votes':sum(s['counts'].values()),'precincts':len(s['counts']),'quarantined_precincts':s['unavailable_precincts']} for s in out]}))
 else:
  print(json.dumps(out,separators=(',',':')))
if __name__=='__main__':main()
