#!/usr/bin/env python3
"""Extract bounded, explicit residence-precinct zeros from county-linked aggregates.

This never certifies missing precinct rows or adjusts a control for duplicates.
Only a literal precinct Early Vote = 0 cell qualifies, after the precinct table
and separately published daily EV graph reconcile for the same closed cutoff.
"""
from __future__ import annotations
import argparse, gzip, hashlib, html, json, re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
BASE='https://updates.electionlink.net/widgets/travistx/2026-11-03/'
START=date(2026,10,19)

def text(value):
    return html.unescape(re.sub('<[^>]*>', '', value)).strip()

def parse(table_raw:bytes, graph_raw:bytes, through:date, observed_counts=None):
    table=table_raw.decode('utf-8-sig');graph=graph_raw.decode('utf-8-sig')
    if 'NOVEMBER 3, 2026 JOINT GENERAL AND SPECIAL ELECTIONS' not in table:
        raise ValueError('Wrong Travis election')
    timestamp=re.search(r'var lastRefreshed = ([\d.]+);',table)
    if not timestamp:raise ValueError('Precinct aggregate lacks generation timestamp')
    generated=datetime.fromtimestamp(float(timestamp[1])/1000,timezone.utc).astimezone(ZoneInfo('America/Chicago'))
    if generated.year!=2026:raise ValueError('Wrong precinct table generation year')
    pairs=re.findall(r"evData.push\(\['([^']+)',(\d+)\]\)",graph)
    daily={datetime.strptime(d,'%m/%d/%Y').date():int(n) for d,n in pairs}
    if len(daily)!=len(pairs) or not daily or min(daily)!=START:
        raise ValueError('Ambiguous/incomplete independent daily EV series')
    if any(n and (d>through or d>=generated.date()) for d,n in daily.items()):
        raise ValueError('Precinct aggregate includes active or unapproved dates')
    cutoff=max(d for d,n in daily.items() if n>0)
    if set(daily)&{START+timedelta(days=i) for i in range((cutoff-START).days+1)} != {START+timedelta(days=i) for i in range((cutoff-START).days+1)}:
        raise ValueError('Daily EV series has a gap')
    try:grid=table.split('id="gridVerify"',1)[1]
    except IndexError:raise ValueError('Precinct aggregate table missing') from None
    header=[text(v) for v in re.findall(r'<th\b[^>]*>(.*?)</th>',grid.split('<tbody>',1)[0],re.S)]
    if header!=['Precinct','Reg. Voters','Early Vote','Election Day','Provisional Application','Turnout']:
        raise ValueError('Precinct aggregate scope/columns changed')
    body=grid.split('<tbody>',1)[1].split('</tbody>',1)[0];rows={}
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',body,re.S):
        cells=[text(v) for v in re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S)]
        if len(cells)!=6 or not re.fullmatch(r'\d+',cells[0]):raise ValueError('Invalid precinct aggregate row')
        precinct=cells[0].lstrip('0') or '0'
        if precinct in rows:raise ValueError('Duplicate normalized precinct')
        if any(not re.fullmatch(r'\d[\d,]*',v) for v in cells[1:5]):raise ValueError('Invalid aggregate count')
        rows[precinct]=dict(zip(['registered','early_vote','election_day','provisional_application'],[int(v.replace(',','')) for v in cells[1:5]]))
    if not rows or sum(r['early_vote'] for r in rows.values())!=sum(daily.values()):
        raise ValueError('Precinct EV total does not reconcile to independent daily EV series')
    zeros={p:r for p,r in rows.items() if r['early_vote']==0}
    # A later literal cumulative zero must not overwrite any known positive
    # earlier observation, even if a publisher revision changed its total.
    for p in zeros:
        if observed_counts and any(s['date']<=str(cutoff) and s['date']>=str(START) and s['counts'].get(p,0)>0 for s in observed_counts):
            raise ValueError(f'Explicit zero conflicts with an earlier precinct observation: {p}')
    return {'county':'travis','year':2026,'through':str(cutoff),'scope':'in_person','precincts':sorted(zeros),'explicit_rows':zeros,'precinct_count':len(rows),'early_vote_total':sum(daily.values()),'report_generated_at':generated.isoformat(),'source':BASE+'TurnoutByPrecinctTable.html','sha256':hashlib.sha256(table_raw).hexdigest(),'corroborating_source':BASE+'EarlyVotingGraphs.html','corroborating_sha256':hashlib.sha256(graph_raw).hexdigest(),'method':'Literal cumulative Early Vote=0 residence-precinct cells; full precinct Early Vote sum equals county-linked ordinary daily EV graph through a closed cutoff. Mail, Election Day and provisional application columns are not used. Only these explicit zeros imply earlier nonnegative daily/cumulative zeros; missing rows and positive cumulative totals imply nothing about earlier dates.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--table',type=Path,required=True);p.add_argument('--graph',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--through',type=date.fromisoformat,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sources=next(c for c in json.loads(a.snapshot.read_text())['counties'] if c['id']=='travis')['sources']
    result=parse(gzip.decompress(a.table.read_bytes()) if a.table.suffix=='.gz' else a.table.read_bytes(),gzip.decompress(a.graph.read_bytes()) if a.graph.suffix=='.gz' else a.graph.read_bytes(),a.through,sources);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
