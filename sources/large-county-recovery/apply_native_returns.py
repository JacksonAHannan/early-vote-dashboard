#!/usr/bin/env python3
"""Merge reviewed native presidential canvasses; preserve geography and known votes."""
import argparse,copy,csv,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def apply(reference,controls,directory):
    output=copy.deepcopy(reference);changed=[]
    for county in output:
        folder=directory/county['id'];path=folder/'presidential-2024.csv'
        if not path.exists():continue
        source=json.loads((folder/'source.json').read_text());raw=path.read_bytes()
        assert source['sha256']==hashlib.sha256(raw).hexdigest(),county['id']
        rows=list(csv.DictReader(raw.decode().splitlines()));ids={p for g in county['groups'] for p in g['old']}
        votes={r['precinct']:{k:int(r[k]) for k in ['harris','trump']} for r in rows}
        assert len(rows)==len(votes) and set(votes)==ids,(county['id'],'native partition')
        assert all(n>=0 for v in votes.values() for n in v.values())
        for key in ['harris','trump']:
            assert sum(v[key] for v in votes.values())==source['totals'][key]==controls[county['id']][key],(county['id'],key,'county conservation')
        assert all(votes[p]==value for p,value in county['presidential'].items()),(county['id'],'existing values conflict')
        changed.append({'county':county['id'],'before':len(county['presidential']),'after':len(votes)})
        county['presidential']=votes
        county['references']['presidential']={'path':str(path.relative_to(ROOT)),'sha256':source['sha256'],'qualification':source['method'],'source':source}
    return output,changed
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--returns',type=Path,default=ROOT/'dashboard/returns');p.add_argument('--output',type=Path);a=p.parse_args()
    source=a.root/'dashboard/data/reference.json';reference=json.loads(source.read_text());controls=json.loads((a.root/'dashboard/data/county-reference.json').read_text())['counties']
    result,changed=apply(reference,controls,a.returns);(a.output or source).write_text(json.dumps(result,separators=(',',':'))+'\n');print(json.dumps(changed))
