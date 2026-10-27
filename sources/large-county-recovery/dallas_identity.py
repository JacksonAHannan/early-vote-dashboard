"""Exact-ID blank-precinct recovery contract; identifiers never leave memory.

A source date must be established by the official endpoint/request, rather than
inferred from row position. This helper neither downloads nor persists rows.
"""
from collections import Counter, defaultdict


def resolve_blank_precincts(blank_native_ids, native_id_counts, sos_pairs, universe):
    """Resolve only globally unique native IDs with one same-date SOS target.

    Call once per official date. native_id_counts covers the entire native
    workbook, including known precincts and every date. sos_pairs contains only
    same-date IN-PERSON (identifier, normalized residence precinct) pairs.
    Returned identity associations are for in-memory transformation only.
    """
    targets = defaultdict(set)
    source_counts = Counter()
    for identifier, precinct in sos_pairs:
        if identifier:
            targets[identifier].add(precinct)
            source_counts[identifier] += 1
    assignments = {}
    diagnostics = Counter()
    for identifier in blank_native_ids:
        if not identifier or native_id_counts[identifier] != 1:
            diagnostics['native_identifier_missing_or_nonunique'] += 1
        elif source_counts[identifier] != 1:
            diagnostics['sos_identifier_missing_or_nonunique'] += 1
        elif len(targets[identifier]) != 1 or not targets[identifier] <= universe:
            diagnostics['sos_precinct_unknown_or_ambiguous'] += 1
        else:
            assignments[identifier] = next(iter(targets[identifier]))
            diagnostics['exact_unique_identity_assigned'] += 1
    return assignments, dict(diagnostics)


def apply_aggregate_counts(original, assignments, expected_blank_rows):
    """Publish anonymous aggregates while conserving every original row.

    Do not use this to reintroduce counts for quarantined precinct/date cells;
    those must continue to be withheld by the native source qualifier.
    """
    if original.get('UNASSIGNED', 0) != expected_blank_rows:
        raise ValueError('native unknown-row aggregate does not match source proof')
    if len(assignments) > expected_blank_rows:
        raise ValueError('recovery exceeds native unknown-row count')
    output = Counter(original)
    output['UNASSIGNED'] -= len(assignments)
    if not output['UNASSIGNED']:
        del output['UNASSIGNED']
    output.update(assignments.values())
    if sum(output.values()) != sum(original.values()):
        raise ValueError('recovery changed native vote total')
    return dict(output)
