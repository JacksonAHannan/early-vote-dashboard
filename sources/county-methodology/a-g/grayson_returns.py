#!/usr/bin/env python3
"""Verify official native Grayson presidential canvass and independent summary."""
import argparse,csv,hashlib,io,json,re,subprocess
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[2]
LABELS={'trump':'REP Donald J. Trump/JD Vance','harris':'DEM Kamala D. Harris/Tim Walz','libertarian':'LIB Chase Oliver/Mike ter Maat','green':'GRN Jill Stein/Rudolph Ware','write_in':'Write-In Totals','cast':'Total Votes Cast'}
PDF_SHA='0b01141401a82dd96b2667294632347ea28e44d0fc123236f1e24457dd589118';SUMMARY_SHA='577c038b8ed1e5df2dd56074537677b80691e3db9da601a61866b81a8e8cc0cc'
def vectors(section):
 out={}
 for key,label in LABELS.items():
  rows=re.findall(r'^'+re.escape(label)+r'\s+([\d,]+)\s+[\d.]+%\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$',section,re.M)
  if len(rows)!=1:raise ValueError('candidate or cast row missing/duplicate')
  vals=[int(s.replace(',',''))for s in rows[0]]
  if vals[0]!=sum(vals[1:]):raise ValueError('candidate/method total does not conserve')
  out[key]=vals
 if any(sum(out[k][i]for k in LABELS if k!='cast')!=out['cast'][i]for i in range(4)):raise ValueError('presidential votes do not conserve all candidates/methods')
 return out

def parse_text(text,summary,reference):
 for report in [text,summary]:
  if any(s not in report for s in ['OFFICIAL RESULTS','November 5, 2024 General Election','Grayson County','President/Vice President'])or 'UNOFFICIAL RESULTS' in report:raise ValueError('not the official reviewed Grayson election scope')
 if reference['id']!='grayson':raise ValueError('wrong native county reference')
 expected={p for g in reference['groups']for p in g['old']};rows={}
 for page in text.split('\f'):
  if 'President/Vice President' not in page:continue
  matches=re.findall(r'^Precinct (\d+)\s*$',page,re.M)
  if len(matches)!=1:raise ValueError('missing native precinct heading')
  precinct=matches[0].lstrip('0')or'0'
  if precinct in rows:raise ValueError('duplicate normalized native precinct')
  rows[precinct]=vectors(page.split('President/Vice President',1)[1])
 if set(rows)!=expected:raise ValueError('canvass native precinct partition differs')
 section=summary.split('President/Vice President',1)[1].split('US Senator',1)[0];control=vectors(section)
 if control['trump'][0]!=50556 or control['harris'][0]!=14800:raise ValueError('official county candidate controls differ')
 for key in LABELS:
  if any(sum(v[key][i]for v in rows.values())!=control[key][i]for i in range(4)):raise ValueError('native precincts fail independently published candidate/method conservation')
 presidential={p:{k:rows[p][k][0]for k in ['harris','trump']}for p in sorted(rows)}
 if any(presidential.get(p)!=v for p,v in reference['presidential'].items()):raise ValueError('conflicts with existing native classified votes')
 return {'county':'grayson','status':'official_final','election_date':'2024-11-05','presidential':presidential,'existing_native_returns':len(reference['presidential']),'additional_native_returns':len(rows)-len(reference['presidential']),'county_totals':{k:v[0]for k,v in control.items()},'method_vectors':control,'method':'Official November19 Grayson2024 precinct canvass: exact full41 native precinct partition; all13 existing native presidential returns agree. Every candidate and total votes cast reconciles across absentee, early voting and Election Day, and all24 county candidate/method totals independently match the official summary. No geographic allocation.'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,default=ROOT/'dashboard/data/reference.json');p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
 for name,sha in [('grayson-2024-precinct.pdf',PDF_SHA),('grayson-2024-summary.pdf',SUMMARY_SHA)]:
  if hashlib.sha256((P/name).read_bytes()).hexdigest()!=sha:raise ValueError('unreviewed official source edition')
 text=subprocess.check_output(['pdftotext','-layout',str(P/'grayson-2024-precinct.pdf'),'-'],text=True);summary=subprocess.check_output(['pdftotext','-layout',str(P/'grayson-2024-summary.pdf'),'-'],text=True);ref=next(r for r in json.loads(a.reference.read_text())if r['id']=='grayson');result=parse_text(text,summary,ref);a.output_dir.mkdir(parents=True,exist_ok=True);f=io.StringIO(newline='');writer=csv.DictWriter(f,fieldnames=['precinct','harris','trump'],lineterminator='\n');writer.writeheader();writer.writerows({'precinct':p,**v}for p,v in result['presidential'].items());raw=f.getvalue().encode();(a.output_dir/'presidential-2024.csv').write_bytes(raw);sources=json.loads((P/'grayson-source-manifest.json').read_text());metadata={'url':sources[0]['source'],'sha256':hashlib.sha256(raw).hexdigest(),'election_date':result['election_date'],'totals':{k:result['county_totals'][k]for k in ['harris','trump']},'method':result['method'],'sources':[{'url':s['source'],'sha256':s['sha256']}for s in sources]};(a.output_dir/'source.json').write_text(json.dumps(metadata,indent=2)+'\n');(a.output_dir/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items()if k!='presidential'}))
if __name__=='__main__':main()
