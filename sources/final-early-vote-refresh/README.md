# October 30 Texas collection review

The completed comparison cutoff during this review is October 29. October 30
is the last day of early in-person voting and remains excluded until it is a
completed reporting day. A later workbook filename is a publication date, not
proof that its latest voting day is complete.

Every prior collection family was inventoried: dated SOS precinct exports,
county ZIP/CSV/XLSX/PDF reports, browser/TLS transports, independent controls,
exact-identity repairs, cumulative anchors and historical recovery editions.
Superseded scripts with frozen calendars and rejected method scopes were not
promoted to production sources. Raw voter records remain memory-only.

Fresh SOS checks covered all 248 admitted precinct counties: 245 October 29
in-person reports were available; Real, Stonewall and Zavala returned empty
responses. The separate official 254-county summary agreed on those three gaps.
All 254 jurisdictions are accounted for; Gregg, Guadalupe, Hill, Taylor, Upton
and Wood retain unresolved precinct relationships rather than guessed joins.
Seven independent control collectors supplied 73 dated current controls through
October 29 with no collector failures.

## Recurring repairs

- Dallas supports its actual 19-column general-election NP CSV, minute timestamps
  and retained Excel sources. Contradictory identities withhold both affected
  date/precinct cells. Blank identities keep the existing full-cell quarantine;
  unaffected dates and cells remain usable.
- Washington accepts its reviewed five- and six-column daily workbook layouts.
  The expanded layout has full residence precinct in D and the exact verified
  early-voting location in E; other layouts remain rejected.
- Waller, Washington and San Patricio retain native daily publications and try
  independently dated SOS reports only for missing dates. The actual San Patricio
  October 28 gap now has 898 state-reported in-person votes across 28 labels.
- Denton can use a later published cumulative workbook for earlier explicit
  Time dates. Current-day rows never enter its observations or identity proofs.
- Collin recognizes both early-voters-through and early-voting-through filenames.
  A later cumulative edition supplies only explicitly dated completed observations;
  global identity contradictions still quarantine affected earlier cells.

Tarrant's exact-cutoff cumulative anchor is not backcast after its archive
advances. Nueces's missing in-person link cannot be replaced by its mail PDF;
its dated SOS fallback remains active. Harris's historical mail source is
unchanged from the rejected baseline, and the old Bexar PDF recovery audit still
fails its changed-inventory guard. Neither unqualified method was admitted.

## Verification

The offline Rust suite passes 167 tests, with live downloads explicitly opt-in.
Full-target Clippy and formatting pass. Actual Dallas and San Patricio production
collectors, and Washington, Denton and Collin Python collectors, returned all 11
completed dates without emitting October 30. New fixture tests reproduce the
format, discovery and cutoff failures; original schema, identity and scope
rejections remain covered. The historical-recovery test fixture now uses a
process-local atomic sequence so parallel tests cannot share a timestamp-named
directory.

Reproduction and data definitions are in `dashboard/README.md`. Detailed local
anonymous inventories, source hashes, red/green evidence and live aggregate
proofs are retained under `analysis/final-early-vote-refresh/` in the original
project. Each published edition is independently checked from its own qualified
source observations; source publication can change between runs.
