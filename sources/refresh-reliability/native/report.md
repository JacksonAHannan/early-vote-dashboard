# Recurring native source refresh reliability — October 28, 2026

Scope: permanent collectors for Collin, Panola, Waller, Washington, San Patricio and the existing Tarrant cumulative anchor. No dated cache patch is used by these changes. Every invocation rediscovers official links and downloads current source bytes; only anonymous counts, source URLs/hashes and diagnostics are retained.

## Confirmed recurring faults and fixes

- **Collin:** October 27's replacement workbook omitted the empty presentation column `Textbox51`, so the collector rejected otherwise valid data. The eight analytical columns remain mandatory and exact; only this observed optional column may be absent. The current workbook contains all nine explicit voting dates. Preserve global identity checks, blank/conflict cell quarantine and Regular-only in-person scope. If the newest advertised edition fails download or validation, independently try an older unambiguous advertised edition and publish its actual date. Never relabel it as the newer date.
- **Panola:** October 27's daily VRH batch was exported October 28 at 07:44:16. The old parser required the administrative export date to equal the voting date. Permit the observed same-day/next-morning export window while every detail record must still have the exact requested voting date, election and EV/EV method. Clamp discovery to the last completed Central-time date.
- **Washington / San Patricio:** alias discovery previously stopped once an older report provided a mapping. Later reports could contradict that mapping but were never checked. Inspect all available completed-date SOS evidence on each refresh, including foreign single-target observations. Conflicts withhold all potentially affected native precinct cells; derived hashes bind the current evidence so changed mappings invalidate dependent outputs.
- **Waller / Washington / San Patricio / Panola:** download and parse independent dated files with at most three concurrent workers, preserving deterministic date order and per-date failure isolation. Alias-source requests use the same bounded concurrency. One failed date does not discard other valid dates.
- **Tarrant:** the current collector already discovers the new publication at its rolling official URL, proves the exact completed cutoff using independent location totals plus ZIP/HTTP metadata, and rechecks all SOS dates through the cutoff. The October 27 invocation succeeded; retain its strict cumulative-only/no-daily-differencing contract.

## Actual official-source verification

The same CLI entry points used by the application were invoked with `--through 2026-10-27`; the precise commands, dates, output totals, source hashes/URLs and observed runtimes are in [verification.json](verification.json).

| Collector | Valid dated outputs | Latest output | Result |
|---|---:|---|---|
| Collin | 9 | October 27 | New workbook accepted; 27,383 surviving ordinary votes across 262 output precinct cells, 5 cells quarantined. |
| Waller | 9 | October 27 | New daily PDF discovered and parsed. |
| Washington | 9 | October 27 | New workbook discovered and parsed; unavailable same-day SOS alias evidence does not discard independently usable native counts. |
| San Patricio | 8 | October 26 | County landing advertises no October 27 in-person roster at verification time. Missing publication is not zero. |
| Panola | 8 | October 26 | Day 9 is advertised and now parses, but fails the source's own batch control: 377 unique valid identities + 6 blank/short rows = 383 observations versus trailer 382. Keep Day 9 withheld and retain prior eight dates. |
| Tarrant | 1 cumulative anchor | October 27 | Rolling ZIP reconciles independent exact-cutoff control; 234,047 surviving output votes including unresolved labels. Unresolved labels remain outside matched native geography. |

All raw roster bytes, identities, names and addresses stay in memory/pipes. No raw voter fixture was created. San Patricio's missing new link and Panola's contradictory control are genuine publication limitations; neither was bypassed.

## Regression verification

`dashboard/tests/test_native_refresh_reliability.py` contains seven synthetic contracts, including observed red→green cases for the removed Collin column, next-morning Panola export, current-day rejection, latest-workbook failure fallback, later evidence invalidating an old alias and foreign-target evidence. A successive-edition test invokes the actual collector repeatedly with new links and replacement bytes, checking date/count/hash changes without code or cache updates.

Passed:

- `python -m unittest discover -s dashboard/tests -p test_native_refresh_reliability.py -v` — 7.
- `python -m unittest discover -s dashboard/tests -p test_county_native.py -v` — 13.
- `python -m unittest discover -s sources/county-methodology/a-g -p test_method_a_g_collin.py -v` — 15.
- `python -m unittest discover -s sources/county-methodology/h-r -p test_method_h_r_panola.py -v` — 9.
- `python -m unittest discover -s dashboard/tests -p test_tarrant_anchor.py -v` — 10.
- `python -m py_compile` for all three changed collectors and the new test; `git diff --check` — successful.

These 54 focused checks verify collector behavior; root integration separately verifies Rust dispatch, hourly orchestration, retained-state merging and publication.
