# Texas reference-integrity audit

Read-only command: `TURNOUT_AUDIT_ROOT=/tmp/turnout-texas-audit-20261025 python dashboard/tests/texas_reference_stress.py`. Data come from the frozen dashboard; hash-pinned public raw sources are read from the original project because the frozen copy intentionally contains only aggregate dashboard data. This extends the existing `verify_demographics.py`, `verify_primary.py` and `expansion.py` partition/count/control oracles to the complete current scope without introducing geospatial dependencies.

Passed 4,937,459 assertions (mostly individual map coordinate checks):

- All 215 precinct counties partition 9,001 old and 8,950 new precinct IDs without duplicate memberships. Every exact pair belongs to the same common-geography component; nine pairs sit inside larger components and do not meet the application's stricter one-to-one unchanged-cohort test.
- All 8,950 rendered map features have unique stable IDs, exact native reference membership, correct group links and explicit Census FIPS. All 2,353,943 coordinate pairs are finite, within geographic/county bounds, and polygon rings close. This is identifier/coordinate validation, not a fresh polygon-overlay or topology proof.
- All 2,795 precinct-to-county Census count sums match both assigned totals and independent direct county counts exactly; all 215 county populations have 100% assigned population. Complements, bounded race/age counts and integer domains hold. All 3,048 shared direct county count cells also match retained TLC county Census rows.
- All 508 official whole-county Harris/Trump cells match retained native SOS County.json, and their statewide sums reconcile to Federal.json. County names and FIPS match both independent raw sources.
- All 1,159 primary-participation precinct rows reconcile Democratic + Republican ballots to their denominators and six independently verified county controls. Only Dallas, Ellis, Hays, Madison, McLennan and Montgomery have supported data; 209 other precinct counties remain unknown. Ellis explicitly lacks precinct 1023 and stays partial. No county or precinct is fabricated as zero.
- 1,307 source-hash checks pass, including the retained precinct presidential CSVs. The immutable inputs stayed unchanged during the audit.

## Qualified presidential-source limitations

92 precinct presidential reference sums differ from certified whole-county totals. Such precinct sources are partial geographic subsets or TLC retabulations; county classification uses the separate certified county source, never the partial precinct sum. All expanded references disclose that limitation. Original Hays's inline provenance contains only source path/hash; its missing presidential members are already unknown, not allocated. This is a metadata qualification flag, not evidence that the county bucket uses a partial county total.

Two complete TLC precinct references exceed the corresponding native certified county totals. An independent scan of `2024_General_Election_Returns.csv` inside the retained TLC ZIP reproduces the saved precinct references exactly, ruling out an extraction/summing drift in this pipeline:

| County | TLC Harris / Trump | Native SOS Harris / Trump | Difference |
| --- | ---: | ---: | ---: |
| Sherman | 70 / 817 | 48 / 817 | +22 / 0 |
| Tyler | 1,252 / 8,327 | 1,249 / 8,286 | +3 / +41 |

Sherman has complete references for all seven old precincts, Tyler all seventeen. Both official county classifications are Trump 30+, matching their TLC aggregate classification. All 24 TLC precinct classifications are Trump 30+.

A bounded sensitivity check assumes only removal of the known net excess, with no offsetting errors or redistribution. Under that assumption, all seven Sherman precinct bands remain Trump 30+; all 24 precinct winners remain Trump. Tyler precinct 5 (57 Harris, 108 Trump; Harris share 34.545%) is near the 35% share boundary: removing at least three excess Trump votes there could move it into a less Republican band. Certified county totals alone cannot identify whether those excess votes belong to precinct 5, and no certified precinct correction is available in this bounded audit. Other patterns of offsetting errors are not ruled out. Consequently no corrected precinct band or winner is asserted, and no votes were rescaled or redistributed. Exact raw rows, hashes and conditional intervals: `reference-presidential-variance.json`.

The existing reference qualifications already disclose TLC/certified differences. These are retained upstream limitations, not a new parser failure or an observed false whole-county classification.
