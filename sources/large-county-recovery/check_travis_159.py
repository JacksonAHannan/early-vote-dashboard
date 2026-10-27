#!/usr/bin/env python3
"""Exact-symptom signal: a proved literal zero must preserve its comparison group."""
import argparse, importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('coverage_oracle',ROOT/'dashboard/scripts/audit_precinct_coverage.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
data=json.loads(a.snapshot.read_text());c=next(c for c in data['counties'] if c['id']=='travis');group=next(g for g in c['reference_groups'] if '159' in g['new']);oldids={p for g in c['reference_groups'] for p in g['old']};newids={p for g in c['reference_groups'] for p in g['new']};old,_=m.reconstruct(c['sources'],2024,1,oldids);new,_=m.reconstruct(c['sources'],2026,1,newids)
result={'county':'travis','day':1,'group_precincts_2026':group['new'],'group_precincts_2024':group['old'],'missing_2026':[p for p in group['new'] if p not in new],'missing_2024':[p for p in group['old'] if p not in old],'proof_expected_159':0};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
assert '159' in new and new['159']==0,'Official explicit cumulative zero159 is absent in Day1 resolved observations'
assert not result['missing_2026'] and not result['missing_2024'],'Known-zero precinct still discards its otherwise available geographic group'
