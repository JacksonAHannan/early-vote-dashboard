# Tarrant exact-cutoff cumulative anchor — 2026-10-27

The current official [county in-person roster ZIP](https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_voting_in_person_report.zip)
contains 373,100 undated rows through October 26. Its 35 actual fields contain no
voting date. It can support one completed cumulative cutoff, never allocations
backwards into October 19–25 or an inferred same-day October 26 count.

The [independent in-person location control](https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_Voting_Daily_Totals.pdf)
is dated October 26, 2026, 8:58:11 PM Central. Its eight daily columns sum exactly
to 373,100. Every location's daily arithmetic and the sum of all location columns
reconcile to the printed county totals. The raw ZIP row count also equals
373,100. The county's [in-person layout](https://www.tarrantcountytx.gov/content/dam/main/elections/2025/early_voting_in_person_report_layout.pdf)
and the dedicated file/control names establish in-person scope; no mail roster
is used.

The ZIP HTTP `Last-Modified` is October 27, 2026, 02:03:31 GMT, equivalent to
October 26 at 9:03:31 PM Central. Its member timestamp is October 26 at 9:00:20 PM.
These bracket a single post-closing publication after the independent dated
control. The collector requires the requested cutoff, control date and final
control column, archive timestamp and Central-converted HTTP date to agree;
control generation must be after 7 PM; the archive/control/HTTP times must remain
within their bounded 30-minute publication windows. A later undated archive is
never relabeled as an earlier cutoff.

Raw ZIP SHA-256:
`be53f3334234dcca8ea255d7cc74e386931ca14fb709c928f39adc837f5ba798`.
Independent control SHA-256:
`a4dfbfb3267569e4e6a6642d7c2465461d84a9380e3102e254337ec8940b267a`.

## Exact identity proof and local exclusions

The county's six-digit residence labels are never truncated. Unique native
county `ID Number` and `SOS Voter ID` are required. An exact identity join to the
available, dated October 19–25 official SOS in-person reports supplies native
precinct targets for each six-digit label. Every observed SOS target participates
in ambiguity checks, including foreign/off-label targets; no majority mapping or
threshold admits a conflicting label.

A conflicting split label may feed multiple native precincts. The entire native
count is withheld for every such possible target, including counts contributed
by otherwise unambiguous labels. This avoids publishing a partial native total.
The audit-only initial candidate exposed 611 native precincts before this
propagation; a red-capable assertion caught its remaining ambiguous target cells.
The safe collector retains **473** native precincts.

There are 373,053 valid identified rows and 47 rows with both identifiers blank,
across 37 raw county labels. Those blank-only labels have no proven unique native
alias, so their cells remain explicitly unavailable under their full raw labels.
Unresolved identified labels remain positive `UNRESOLVED <six-digit-label>`
aggregates. They never certify omitted native precincts as zero. After local
native quarantine, 75,342 identified rows are withheld; the remaining aggregate
source total is 297,711, including explicit unresolved-label counts. This is not
presented as the county total. No voter identifiers, names, addresses, raw ZIPs,
or voter CSVs are written to disk or emitted in logs.

## Runtime contract

`dashboard/scripts/collect_tarrant_anchor.py` downloads and validates fresh county
sources; runs at most three concurrent alias-source reads; and emits one Daily
aggregate with `cumulative: true`, `complete: false`, and
`allow_daily_difference: false`. The derived SHA-256 hashes the canonical source
hashes, same-date SOS proof sources, cutoff and publication metadata. Original
URLs and hashes are retained in the note and optional aggregate proof manifest.

The Rust Tarrant2026 adapter keeps every available ordinary dated SOS report and
then attempts this optional exact-cutoff anchor. Failure to prove the anchor
preserves those ordinary sources. The Rust parser independently requires the
specific official county URL, exact requested date, cumulative scope, explicit
daily-difference prohibition, valid provenance and positive native counts.
Independent qualification still governs absent-row zeros. The anchor does not
replace October 19–25 sources or create an October 26 daily observation.

## Verification

- `python3 dashboard/tests/test_tarrant_anchor.py`: six tests passed, including
  conflict propagation, foreign-label conflicts, blank-ID native-cell quarantine,
  repeated identities, exact completed cutoff, and independent site arithmetic.
- Focused Rust parser guard test passed, covering absent/true difference flags,
  wrong dates, wrong source URL and noncumulative scope.
- Actual live adapter acceptance passed in **26.62 seconds**. Anonymous output:
  `analysis/large-county-recovery/tarrant-bexar/tarrant-native-live-sources.json`.
- Independent reconciliation verifies all seven ordinary SOS precinct count maps
  and source hashes are unchanged from the frozen public snapshot; cumulative-only
  flags, propagated exclusions and aggregate conservation also pass. Evidence:
  `tarrant-anchor-independent-reconciliation.json` in the same analysis directory.
- All-target Clippy passed with `-D warnings`; Python compilation and Git whitespace
  checks passed. The root release verification covers later integrated changes.
