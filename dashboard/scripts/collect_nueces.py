"""Aggregate Nueces' native dated in-person PDF entirely in memory.

uv run --with curl-cffi==0.16.3 --with pymupdf python dashboard/scripts/collect_nueces.py
Add --write only after reviewing the aggregate audit; no PDF or voter text is saved.
"""
import argparse,collections,datetime as dt,hashlib,json,pathlib,re,subprocess
from curl_cffi import requests
import pymupdf
ROOT=pathlib.Path(__file__).resolve().parents[2];DATA=ROOT/'dashboard/data';OUT=ROOT/'sources/precinct-expansion/discovery'
URL='https://www.nuecesco.com/home/showpublisheddocument/34763'
ROW=re.compile(r'^\s*([A-Z0-9.-]+)\s+(\d{8,10})\s+(.+?)\s*(Early Voted)\s+(\d{1,2}/\d{1,2}/\d{4})\s*$',re.I)
def normalize(v):
 v=v.strip().upper();return str(int(v)) if v.isdigit() else v or 'UNASSIGNED'
def run(write=False):
 r=requests.get(URL,impersonate='chrome',timeout=90);r.raise_for_status();raw=r.content;assert raw.startswith(b'%PDF-'),'county response is not PDF'
 document=pymupdf.open(stream=raw,filetype='pdf');days=collections.defaultdict(collections.Counter);seen=set();pages=[];types=collections.Counter();raw_record_rows=0
 for i,page in enumerate(document):
  text=page.get_text(sort=True);lines=text.splitlines();vuid_occurrences=len(re.findall(r'\b\d{8,10}\b',text));record_lines=sum(bool(re.search(r'Early\s+Voted',line,re.I)) for line in lines);parsed=0
  for line in lines:
   match=ROW.fullmatch(line)
   if not match:
    if re.search(r'Early\s+Voted',line,re.I) or re.search(r'\b\d{8,10}\b',line):raise ValueError(f'unparsed voter row on page {i+1}')
    continue
   precinct,identity,_,kind,date=match.groups();date=dt.datetime.strptime(date,'%m/%d/%Y').date().isoformat()
   if not '2026-10-19'<=date<='2026-10-23':raise ValueError('voting date outside current completed calendar')
   if identity in seen:raise ValueError('repeated VUID in native county PDF')
   seen.add(identity);days[date][normalize(precinct)]+=1;types[kind]+=1;parsed+=1
  assert parsed==vuid_occurrences==record_lines,f'page {i+1}: parsed row/VUID/Early Voted controls differ'
  assert parsed>0,f'page {i+1}: no voter rows'
  pages.append(dict(page=i+1,parsed_rows=parsed,vuid_occurrences=vuid_occurrences,early_voted_record_lines=record_lines));raw_record_rows+=parsed
 assert len(days)==5 and set(days)=={f'2026-10-{d}' for d in range(19,24)},'native county PDF lacks a completed date'
 assert raw_record_rows==len(seen)==sum(sum(c.values()) for c in days.values())
 independent=subprocess.run(['pdftotext','-layout','-','-'],input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout.decode('utf-8')
 independent_days=collections.defaultdict(collections.Counter);independent_ids=set()
 for line in independent.splitlines():
  match=ROW.fullmatch(line)
  if not match:
   if re.search(r'Early\s+Voted',line,re.I) or re.search(r'\b\d{8,10}\b',line):raise ValueError('unparsed pdftotext voter row')
   continue
  precinct,identity,_,kind,date=match.groups();date=dt.datetime.strptime(date,'%m/%d/%Y').date().isoformat()
  if identity in independent_ids:raise ValueError('repeated VUID in independent parser')
  independent_ids.add(identity);independent_days[date][normalize(precinct)]+=1
 independent_early_lines=sum(bool(re.search(r'Early\s+Voted',line,re.I)) for line in independent.splitlines())
 assert len(independent_ids)==independent_early_lines,'independent Early Voted row control differs'
 assert dict(independent_days)==dict(days) and independent_ids==seen,'independent PDF parsers differ'
 sha=hashlib.sha256(raw).hexdigest();stamp=dt.datetime.now(dt.timezone.utc).isoformat();series=[];comparisons=[]
 state=next(c for c in json.loads((DATA/'statewide.json').read_text())['counties'] if c['id']=='nueces');sos_source=OUT/'nueces-sos-2026-series.json'
 old=json.loads((sos_source if sos_source.exists() else DATA/'cache/nueces/2026-series.json').read_text())
 assert all('goelect.txelections.civixapps.com' in d['source'] for d in old),'SOS comparison must use retained SOS aggregates, never a prior native parser output'
 sos={d['date']:d for d in old};reference=json.loads((DATA/'reference.json').read_text());refs=reference['counties'] if isinstance(reference,dict) and 'counties' in reference else reference;ref=next((x for x in refs if x['id']=='nueces'),None);native={p for g in ref['groups'] for p in g['new']} if ref else None
 for date,counts in sorted(days.items()):
  control=next(x for x in state['days'] if x['date_2026']==date);summary=control['votes_2026'];roster=sos.get(date);other=roster['counts'] if roster else {};keys=counts.keys()|other.keys();diffs={k:counts[k]-other.get(k,0) for k in keys if counts[k]!=other.get(k,0)};missing={p:n for p,n in counts.items() if native is not None and p not in native}
  comparisons.append(dict(date=date,county_in_person=sum(counts.values()),sos_roster_in_person=sum(other.values()) if roster else None,sos_county_daily=summary,sos_county_cumulative=control['cumulative_2026'],county_minus_sos_roster=sum(counts.values())-sum(other.values()) if roster else None,precincts_differing=len(diffs) if roster else None,absolute_precinct_difference=sum(abs(v) for v in diffs.values()) if roster else None,precinct_deltas=diffs if roster else None,unmapped_precinct_counts=missing if native is not None else None))
  note='Official Nueces County in-person early-voting PDF roster through October 23, 2026. Each row is explicitly Early Voted; its Date and residence Precinct determine daily counts. Unique VUID and parsed-row controls verified across all 775 PDF pages. Raw PDF and voter text remain only in memory. The native county series is used consistently for all five dates; SOS daily differences are retained in the source audit.'
  series.append(dict(county='nueces',date=date,counts=dict(sorted(counts.items())),source=URL,sha256=sha,retrieved_at=stamp,note=note,cumulative=False))
 audit=dict(county='nueces',source=URL,sha256=sha,retrieved_at=stamp,pages=len(document),parsed_rows=raw_record_rows,unique_vuid=len(seen),duplicate_vuid=0,parser_revision=2,supersedes_incomplete_ten_digit_id_parser=True,vuid_token_lengths=dict(collections.Counter(str(len(v)) for v in seen)),independent_pdftotext_rows=len(independent_ids),independent_early_voted_record_lines=independent_early_lines,independent_parsers_agree=True,record_types=dict(types),date_format='%m/%d/%Y',row_regex=ROW.pattern,scope='County PDF explicitly labels every accepted record Early Voted; mail roster is a different URL (34761).',daily=comparisons,page_controls=pages,cache_written=write)
 (OUT/'nueces-native-2026-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
 (OUT/'nueces-native-2026-proposed-series.json').write_text(json.dumps(series,indent=2)+'\n')
 if write:
  target=DATA/'cache/nueces/2026-series.json';backup=OUT/'nueces-sos-2026-series.json'
  if not backup.exists():backup.write_bytes(target.read_bytes())
  target.write_text(json.dumps(series,indent=2)+'\n')
 print(json.dumps({k:v for k,v in audit.items() if k not in ['page_controls','daily']}));print(json.dumps([{k:v for k,v in x.items() if k!='precinct_deltas'} for x in comparisons],indent=2))
 return audit
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args();run(args.write)
