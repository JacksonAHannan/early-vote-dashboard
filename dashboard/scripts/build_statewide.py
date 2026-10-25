#!/usr/bin/env python3
"""Refresh or rebuild Texas county mail/in-person aggregates with the Rust collector.

python3 dashboard/scripts/build_statewide.py --through 2026-10-23 [--offline]
The existing entry point delegates to the same validated parser used by the server
and Pages workflow, so it cannot overwrite mail with a separate in-person schema.
"""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', required=True)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[1] / 'Cargo.toml'
    command = ['cargo', 'run', '--manifest-path', str(manifest), '--locked', '--',
               'statewide', '--through', args.through]
    if args.offline:
        command.append('--offline')
    return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
