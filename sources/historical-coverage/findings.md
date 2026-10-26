# Historical Days 1–5 precinct coverage

Audited October 25, 2026. **Both source selection in our system and incomplete publisher observations caused missing precinct comparisons.** The matching engine already retains the largest certain common geography independently for each day. It does not discard an entire county because a few precincts are unavailable. We recovered four source cases without changing that rule or inferring unproved zeros.

## Observed impact

The pinned public and native snapshots had identical Day 1–5 coverage before the fix. The independent audit uses the full **8,950 native precincts / 7,824 common geographic groups / 215 precinct-analysis counties**, including counties with no comparison period. This is not a claim that precinct data exist for all 254 counties; the separate county-total workspace retains all 254.

| Cumulative early-vote day | Paired precincts before | After | Recovered | Still unpaired |
|---|---:|---:|---:|---:|
| 1 | 8,083 | 8,281 | 198 | 669 |
| 2 | 7,892 | 8,140 | 248 | 810 |
| 3 | 7,833 | 8,088 | 255 | 862 |
| 4 | 7,821 | 8,017 | 196 | 933 |
| 5 | 7,658 | 7,875 | 217 | 1,075 |

These are **1,114 recovered precinct-date observations**, not 1,114 distinct precincts. The repaired Rust API exactly matches a separate source-based reconstruction of all 1,075 county/day cases and their paired vote sums. Counts describe availability before partisan or demographic classification. They use native current precinct counts, not the number of geographic groups or regression dots. Each point compares identical reported geography in both cycles; membership may vary by date and by daily versus cumulative measure.

## Recovered system/source-selection cases

| County / cycle | Cause | Correction | Remaining limit |
|---|---|---|---|
| Harris 2024 | The selected county ZIP omits positive precinct observations present in the dated SOS reports. Its omissions had correctly been quarantined, but the available replacement source was not selected. | Re-fetched all 12 official SOS daily in-person reports. Every report exactly matches its independent completed county control, has no unassigned count, and has no voter-ID repetition across dates. Replace each whole dated report only when the retained archive has the reviewed conflicting hash. | All 1,224 native precincts now pair on Days 1–5. This does not manufacture missing presidential or demographic classifications. |
| Ellis 2026 | The collector only requested a rotating cumulative workbook, which cannot reconstruct earlier cutoffs. Dated SOS reports were available. | Add six dated SOS reports alongside the separate native cumulative anchors. The live collector now requests completed daily reports and retains partial successes. | Days 1–3 recover 60 of 61 native precincts. The last remains unknown. Unmapped source IDs stay unallocated. |
| Houston 2024, October 25 | The strict identity validator rejected the whole report because one CSV row was repeated exactly. | After checking all five dates for cross-date repetitions, accept exactly one identical repeated record only for the reviewed file hash, counting it once. | 586 unique in-person records versus independent control 589; still partial. Recovers 21 native precincts on Day 5. |
| Leon 2024, October 22 | The same one-row exact duplication rejected the whole date. | The same narrowly hash-pinned policy, after checking five dates. Differing records or additional duplicates still fail. | 717 unique in-person records versus control 721; still partial. Recovers 14 native precincts on Days 2–5. |

No overlapping rosters were unioned and no highest-count selection was used. Harris uses one complete dated source in place of one conflicting dated source. The source edition fills missing exact-date observations in old retained caches; a later source with an unreviewed hash is preserved. Both API qualification and historical daily analysis apply the edition. The qualification fingerprint includes it, preventing a derived-cache hit based solely on an unchanged raw generation time.

The anonymous edition is [texas-20261025.json](../../dashboard/recovery/texas-20261025.json). Each observation retains its source URL, raw-source SHA-256 and retrieval time. Counts are residence-precinct aggregates only. Voter names and identifiers were handled in memory and were not saved or printed.

The visual audit also found that the All Counties table summed coverage denominators only for counties with usable periods, concealing wholly missing county-days. The displayed denominator now always includes all 8,950 mapped native precincts. Vote sums and membership are unchanged; the coverage label and PNG now disclose the full reference universe.

## Why remaining gaps persist

We rechecked 30 initial official dated reports, then 97 additional deficient or diagnostic reports. Of the second set, **94 produced precisely the same precinct counts already published**. The three strict duplicate failures were the two recovered reports above and the already reviewed conflicting-ID Tarrant Day 1 case. Five-day follow-up downloads for Houston and Leon confirmed no cross-date overlap. This is evidence against a general stale-cache explanation; it does not prove no other county can publish a new correction or alternate source later.

The largest remaining Day 3 gaps are:

| County | Paired / native precincts | Missing due to 2024 only | 2026 only | Both cycles |
|---|---:|---:|---:|---:|
| Dallas | 584 / 791 | 89 | 47 | 71 |
| Tarrant | 546 / 707 | 84 | 22 | 55 |
| Bexar | 651 / 806 | 0 | 155 | 0 |
| El Paso | 203 / 236 | 2 | 16 | 15 |
| Travis | 277 / 308 | 0 | 31 | 0 |

Across all precinct counties on Day 3, **184** native precincts are blocked by historical observations only, **531** by current observations only and **147** by both. A cumulative comparison needs every member's known count through that day. An incomplete earlier daily report therefore can also block later cumulative observations, even where the latest daily report is usable. An independently dated cumulative anchor can restore its own cutoff without inventing intervening daily totals.

Examples of actual source limits:

- Dallas's native workbooks have positive unassigned residence-precinct counts (2024 Days 1–3: 54, 24, 32; 2026: 75, 35, 20). Even an exactly reconciled county total cannot establish omitted precinct zeros when unassigned votes remain. The workbook is a voter roster, not an explicit zero-row precinct table; its parser did not drop zero rows.
- Tarrant's 2026 SOS in-person reports contain 50,142 / 50,722 / 48,632 / 46,124 / 50,639 records on Days 1–5, versus native controls 50,409 / 51,018 / 48,926 / 46,364 / 50,949. Historical reports also fall short of independent controls. A non-voting precinct and an omitted precinct cannot be distinguished from those files alone.
- Bexar's historical reports qualify as complete; the current reports do not. Native independent controls were unavailable for the first four dates in the audited control set; Day 5 contains 45,663 SOS records versus native control 45,703.
- Travis's current Day 1 and Day 4 residence rosters differ from the independent native count by one. That is sufficient to withhold absent-row zero inference, although explicit observations remain usable. Later cumulative intersections retain that earlier uncertainty.
- Fifteen counties have no defensible cumulative precinct pair on Day 5 in the checked reports: Callahan, Dawson, Floyd, Hall, King, Lipscomb, Loving, Panola, Presidio, San Patricio, Starr, Swisher, Waller, Washington and Winkler. Earlier usable dates remain present. A county-level total is not evidence of the missing residence-precinct distribution.

These are reporting/assignment limits in the checked sources, not proof that every absent precinct voted zero. The audit cannot attribute each discrepancy to ordinary versus limited/provisional categories or publisher corrections. It withholds zero inference rather than allocating the difference. Missing presidential returns, tied elections, mixed old-member partisan bands, missing Census counts and unsupported primary participation are separate classification limits; they do not erase the underlying available turnout pair.

## Sources and reproduction

Official primary sources used include the [historical SOS download service](https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do), [current SOS county/date download service](https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat?type=EVR_EARLYVOTING&electionId=53815&electionDate=10/19/2026&county=ELLIS&countyId=70&format=csv), [Harris county archive](https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_1124.zip), [Ellis county roster](https://www.elliscountytx.gov/DocumentCenter/View/24311/110326-Election-Early-Voting-InPerson-Roster?bidId=), [Bexar native counts](https://earlyvotecounts.bexar.org/) and [Travis native graph](https://updates.electionlink.net/widgets/travistx/2026-11-03/EarlyVotingGraphs.html). Historical SOS requests use election 49664, exact voting date and county ID; current requests use election 53815. All source parameters are preserved in the edition.

Reviewed conflicting Harris archive SHA-256: `b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49`. Houston duplicate-policy hash: `1b662d55c21f7ee931ad8f089afeac273775d94657695231ca46db52fa78cb03`. Leon: `7cdf0400b0924e80d753655102f5b52d2d9bf868cd5a66e5d60e3a64b9662bf1`.

Run the independent [coverage auditor](../../dashboard/scripts/audit_precinct_coverage.py) with a saved `/api/data` response. It reconstructs cumulative availability from exact-date source observations without importing production matching code, then asserts that every published group/precinct count and paired vote sum agrees. `--require-complete` deliberately remains red where real gaps remain. [Rust recovery tests](../../dashboard/tests/historical_recovery.rs) cover source substitution, later-revision preservation, partial controls, separate cumulative anchors, unrelated counties, curated provenance and the opt-in real collectors. [API/browser checks](../../dashboard/tests/historical_coverage.py) verify per-day cumulative primary/demographic timelines and exported coverage alongside the existing independent matching, joint-matrix and geography suites.

The baseline and before/after anonymous snapshots, source recheck diagnostics and browser proof are retained locally in `analysis/historical-coverage/`. Existing [adversarial source findings](../texas-stress/source-findings.md) document the independent controls and earlier mail/zero safeguards. Precinct comparisons remain **early in-person**; county totals retain the separate mail + in-person comparisons.
