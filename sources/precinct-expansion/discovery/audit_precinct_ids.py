"""Reconcile anonymous source counts against native TLC precinct identifiers.

Native county identity is official FIPS (TLC CNTY), not the SOS county ID or
TLC cntykey. Native PREC padding follows build_precinct_expansion.normalize;
VTD identifiers and observed source labels are never rewritten by this audit.
"""
import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXISTING = set('travis dallas montgomery bell hays ellis mclennan hockley madison tarrant'.split())


def norm(value):
    """Normalize native PREC fields only, matching the geography builder."""
    return str(value).strip().upper().lstrip('0') or '0'


def official_fips(targets, county_reference):
    result = {}
    for county in targets:
        value = county_reference[county]['fips']
        if not isinstance(value, str) or len(value) != 5 or not value.isdigit() or not value.startswith('48'):
            raise ValueError(f'Invalid official Texas county FIPS: {county}')
        result[county] = int(value[2:])
    if len(set(result.values())) != len(result):
        raise ValueError('Multiple county identities share one official FIPS')
    return result


def native_universe(records, wanted_fips):
    """Reject duplicate normalized IDs; never merge colliding shape records."""
    result = {fips: set() for fips in wanted_fips}
    for record in records:
        if 'CNTY' not in record:
            raise ValueError('Native geometry record requires official CNTY; cntykey is not a substitute')
        county_fips = int(record['CNTY'])
        if county_fips not in result:
            continue
        precinct = norm(record['PREC'])
        if precinct in result[county_fips]:
            raise ValueError(f'Duplicate normalized native precinct {precinct} in FIPS {county_fips:03d}')
        result[county_fips].add(precinct)
    missing = [fips for fips, precincts in result.items() if not precincts]
    if missing:
        raise ValueError(f'Missing native county geometry: {missing}')
    return result


def load_universes(root, wanted_fips):
    import shapefile
    result = {}
    for year, vintage in [(2024, '24g'), (2026, '26p')]:
        path = root / f'sources/boundaries/{vintage}/Precincts{vintage.upper()}.dbf'
        with shapefile.Reader(str(path)) as reader:
            result[year] = native_universe((record.as_dict() for record in reader.iterRecords()), wanted_fips)
    return result


def audit_counts(days, native):
    # Source labels remain exact; unknown positive categories stay unlocated.
    observed = collections.Counter()
    for day in days:
        observed.update(day['counts'])
    missing = {p: n for p, n in sorted(observed.items()) if p not in native}
    total = sum(observed.values())
    unmapped = sum(missing.values())
    return dict(days=len(days), native_precincts=len(native), observed_precincts=len(observed),
                observed_votes=total, unmapped_precincts=missing, unmapped_votes=unmapped,
                mapped_share=(total - unmapped) / total if total else None)


def main(argv=None, root=None):
    root = ROOT if root is None else Path(root)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--output', type=Path, help='Diagnostic destination; source caches are never modified')
    args = parser.parse_args(argv)
    state = json.loads((root / 'dashboard/data/statewide.json').read_text())
    counties = {c['id']: c for c in state['counties']}
    if args.all:
        targets = sorted(p.name for p in (root / 'dashboard/data/cache').iterdir()
                         if p.is_dir() and p.name in counties and p.name not in EXISTING)
    else:
        probe = json.loads((root / 'sources/precinct-expansion/discovery/probe-summary.json').read_text())
        targets = [c['county'] for c in probe if c['date'] == '2024-10-21']
    if len(targets) != len(set(targets)):
        raise ValueError('Repeated county in requested audit universe')
    reference = json.loads((root / 'dashboard/data/county-reference.json').read_text())['counties']
    fips = official_fips(targets, reference)
    universes = load_universes(root, set(fips.values()))
    output = []
    for county in targets:
        c = counties[county]
        row = dict(county=county, name=c['name'], state_id=c['state_id'],
                   fips=reference[county]['fips'], native_county_field='CNTY', years={})
        for year in [2024, 2026]:
            source = root / f'dashboard/data/cache/{county}/{year}-series.json'
            if source.exists():
                row['years'][str(year)] = audit_counts(json.loads(source.read_text()), universes[year][fips[county]])
        output.append(row)
    destination = args.output or root / ('sources/precinct-expansion/discovery/inventory-precinct-id-audit.json'
                                         if args.all else 'sources/precinct-expansion/discovery/precinct-id-audit.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2) + '\n')
    for row in output:
        print(row['county'], [(year, values['days'],
                               f"{100 * values['mapped_share']:.2f}%" if values['mapped_share'] is not None else '—',
                               values['unmapped_precincts']) for year, values in row['years'].items()])
    return output


if __name__ == '__main__':
    main()
