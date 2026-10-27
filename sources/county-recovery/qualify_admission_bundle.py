#!/usr/bin/env python3
"""Select staged counties using explicit paired source observations only.

No complete-report zero inference, label aliases, spatial allocation or product
imports. At least one cumulative common group with positive 2024 baseline must
have explicit native-ID observations on every required date in both years.
Outputs are additive county objects; the parent merges into its current base.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def known(sources, year, day, cumulative):
    start = dt.date(year, 10, 21 if year == 2024 else 19)
    when = str(start + dt.timedelta(days=day - 1))
    anchors = [d for d in sources if d['date'] == when and d.get('cumulative', False)]
    if cumulative and anchors:
        return max(anchors, key=lambda d: d['retrieved_at'])['counts']
    dates = [str(start + dt.timedelta(days=i)) for i in range(day)] if cumulative else [when]
    observations = []
    for stamp in dates:
        candidates = [d for d in sources if d['date'] == stamp and not d.get('cumulative', False)]
        if not candidates:
            return {}
        observations.append(max(candidates, key=lambda d: d['retrieved_at'])['counts'])
    ids = set.intersection(*(set(d) for d in observations))
    return {id: sum(d[id] for d in observations) for id in ids}


def run(args):
    bundle = args.bundle.resolve()
    source = args.source_root.resolve()
    status = read(bundle / 'status.json')
    assert status['passed'], 'Prerequisite build must pass before qualification'
    project = bundle / 'project'
    candidates = status['selected_counties']
    refs = [r for r in read(project / 'dashboard/data/reference.json') if r['id'] in candidates]
    assert {r['id'] for r in refs} == set(candidates)
    report = {'method': __doc__, 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'admitted': [], 'excluded': [], 'counties': {}, 'source_hashes': {}}
    for county in refs:
        slug = county['id']
        sources = []
        for year in [2024, 2026]:
            path = source / f'dashboard/data/cache/{slug}/{year}-series.json'
            raw = path.read_bytes()
            observations = json.loads(raw)
            assert all(d['county'] == slug and d['date'].startswith(str(year)) for d in observations)
            assert all(isinstance(n, int) and n >= 0 for d in observations for n in d['counts'].values())
            sources.extend(observations)
            report['source_hashes'][str(path.relative_to(source))] = hashlib.sha256(raw).hexdigest()
        rows = []
        for day in range(1, args.days + 1):
            row = {'day': day}
            for measure in ['daily', 'cumulative']:
                old = known(sources, 2024, day, measure == 'cumulative')
                new = known(sources, 2026, day, measure == 'cumulative')
                paired = [g for g in county['groups']
                          if all(p in old for p in g['old']) and all(p in new for p in g['new'])
                          and sum(old[p] for p in g['old']) > 0]
                row[measure] = {'groups': len(paired), 'precincts_2026': sum(len(g['new']) for g in paired),
                                'votes_2024': sum(sum(old[p] for p in g['old']) for g in paired),
                                'votes_2026': sum(sum(new[p] for p in g['new']) for g in paired)}
            rows.append(row)
        eligible = any(row['cumulative']['groups'] > 0 for row in rows)
        report['admitted' if eligible else 'excluded'].append(slug)
        report['counties'][slug] = {'eligible': eligible, 'days': rows,
                                    'reason': 'Explicit paired cumulative common groups exist.' if eligible else
                                    'No common group has explicit native-ID source observations in both years; unknown labels are not zeros.'}
        print(slug, 'ADMIT' if eligible else 'EXCLUDE',
              [(r['day'], r['cumulative']['groups'], r['cumulative']['precincts_2026']) for r in rows], flush=True)
    selected = set(report['admitted'])
    output = bundle / 'qualified'
    write(output / 'reference-additions.json', [r for r in refs if r['id'] in selected])
    for name, path in [('demographics', 'dashboard/data/demographics.json'),
                       ('primary', 'dashboard/data/primary.json'), ('places', 'dashboard/places/texas.json')]:
        data = read(project / path)
        data['counties'] = {slug: data['counties'][slug] for slug in report['admitted']}
        write(output / (name + '-additions.json'), data)
    report['count'] = len(selected)
    report['new_native_precincts'] = sum(len({p for g in r['groups'] for p in g['new']})
                                        for r in refs if r['id'] in selected)
    report['new_common_groups'] = sum(len(r['groups']) for r in refs if r['id'] in selected)
    report['passed'] = True
    write(output / 'qualification.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'analysis/county-recovery/admission-additional')
    parser.add_argument('--source-root', type=Path, default=ROOT.parent / 'texas-early-vote-2026-11-03')
    parser.add_argument('--days', type=int, default=7)
    run(parser.parse_args())
