#!/usr/bin/env python3
"""Download Collin official early-voter workbook only in memory; emit aggregates."""
import argparse, collections, hashlib, json, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dashboard/scripts'))
from audit_completeness import workbook

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    page='https://www.collincountytx.gov/Elections/rosters';html=urlopen(Request(page,headers={'User-Agent':'Mozilla/5.0'}),timeout=60).read().decode()
    links=[x.replace('&amp;','&') for x in re.findall(r'href=["\']([^"\']+)',html) if re.search(r'/early-voters-through-october-26-2026\.xlsx',x)]
    assert len(set(links))==1
    url='https://www.collincountytx.gov'+links[0];raw=urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=120).read();rows=workbook(raw)
    expected={'A':'VoterName','B':'VoterAddress','C':'CertificateNumber','D':'Precinct','E':'VoteDate','F':'VotedBallotStyle1','G':'VoteType','H':'VotedPhase','I':'Textbox51'}
    assert rows[0]==expected,'County workbook schema changed'
    kinds=collections.Counter();phases=collections.Counter();date_shapes=collections.Counter();blanks=collections.Counter();identities={};duplicates=conflicts=0;counts=collections.defaultdict(collections.Counter);quarantine=set();regular_rows=collections.Counter()
    for row in rows[1:]:
        kinds[row.get('G','')]+=1;phases[row.get('H','')]+=1
        if row.get('G')!='Regular':continue
        assert row.get('H')=='Early Voting','Unexpected voting method in ordinary source'
        ds=row.get('E','').strip();when=None
        for fmt in ['%m/%d/%Y','%m/%d/%Y %I:%M:%S %p','%Y-%m-%d','%m/%d/%Y %H:%M:%S']:
            try:when=datetime.strptime(ds,fmt).date();break
            except ValueError:pass
        if when is None and re.fullmatch(r'\d{5}(?:\.\d+)?',ds):when=date(1899,12,30)+timedelta(days=int(float(ds)))
        if when is None:date_shapes['empty' if not ds else 'unrecognized date format']+=1;continue
        precinct=row.get('D','').strip().lstrip('0') or 'UNASSIGNED';id=row.get('C','').strip();regular_rows[str(when)]+=1
        if not id:blanks[f'{when}:{precinct}']+=1;quarantine.add((str(when),precinct));continue
        cell=(str(when),precinct,row.get('G',''),row.get('H',''))
        if id in identities:
            duplicates+=1
            if identities[id]!=cell:
                conflicts+=1;quarantine.add((identities[id][0],identities[id][1]));quarantine.add((cell[0],cell[1]))
            continue
        identities[id]=cell;counts[str(when)][precinct]+=1
    unfiltered_identified_totals={d:sum(c.values()) for d,c in counts.items()}
    for d,pct in quarantine:counts[d].pop(pct,None)
    result={'scope':'in_person','vote_type':'Regular','source':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'data_rows':len(rows)-1,'vote_types':dict(kinds),'vote_phases':dict(phases),'unparseable_date_values':dict(date_shapes),'blank_identity_cells':dict(blanks),'repeated_identities':duplicates,'conflicting_identities':conflicts,'days':[{'date':d,'counts':dict(sorted(c.items())),'total':sum(c.values()),'regular_source_rows':regular_rows[d],'identified_before_quarantine':unfiltered_identified_totals[d],'unavailable_precincts':sorted(p for day,p in quarantine if day==d)} for d,c in sorted(counts.items())]}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v if k!='days' else [{'date':d['date'],'total':d['total'],'precincts':len(d['counts']),'regular_source_rows':d['regular_source_rows'],'unavailable_precincts':d['unavailable_precincts']} for d in v] for k,v in result.items()}))
if __name__=='__main__':main()
