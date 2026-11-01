# Final stale-control investigation and supported recovery

The bounded official-site sweep found **no independently reconciled final ordinary in-person county aggregate** that safely replaces the stale SOS final rows for the 18 named counties or resolves Waller/Washington's reverse residuals. It did find and verify a supported **Dimmit October 30 native recovery**, and prove that Swisher publishes positive final-day in-person activity without the precinct field needed for recovery.

The [official October 30 SOS county summary](https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile?type=EVR_EARLYVOTING&electionId=53815&electionDate=10%2F30%2F2026) still repeats October 29 cumulative totals for these 18 counties, whose prior cumulative values sum to **25,940**. That statewide source is not promoted into a completed final denominator. Neither a zero daily field, an empty HTTP200 body nor a mail-only file establishes ordinary in-person zero.

## Dimmit: accepted final ordinary native observations

The [official election page](https://dimmitcounty.org/government/departments/elections/index.php) advertises all twelve October 19–30 VRH files. Its HTML **base URL is the county root**, so the final link resolves to [VoterHistory 10302026.txt](https://dimmitcounty.org/VoterHistory%2010302026.txt?t=202610302107480). Resolving links against the page's directory instead produces a misleading 404. The correct final file SHA-256 is `67b9db39988291ca687a19b904f1c5a0c51e8087791651e1a247502271586585`.

All **228** final detail records have the reviewed fixed-width county `064`, election `53815`, exact voting date October 30, both ordinary event/method codes `EV`, valid ten-digit VUID and full residence P/S split label; they reconcile exactly to the explicit native batch trailer. No VUIDs, names, addresses or raw records were retained.

The new `dashboard/scripts/collect_final_county_recovery.py` downloads and validates all twelve SOS dates with one shared identity proof, and checks every accepted native identity within/across dates and against the SOS date of that same identity. Only exact same-date joins can prove a full native residence code's unique native target; all foreign/contradictory observed targets invalidate the alias. The existing Panola alias-proof and generic county aggregation owners are reused. Split suffixes are never truncated.

Four native inputs are excluded entirely from aliases/observations: October 19 contains mixed October 19/20 detail dates; October 25/28/29 each contain an `EV/PE` row. Their URLs/hashes and exact reasons are retained in `dimmit-proof.json`. Their rows do not supply aliases. The remaining eight files supply unique full-code alias evidence. The final output has **222 votes in native precincts 1–7 and six UNASSIGNED observations** carrying unproved codes `S5.5` and `S6.3`. No zero or missing vote is inferred.

The collector returns an **atomic twelve-source series**: the eleven freshly revalidated positive SOS sources, followed by the native final fallback. Every earlier SOS **count map, URL and original CSV SHA-256** exactly equals the parent's pinned deployed edition. The final state's HTTP200 empty body is explicitly recorded as unavailable, with its empty-body hash and `zero_certified:false`. Native fallback hashes bind those exact earlier source editions, so the Rust caller does not need to re-download a potentially revised SOS edition. Malformed schema, invalid/duplicate IDs, wrong methods/dates, false/non-string upload values and explicit API-error envelopes remain errors. Missing upload/empty body are availability states only.

Against unchanged pinned history/geography, final current and paired availability improves **0 → 5 of 7 precincts**, containing **1,541 current / 1,345 historical votes**. Two precincts still lack an uninterrupted earlier date chain. Final source observations total 228; the whole selected daily series totals 1,630 observations. These are reported observations, not an independently certified full-county check-in denominator.

`dimmit-live.json` contains all twelve anonymous Daily observations; `dimmit-proof.json` contains source hashes, counts, rejection/availability facts and `fallback_dates:["2026-10-30"]`; `dimmit-acceptance.json` records exact preservation and before/after coverage.

## Swisher: positive final activity, missing precinct proof

The [official election page](https://www.co.swisher.tx.us/page/swisher.Elections) links [Early Voting In Person, October 30](https://www.co.swisher.tx.us/upload/page/7290/2026/EV%20In%20Person%2010.30.2026.pdf), SHA-256 `ec8ed9c93b99c8149cca0061c1ba7be275b4801edfce462dd18520f73231e3c6`. Its cumulative roster contains **1,027 distinct valid ten-digit VUIDs**, no repeated VUIDs, and no unparsed nonempty rows; **129 are explicitly dated October 30** under `DATE VOTED IN PERSON`. This establishes published positive final-day in-person activity, not a reconciled ordinary-vote aggregate.

The PDF contains only name, VUID and in-person date, with **no residence precinct field**. The official page advertises a precinct map and general registration services, but no active VUID-to-residence-precinct voter roll. A map cannot join these identities. No Swisher adapter or estimated precinct votes were created. Anonymous scope/date/uniqueness facts are retained in `swisher-facts.json`; personal raw data stayed in memory.

## Remaining county control dispositions

These are bounded-source findings, not claims that a county has no data anywhere. Current notices, previous-election results, blank test reports, personal roster footers and the same SOS portal are not independent final ordinary early-vote controls.

| County | Official source inspected | Material missing proof |
| --- | --- | --- |
| Bandera | [Current elections](https://www.banderacounty.gov/page/elections.current.elections) | Advertised in-person rosters through Oct 28; no independent final ordinary total. |
| Concho | [Elections](https://www.co.concho.tx.us/page/concho.Elections) | Current election notices; no final dated ordinary in-person aggregate. |
| Crockett | [Elections](https://www.co.crockett.tx.us/page/crockett.Elections) | Daily Voter Turnout links through Oct 29; no verified Oct 30 aggregate. |
| Donley | [Elections](https://www.co.donley.tx.us/page/Elections) | Current daily lists through Oct 29; separately labeled early-vote totals concern earlier election material. |
| Fisher | [Election page](https://www.fishercounty.org/page/fisher.ElectionPage) | Turnout link leads to the same state feed; historical results cannot certify current completion. |
| Floyd | [Elections](https://www.co.floyd.tx.us/page/floyd.Elections) | Older/test/zero reports are not November 3 final early-voting controls. |
| Frio | [Elections](https://www.co.frio.tx.us/page/elect.home) | Current notices and rosters; no independent final ordinary total. |
| Hall | [County elections](https://www.co.hall.tx.us/page/hall.County.Elections) | Same state turnout portal; primary/May results excluded. |
| Hartley | [Voter information](https://www.co.hartley.tx.us/page/Voter.Information) | Current dates plus state links and older results; no independent final total. |
| Jackson | [2026 elections](https://www.co.jackson.tx.us/page/Voting.2026.Elections) | Advertised early-vote roster dated Oct 27; no final control found. |
| Lipscomb | [Election information](https://www.co.lipscomb.tx.us/page/lipscomb.ElectionInformation) | Earlier histories/results/current notices do not supply the required final ordinary total. |
| San Saba | [Elections](https://www.co.san-saba.tx.us/page/sansaba.Elections) | Current histories through Oct 28; no independent final control. |
| Stephens | [Elections](https://www.co.stephens.tx.us/page/stephens.Elections) | November notices and earlier primary/runoff results; no final ordinary total. |
| Stonewall | [Elections](https://www.stonewallcounty.org/page/stonewall.Elections) | November notices and earlier official statistics; no current final in-person control. |
| Terry | [November election](https://www.co.terry.tx.us/page/Elections.November) | Current voting information supplies no independently reconciled final ordinary total. |
| Zavala | [2026 election results](https://www.co.zavala.tx.us/page/Election%20Results%202026) | Published results concern primary/runoff, not November early voting. |

## Waller and Washington remain unresolved

Fresh inspection of [Waller's current election page](https://www.co.waller.tx.us/page/2026%20County%20and%20Entity%20Elections) found the same dated in-person rosters and personal E Pulse roster labeled total in-person; it did not produce an independent aggregate. The original comparison remains: paired **14,120** versus SOS **13,431**, a **689 reverse residual**, with retained county-native final observations 2,092 against SOS 10.

Fresh inspection of [Washington's election page](https://www.co.washington.tx.us/page/washington.elections.information) found dated personal workbooks and the same state turnout portal. Paired **11,616** versus SOS **10,788** remains an **828 reverse residual**. October 30 agrees at 1,218; the earlier cumulative source disagreement remains unresolved. Earlier native/SOS scope or revisions cannot be inferred away. The original detailed proof is preserved in `analysis/official-total-gaps/waller-washington/findings.md`; no conflicting control was overwritten.

## Provenance and verification

Primary landing discovery started from the [Texas SOS county election officials directory](https://www.sos.state.tx.us/elections/voter/county.shtml) and followed official county current-election/results pages. Hostname corrections are explicit in request facts: Bandera redirects to `banderacounty.gov`, Swisher to `co.swisher.tx.us`, Stonewall to `stonewallcounty.org`; obsolete/contact email hosts for Frio, Terry, Stephens and Zavala required their actual official county sites. Parked/failed initial hosts supplied no turnout evidence.

`stale-status.json` records every named county's pinned state row, primary URL, disposition and page hashes/timestamps. `root-facts.json`, `elections-facts.json`, `final-facts.json`, `current-facts.json` and `results-facts.json` preserve bounded request/link evidence. `raw-manifest.json` hashes the retained **public landing/contact/result HTML only**. No personal voter-source payload was saved. Firecrawl's insufficient credits had already been established; existing official direct HTTP transport was reused without account changes.

Executed verification:

- `python -m unittest discover -s dashboard/tests -p test_final_county_recovery.py -v`: **7 passed** (`focused.log`), including full collector behavior with one rejected earlier native publication and an HTTP200 empty final SOS response, identity/date/method/schema guards, all-target ambiguity, unchanged earlier-source facts, quarantine and empty-envelope handling.
- Real memory-only Dimmit collector command completed successfully and produced twelve Daily observations; exact earlier count/URL/hash preservation and coverage reconstruction passed assertions in `dimmit-acceptance.json`.
- Independent reviewer reran all seven focused tests and zero/BOM/envelope edge guards; confirmed live preservation and found no remaining material blocker in the reviewed script.
- All 20 county dispositions were reconciled to the parent CSV; the 18 stale prior cumulative totals independently sum to 25,940.

Parent owns Rust adapter wiring, integrated runtime refresh, broad verification and master-report changes. New code is limited to `dashboard/scripts/collect_final_county_recovery.py` and its new focused Python test. No commits, pushes or publication were performed here.
