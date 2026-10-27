"""Scoped candidate for exact-identity Tarrant cumulative cell resolution."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('existing_tarrant_anchor',ROOT/'dashboard/scripts/collect_tarrant_anchor.py')
EXISTING=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(EXISTING)

# Keep the reproducible research CLI on the single production transformation.
aggregate=EXISTING.aggregate
collect=EXISTING.collect
import json
from datetime import date


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--through',type=date.fromisoformat,required=True)
    p.add_argument('--evidence',type=Path,help='Optional anonymous provenance and alias diagnostics')
    p.add_argument('--output',type=Path,help='Optional combined observation/evidence audit artifact')
    args=p.parse_args();daily,evidence=collect(args.through)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(evidence,indent=2)+'\n')
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(observation=daily,evidence=evidence),indent=2)+'\n')
    # Production transport expects only aggregate Daily JSON on stdout.
    print(json.dumps([daily],sort_keys=True))

if __name__=='__main__':main()
