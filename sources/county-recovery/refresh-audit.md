# Dallas and Montgomery refresh audit

Audit date: 2026-10-26. Scope: read-only inspection of the public repository,
the original working project, anonymous aggregate caches, and existing local
production logs. No collector, source cache, application, or service was changed.
This document is the only audit-owned file.

## Confirmed immediate failure

The automatic refresh runs, but both 2026 county adapters reject an ordinary
roster row with no identifier and discard that attempt's entire fresh series.
The existing five-day aggregates are retained. Dallas independently also fails
to refresh its completion controls because the selected aggregate URL does not
match the required dated filename suffix.

Evidence from `/tmp/turnout-matrix-production.log`:

- Line 2: completion audit at `2026-10-26T22:48:36.509195+00:00`, requested
  through `2026-10-25`; Dallas error `ValueError: Dallas dated report cutoff
  absent`. Dallas current controls end October 23; Montgomery controls in this
  original-project refresh cover October 25.
- Lines 7–8: `Montgomery: 2026: blank identifier in ordinary county roster;
  earlier reported dates retained`, followed by 17 retained observations.
- Lines 25–26: the same Dallas error and 17 retained observations.
- `/tmp/turnout-brand-production.log` records the same failures on successive
  completion-audit rounds at 17:24, 18:26, 19:28, 20:29, and 21:31 UTC.

Observed process: PID 887654 was launched October 26 at 17:48:34 Central as the
original project's `dashboard/target/release/texas-turnout serve --port 8741`.
The source loop refreshes immediately, then sleeps 3,600 seconds by default
after each completed refresh (`dashboard/src/main.rs:850`). It is not aligned
to clock-hour boundaries. Existing logs establish that retrying the unchanged
parser has repeatedly reproduced this failure.

The cache symptom was independently reproduced with a read-only Python assertion
over both projects' `dashboard/data/cache/{dallas,montgomery}/{year}-series.json`.
For each county, in each project:

| Year | Distinct daily reports | Earliest | Latest |
| --- | ---: | --- | --- |
| 2024 | 12 | 2024-10-21 | 2024-11-01 |
| 2026 | 5 | 2026-10-19 | 2026-10-23 |

The command failed explicitly with `Missing current Day 6/7` for all four
project/county pairs; runtime was 0.011 seconds. Dallas and Montgomery
`data/history-cache/.../2024-series.json` in the public project also contain
all 12 historical dates. Historical calendar truncation is therefore not the
immediate cause of these missing current dates.

At inspection, the public project's independently retained Montgomery controls
covered October 24, whereas the original production log's fresh controls covered
October 25. These are different retained states; do not assume the two project
directories share newly refreshed data.

## Relevant code path

1. `dashboard/src/county.rs:89`: shared `insert` rejects an empty identity.
   It separately converts an empty residence precinct to `UNASSIGNED`. An
   absent voter identity and an absent precinct have different behavior.
2. Montgomery (`county.rs:247`) downloads each requested exact-date ZIP,
   filters `VoteType == E`, checks `DateVoted`, and passes `VUID` to `insert`
   (`county.rs:292`). Any blank VUID in an accepted row aborts the whole
   collection before it returns the assembled `Vec<Daily>`.
3. Dallas (`county.rs:336`) downloads the linked cumulative in-person workbook,
   filters to requested `DATE VOTED` dates, then uses `SOS VOTERID` with
   `IDNUMBER` fallback (`county.rs:363`). A row with neither usable field
   aborts collection. The discovery header check requires date and precinct,
   but does not require either identity column (`county.rs:348`).
4. `dashboard/src/main.rs:144` unconditionally refreshes the current year.
   A known county adapter is selected before the state-export branch
   (`main.rs:149`). There is no state fallback after an adapter error.
5. `main.rs:169` starts with cached values and merges only an `Ok(fresh)`.
   On `Err`, all old observations remain and no partial fresh result is
   available. Montgomery's earlier successful files from the same attempt are
   therefore also lost. The retained cache is rewritten when nonempty
   (`main.rs:178`), so a new modification time alone does not establish new
   source coverage. Previous snapshot sources are merged afterward
   (`main.rs:186`).
6. `quality::qualify` is then applied and a new snapshot timestamp is published
   (`main.rs:231`). Qualification replaces each county error with the generic
   matched-cutoff error when no latest period exists (`quality.rs:207`). The
   precise acquisition error remains in server logs rather than that county
   error field. `/api/status` exposes only updating/generation state
   (`main.rs:611`), which also does not establish source freshness.

The inspected `main.rs`, `county.rs`, `quality.rs`, and
`scripts/audit_completeness.py` were byte-identical between projects. This audit
did not re-download either voter source, so it does **not** establish whether the
rejected entries are genuine anonymous records, extra report rows, renamed
identity columns, or another publisher change. Their number, affected dates,
and precinct distribution require the separate in-memory source inspection.
Do not fix this by silently dropping rows or generating replacement identities.

## Dallas independent controls and matching

`dashboard/scripts/audit_completeness.py:248` discovers the county location
workbook, checks its election, all 12 calendar columns, daily/site arithmetic,
and cumulative total. At line 281 it additionally requires a URL suffix
`_MM.DD.YY.xlsx` to establish the closed reporting cutoff. The logged
`Dallas dated report cutoff absent` comes from that last check. The audit
retains prior controls for their own exact dates and records collector errors
without failing the whole audit (`audit_completeness.py:320`, `:342`). Thus a
successful audit process can retain old Dallas controls.

These controls are an independent issue, not an explanation for physically
absent Day 6/7 source observations. `quality.rs:154` retains explicit precinct
observations even without a matching control. `quality.rs:172` sets
`Daily.complete` only for an exact county-total reconciliation, no unassigned
votes, and no disallowed historical source hash. Completeness governs inference
of omitted precinct zeros. It is not whole-county admission.

`matching.rs:58` accepts explicit exact-date counts; its cumulative path needs
the actual requested daily observation plus the preceding cumulative chain
(`matching.rs:67`). Pairing needs both years (`matching.rs:126`). Consequently
full 2024 history cannot fill an absent 2026 Day 6/7 observation, and restoring
current controls alone cannot supply precinct counts. Earlier incomplete
observations may still reduce later cumulative coverage after fresh dates are
recovered; retain those uncertainty rules.

## Historical collector and publication packaging

`dashboard/src/trends.rs:720` calls
`sources/daily-tracking/collect_dallas_history.py` only when Dallas's merged
historical sources lack a full 12-day calendar (`trends.rs:794`). That helper is
absent from the public repository but present in the original project.

The original helper also depends on its sibling `verify_history.py`, the saved
`sources/refresh-2026-10-23/county-a/dallas-2024-location-totals.xlsx`, and five
accepted historical Dallas days in `dashboard/data/latest.json` (helper lines
13, 97–103). These sibling/validation inputs are also absent from the public
repository. It selects county `IDNUMBER` first, unlike the ordinary Rust
adapter, because the prior historical audit found one reused SOS identifier.
Those dependencies make this a separate reconstruction gap; copying only the
helper would not repair a genuine cold start.

The state packager explicitly includes `dashboard/data/cache/` and
`dashboard/data/history-cache/` JSON (`scripts/package_pages_state.py:30`).
The current workflow restores that retained archive from Actions cache or the
`data-state`/`bootstrap` release before refreshing (`.github/workflows/pages.yml:61`).
Restoring all 12 accepted Dallas historical observations bypasses the missing
helper. The helper and historical XLSX are outside the aggregate archive
allowlist. The missing collector is not the immediate cause when the complete
baseline is already present; it matters if those baseline observations need
independent reconstruction. The existing release restore is a real retained
state path, but not a source-only cold reconstruction path.

The Pages workflow intentionally skips refresh on pushes and can publish
validated retained aggregates. Scheduled/manual refresh has `continue-on-error`
and a 35-minute process deadline (`pages.yml:100`). Even without that option,
per-county errors are retained and `refresh_precincts` can return `Ok(())`
(`main.rs:278`), so a green workflow or fresh publication timestamp does not
guarantee Dallas/Montgomery new-date coverage. This audit did not inspect remote
Actions executions and does not attribute an observed remote run to a timeout.

## Narrow repair and verification recommendations

1. Establish the precise source change with in-memory diagnostics: source URL
   and hash, headers, accepted row counts by exact date, blank identity counts
   by date/type, deduplication collisions, unassigned precinct totals, and
   independent controls. Persist only aggregate diagnostics/provenance. Use
   the smallest defensible row/identity policy supported by that evidence,
   retaining strict rejection for unexplained rows and identity conflicts.
2. Fix Dallas's closed-cutoff extraction for the actual official report format.
   Require a verifiable closed date and keep future placeholder zero columns
   excluded. An HTTP retrieval time or latest nonzero cell alone does not prove
   that all requested days are complete.
3. Keep the county source consistent across dates. Add state fallback only
   after an explicit source-equivalence review; prior Dallas historical work
   found equal county totals could still mask different precinct counts.
4. If preserving partial adapter progress is included, return validated dated
   results and their failure separately. For Montgomery preserve cross-file
   identity checks and earliest-date assignment. Do not union overlapping
   native/state sources or replace later unreviewed revisions automatically.
5. Repair Dallas historical reconstruction independently: move a self-contained
   collector and its verifiable controls under a maintained runtime location,
   or explicitly enforce/verify the retained full-baseline prerequisite. Preserve
   the reviewed county-ID identity rule and validation against accepted baseline
   aggregates. Test with empty historical caches in a temporary project tree.
6. Preserve precise acquisition failures in refresh diagnostics alongside
   matching availability so publication success is distinguishable from source
   freshness. Avoid changing publication of valid retained observations.

Meaningful regression tests should exercise parser/call-site behavior, not only
the shared identity map:

- Synthetic Dallas and Montgomery formats reproducing the observed problematic
  row layout; expected accepted aggregate totals, unknown-precinct retention,
  duplicate detection, genuine malformed-row rejection, and date/type filtering.
- Montgomery a valid earlier date followed by a failing file, checking the
  intended retained/fresh behavior and cross-date identity invariant.
- Dallas controls for both old dated and newly observed official filenames,
  absent/contradictory cutoff evidence, future zeros, and exact-date retention
  after a control download fails.
- Refresh with a five-day retained cache and valid seven-day sources: assert
  actual current-date observations and Day 6/7 matched coverage, not just new
  `generated_at` or successful exit status. Failed sources must retain prior
  aggregates without fabricating observations.
- An isolated retained-archive restore with all 12 Dallas historical dates;
  separately a historical rebuild without prior source/cache state to catch
  unavailable helper/validation dependencies.

Existing `county.rs:523` tests deduplication and `quality.rs:355` tests retention
without controls, but neither checks the Dallas/Montgomery format failure.
`tests/live_refresh.py:20` and `scripts/verify_refresh.py:60` are pinned to the
older October 22 four-day scenario; they do not by themselves verify the current
seven-day refresh. No implementation/test changes or Rust test runs were made
as part of this bounded read-only audit.
