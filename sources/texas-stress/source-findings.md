# Texas adversarial source audit

October 25 follow-up: [historical coverage recovery](../historical-coverage/findings.md) replaces the specifically conflicting Harris archive with independently reconciled whole SOS reports and repairs three additional source cases. The original quarantine evidence below remains the rationale for withholding zeros from the disputed archive.

Checked 2026-10-24 America/Chicago against the immutable source archive frozen at `/tmp/turnout-texas-audit-20261025`. The repeatable read-only check is `dashboard/tests/texas_source_stress.py`; evidence is `analysis/texas-stress/source-audit-frozen.json`. Run:

```sh
TURNOUT_AUDIT_ROOT=/tmp/turnout-texas-audit-20261025 TURNOUT_AUDIT_TAG=frozen python dashboard/tests/texas_source_stress.py
```

The check passed **71,846 assertions**, reconstructing all **19 official county-summary reports / 4,826 county-report observations** and **3,333 completion controls** from original publisher bytes. It does not import the production parsers. Native county controls use independently reconstructed polling-location sums where available. No voter-detail endpoint was requested and no voter identities were read or retained. Firecrawl reported exhausted credits, so additional live verification used primary county pages directly; no new usable Anderson November aggregate was found on its [current elections page](https://www.andersoncountytx.gov/page/Elections).

## Finding 1: a positive cumulative value can be stale

**High, county cumulative comparisons.** The [current SOS aggregate endpoint](https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile?type=EVR_EARLYVOTING&electionId=53815&electionDate=10/23/2026) supplies zero daily in-person values alongside a positive cumulative value. The existing parser nulls the daily zero but retains the positive cumulative observation as usable for the requested later date. In the frozen data there are **19 such county/date cells**, all exactly equal to the preceding calendar day's cumulative observation, and none has an independent exact-date native control. Examples:

| County | Requested date | Daily IP | Cumulative | Same as |
|---|---|---:|---:|---|
| Panola | October 20 and 21 | 0 | 604 | October 19 |
| Hall | October 21–23 | 0 | 103 | October 20 |
| Starr | October 23 | 0 | 4,315 | October 22 |
| Presidio | October 23 | 0 | 600 | October 22 |
| Dawson | October 23 | 0 | 728 | October 22 |

These are **unconfirmed current-day cumulative reports**, not proof of no further voting. The current daily residence-precinct sources for the sampled counties likewise stop at the previous positive date. Comparing these stale cumulative observations against the later completed 2024 observation creates an unsupported lag. Seventeen affected cells fall in Trump 30+, one in Trump 15–30 (Starr), and one in Harris 30+ (Presidio).

Correction: quarantine both daily and cumulative fields for a current native in-person zero unless an independently corroborated exact-date county control restores the value. Preserve the raw source and prior usable dates. Do not carry an earlier total forward or exclude a county wholesale. Historical mature zero observations retain their existing interpretation.

## Finding 2: a numeric mail zero does not certify a completed zero

**Medium, mail and combined comparisons.** The same current aggregate provides no county-level mail reporting or completion flag. There are **56 observed-date mail-zero cells across 16 counties**, plus **23 zero pre-opening anchors**. Fifty observed cells belong to Trump 30+ counties and six to Trump 15–30. Retained versions of the same Orange report/date contain conflicting mail values (October 19: 0, 1, 135; October 20: 0, 1, 141; October 21: 0, 1, 151; October 22: 0, 1, 170). This establishes source revision/absence ambiguity; it does not establish which number should replace the latest publisher observation.

Correction: treat uncorroborated **current** literal mail zeros as unknown for the applicable observation. Daily mail needs two known adjacent cumulative anchors; a missing anchor must not become a zero day. A positive cumulative mail observation remains independently usable even if its daily delta cannot be established. Do not infer mail from the in-person count or replace the source with a historical maximum.

The county-level membership effect is narrow and varies by date:

| Early-vote day | Mail cumulative unknown counties | Mail daily unknown counties | Stale in-person cumulative cells | Union affected in combined cumulative |
|---|---:|---:|---:|---:|
| 1 | 16 | 23 | 0 | 16 |
| 2 | 12 | 16 | 3 | 15 |
| 3 | 10 | 12 | 2 | 11 |
| 4 | 10 | 10 | 4 | 13 |
| 5 | 8 | 10 | 10 | 14 |

These counts describe source availability, not blanket exclusions from every chart. A separately validated precinct subset can remain available where a full-county observation is unavailable. Both cycles must use the same available county/date/method membership for each comparison.

## Checks that found no new error

- Every cached field agrees with its content-addressed official raw source; SHA-256, election ID, requested date, county identity/universe, and count bounds reconcile. Historical mail, daily in-person, cumulative in-person, and registration county sums equal the official statewide total. Every historical combined row equals in-person plus mail.
- All **75 Harris polling-location rows** sum to its native daily in-person controls. All **47 current / 51 historical Tarrant sites**, **84 current / 71 historical Dallas sites**, Fort Bend site tables versus grand totals, and **59 Bexar sites** reconcile. These reports establish full-county in-person observations; they are not precinct extrapolations.
- Native current/historical Travis and Montgomery controls match their separate ordinary `evData` arrays. Provisional arrays are excluded. Sources are the county-linked [Travis ElectionLink graph](https://updates.electionlink.net/widgets/travistx/2026-11-03/EarlyVotingGraphs.html) and [Montgomery ElectionLink graph](https://updates.electionlink.net/widgets/montgomerytx/2026-11-03/EarlyVotingGraphs.html).
- Source discrepancies are real and should remain corrected by the native county controls: Harris October 23 SOS daily in-person 59,911 versus [native check-ins](https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf) 95,108; Travis SOS 50,267 versus native ordinary early vote 40,453. The audit found no mis-summed native control.
- The archive contains eight historical downward mail transitions, including seven positive pre-opening stocks resetting to zero on Day 1 and Williamson 7,091 to 7,090 later. A nonnegative-delta guard correctly makes the affected daily observations unavailable. A publisher downward revision alone does not justify overwriting its independently reported cumulative value with a maximum or carrying forward an earlier count.
- Native county mail received and SOS by-mail counts still require consistent historical measure reconciliation. The source audit does not promote Harris native received-mail records into the existing precinct dashboard.

## Limits

An administrative report remains subject to later county revisions. Site arithmetic and a closed date do not constitute certification of election results. This audit establishes the retained reported turnout basis and identifies unsupported availability assumptions. It does not independently resolve voter-file deduplication, changed residence precincts, or demographic allocation; those are separate audit scopes. Production corrections and post-change API evidence belong to the parent audit record.

## Follow-up: historical year alone cannot certify absent-precinct zeros

**High, precinct comparisons.** `quality::sources` currently sets every 2024 daily source `complete=true`, regardless of whether its reported counts reconcile with an independently completed same-date in-person control. This flag causes matching to fill every missing reference precinct with zero.

The frozen history contains **2,576 actual historical daily sources across 215 counties**, no derived or cumulative source rows. Every one has a same-date completed county in-person control. **1,861** sums equal the control exactly, **705** are below it, and **10** exceed it. With the existing one-voter reconciliation precision, **1,994** reconcile and **582** do not. Among the latter, 572 are SOS residence-precinct rosters below the official same-date county total by more than one vote; ten are native county-source discrepancies. The differences do not justify allocating missing votes. They also do not justify certifying every absent precinct as zero merely because the year is historical.

Known scope distinctions matter: Montgomery ordinary-E rosters exclude limited/mail and its controls use the same ordinary-E graph; Travis excludes limited/mail and its graph agrees within one voter; Dallas's historical native residence-precinct workbook agrees exactly with its independent location controls for all 12 dates. Harris native and SOS ordinary in-person source totals disagree on some dates. General SOS rosters do not expose separate limited/provisional flags, so the audit cannot classify every small shortfall as missing ordinary votes versus administrative categories or revisions. Preserve explicit observations and withhold unsupported zero inference; do not remove an entire county because one source-day fails this gate.

A **same-date, live-verified contradiction** makes the failure concrete. Harris's native 2024 October 23 roster omits precinct **889**, while the independently fetched official SOS in-person roster contains **two** voters in that precinct. The SOS roster has **111,153** unique in-person voters and agrees exactly with the same-date official county aggregate; native county total is **111,140**. Current 2026 October 21 native precinct 889 has **five** voters. The existing year shortcut therefore lets those five enter against an invented old zero. This does not establish permission to merge the two rosters; it establishes that the native absence is disputed and should not become a certified zero.

The live re-fetch used the official [historical roster endpoint](https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do) with POST `idElection=49664`, `selectedDate=2024-10-23 00:00:00.0`, `idTown=101`, and the ordinary early-vote CSV flags. Its SHA-256, **`8bd66a0934cf52590569a96f07565fedee91c5c2e3f07cdea560fff35feb97d9`**, exactly matches the retained anonymous aggregate's provenance. The native county ZIP SHA is **`b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49`**. Voter CSVs and identifiers remained in memory; only anonymous proof counts and provenance were saved in `analysis/texas-stress/source-harris-live-2024-10-23.json`. Direct urllib received HTTP 403; the project's existing curl-cffi transport succeeded.

There are also **393 candidate currently reported daily group/date cells** whose historical missing IDs would lose zero inference under the corroboration gate, including **313** groups with multiple old precincts. Thirty-nine multiple-old groups have missing IDs that are known positive on other historical dates. For example, Day 1 Harris group old `[250,1108]` → new `[250]` has old 250=56, absent old 1108, and new 250=52; old 1108 has positive records on later dates. This establishes uncertainty, not proof that 1108 voted on Day 1. Candidate counts precede partisan/demographic classification and cumulative-prefix propagation, so they are not a final chart impact count.

Finally, county totals alone are a conservative gate, not a mathematical guarantee of identical precinct distributions: a future historical Day 7 mixed group old `[934,970]` → new `[934]` has native precinct 934 absent versus SOS 934=1 even though both county totals equal 43,535. Do not fuse those records or infer a replacement from the higher precinct value without reconciling their source semantics.

Reproduce the full comparison and candidate groups with:

```sh
TURNOUT_AUDIT_ROOT=/tmp/turnout-texas-audit-20261025 python analysis/texas-stress/source-historical-qualification.py
```

Output: `analysis/texas-stress/source-historical-qualification.json`. Production correction should remove the year-only completeness exception, retain all explicit counts, and apply the existing exact-date control gate symmetrically. Where a known same-date source conflict disputes an absent precinct, that precinct's zero remains unproven even if aggregate totals happen to match.

### Exact zero-inference gate and cumulative availability

A one-voter tolerance can be suitable for displaying an administrative reconciliation difference, but **one unknown voter is enough to make an omitted precinct's zero uncertain**. The proposed correction therefore uses exact same-date count equality for zero inference in both cycles and withholds inferred zeros when the roster has positive `UNASSIGNED` votes. Explicit reported precinct values remain available.

The availability simulation holds current frozen observations fixed and only changes historical zero inference. It resolves each historical cumulative group through all preceding daily observations, including a zero only when that particular day passes the new exact/no-unassigned gate.

| Day | Existing classified cumulative groups | Retained | Existing counties with usable groups | Retained counties |
|---|---:|---:|---:|---:|
| 1 | 6,452 | 6,416 | 214 | 214 |
| 2 | 6,341 | 6,290 | 211 | 211 |
| 3 | 6,298 | 6,244 | 210 | 210 |
| 4 | 6,306 | 6,246 | 210 | 210 |
| 5 | 6,165 | 6,106 | 197 | 197 |

No county loses all its available groups because of this historical gate. On Day 5 the 59 removed partisan-classified groups represent 5,122 old votes and 6,884 current votes; 99.0% of the previously available partisan groups remain. Including groups without a partisan classification, Day 5 availability changes from 7,192 to 6,909; those excluded groups account for 128,630 old votes and 123,231 current votes. Unclassified groups may still matter to demographic analyses, so their separate impact is retained in the evidence rather than hidden.

This is an isolation estimate, not the final dashboard count: changes to current-year zero inference or other matching fixes can change current availability separately. Evidence: `analysis/texas-stress/source-historical-cumulative-impact.json`, generated by the same repeatable qualification audit.

The Harris historical Day 7 distribution conflict contains **no unassigned votes**: all 43,535 native records are assigned numeric precincts, with native 934 absent and 970=5, versus alternative SOS 934=1. Exact aggregate agreement and no-unassigned are conservative checks, not sufficient proof that two publishers use identical residence or date assignments. Reconciling that source conflict requires its own semantics audit; blindly combining the two distributions would undermine the matching contract.

### Implemented source-specific quarantine

The final zero-inference policy in `quality::sources` requires **all three** of the following for either cycle:

1. The dated source's full count exactly equals an independently completed same-date, same-measure county in-person control.
2. It contains no positive `UNASSIGNED` count.
3. It is not the specifically disputed Harris historical ZIP with SHA-256 **`b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49`**.

The third condition addresses the proven Day 7 counterexample even when the first two conditions pass. It is pinned to the immutable bytes whose native and SOS precinct distributions conflict; it does not quarantine all Harris data, all historical county archives, or a future changed ZIP merely because it has the same URL. **Every explicit observation from this archive remains usable.** Only absent-precinct zero inference is withheld. No SOS count is merged into the native roster and no missing vote is allocated.

The independent source stress test now includes nine pinned checks for this case: native ZIP provenance, alternative Day 7 SOS provenance **`5974b86a73ca7613967018faa4e9cb0bf52fadf957b2dd4141ef3eb4631adc15`**, both totals 43,535, no native unassigned votes, native 934 absent, native 970=5, SOS 934=1, and the actual old `[934,970]` → new `[934]` crosswalk group. The frozen source audit passes **71,855 assertions** after adding these checks.

Recomputing the cumulative availability estimate with the **actual three-part policy**, including the hash quarantine, changes none of the first five days' counts in the preceding table: those Harris source-days already fail the exact aggregate gate, and Day 7 is outside the current five-day observation window. All previously participating counties retain usable groups; Day 5 remains 6,106 of 6,165 partisan-classified groups and 6,909 of 7,192 total groups. The exact-policy evidence is `analysis/texas-stress/source-historical-cumulative-impact-final-gate.json`; the previous two-condition estimate is preserved separately.

The parent implementation also rebuilds statewide derived values read-only from retained source caches before live API and static export access. Consequently, a previously published derived file cannot retain the old unsafe zero rules merely because no new network refresh occurred. Raw source values and hashes remain unchanged; cache qualification is a reproducible interpretation of those same bytes.

## Other verified corrections

- A downward revision between complete cumulative rosters no longer becomes an inferred daily zero. Only the affected daily precinct comparison is withheld; legitimate zero precincts, other explicit groups and cumulative values remain available. Seven adversarial Rust fixtures include 1,300 seeded cases.
- Incomplete presidential membership no longer produces partial Harris/Trump sums in the API. Existing browser winner/color guards already handled that case; no displayed miscoloring is claimed.
- County timelines, tables, day controls and exports now use their own completed cutoff when precinct data lags.
- Changed publications invalidate demographic bins, OLS and trend caches even if the source generation timestamp is unchanged. Delayed older requests cannot overwrite the updated view.
- Saved statewide derivatives are recomputed read-only from retained native aggregate caches at API/export time, so an older saved file cannot bypass the corrected qualifications. Source timestamps, hashes and failed-download warnings remain attached.

Final matching verification retains every previously participating county at every observed day. On Day 5 the combined set of qualification changes reduces partisan-classified groups from 6,165 to 6,065; their matched in-person turnout ratio changes from 84.0488% to 83.8565%. These are classified precinct-subset ratios, not full-county mail-plus-in-person turnout. Other classifications use their own available groups. See [matching findings](matching-findings.md) and [reference integrity and source limits](reference-findings.md).
