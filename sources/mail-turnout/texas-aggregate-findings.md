# Texas mail plus early in-person aggregate reporting

Checked 2026-10-24 America/Chicago, using retained official responses followed by live read-only aggregate probes. No voter-detail endpoint was requested. Probe code and anonymous evidence are under `analysis/mail-turnout/`.

## Exact source fields

The SOS links the current Civix portal and its 2020–2025 historical portal from its official [Election Results/Data index](https://www.sos.state.tx.us/elections/earlyvoting/index.shtml). This establishes the two third-party hostnames' official provenance.

**2026:** GET `https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile?type=EVR_EARLYVOTING&electionId=53815&electionDate=10%2F23%2F2026`. The JSON response has a base64 `upload` containing aggregate JSON. Its identity fields include `election_id`, `early_voting_date`, and `date_updated`. Each `turnout_by_county` row contains these count fields:

| Field | Observed meaning |
| --- | --- |
| `in_person_votes_on_date` | Published daily in-person count |
| `total_in_person_votes_for_election` | Published cumulative in-person count |
| `total_mail_votes_for_election` | Published cumulative by-mail count |

Other county fields are `id`, `name`, `registered_voters`, and a voter-report link. The aggregate response provides **no daily mail field**, issued-ballot field, accepted-ballot field, county report timestamp, or county completion flag. The current Rust `statewide::current_rows` validates the mail field's presence among allowed names but drops its count from `Aggregate`.

**2024:** POST [getEVDetails.do](https://earlyvoting.texas-election.com/Elections/getEVDetails.do) with form `idElection=49664`, `selectedDate=2024-10-25 00:00:00.0`, `pollPlaceIdtown=` and `electionDate=,`. Zero-based HTML table indexes are:

| Index | Meaning |
| --- | --- |
| 0 | County |
| 1 | Registered voters |
| 2 | Daily in-person, with requested date in heading |
| 3 | Cumulative in-person |
| 4 | Cumulative in-person percentage |
| 5 | `Cumulative By Mail Voters` |
| 6 | `Cumulative In-Person And Mail Voters` |
| 7 | Cumulative early-voting percentage |
| 8 | Voter-report link |

Both county and statewide `TOTAL` rows expose indexes 5 and 6. For each of the 12 retained dates October 21–November 1, 2024, all 254 county mail values sum exactly to the mail TOTAL, and every county's index 6 equals indexes 3 plus 5. This independent audit is saved in `analysis/mail-turnout/retained-aggregate-audit.json`. It should become a parser validation rather than relying only on header position.

## Concrete cross-cycle observations

All values below are actual aggregate responses; combined values for 2026 are arithmetic sums of its two native cumulative fields.

| County/date | Cumulative in-person | Cumulative mail | Combined |
| --- | ---: | ---: | ---: |
| Harris 2024-10-20, before regular opening | 0 | 23,831 | 23,831 |
| Harris 2024-10-21, opening day | 126,473 | 25,602 | 152,075 |
| Harris 2024-10-25, day 5 | 570,614 | 37,722 | 608,336 |
| Harris 2026-10-18, before regular opening | 0 | 20,654 | 20,654 |
| Harris 2026-10-19, opening day | 104,606 | 22,444 | 127,050 |
| Harris 2026-10-23, day 5 | 411,096 | 29,255 | 440,351 |

The retained 2026 Harris day-5 SOS in-person figure has already been identified elsewhere in this project as underfilled compared with native county data. The table records its source exactly; it is not an endorsement of replacing the existing qualified county in-person observation with that SOS figure. Method and geographic scope must remain explicit when combining stronger county in-person totals with SOS mail aggregates.

## Pre-opening mail and daily derivation

Pre-opening reports are available in **both** systems. Live probes retrieved 2026 October 17/18 and historical 2024 October 19/20, each containing all 254 counties. The historical date-selection response for election 49664 lists daily reports starting September 29, 2024. Historical requests made through plain urllib received HTTP 403; the project's existing `curl_cffi` Chrome transport successfully returned the same aggregate pages.

| Date | State cumulative mail | State cumulative in-person |
| --- | ---: | ---: |
| 2024-10-19 | 160,708 | 22 |
| 2024-10-20 | 161,958 | 24 |
| 2026-10-17 | 111,443 | 164 |
| 2026-10-18 | 112,077 | 164 |

Do not assume the day-before-opening baseline is zero, even for cumulative in-person: the source itself has small pre-opening in-person amounts, whose subtype was not determined in this task. For daily mail on an opening day, fetch the actual previous calendar day's cumulative mail. Harris opening-day mail is 1,771 in 2024 and 1,790 in 2026, rather than the entire previously returned mail stock. Cumulative combined turnout should include that stock.

Recommended calculation: daily mail is `M(date) − M(previous calendar date)` only when both published values exist and the result is nonnegative. Daily combined is qualified daily in-person plus that valid daily mail value; cumulative combined is qualified cumulative in-person plus same-date cumulative mail. Missing/negative daily values must not invalidate an independently available cumulative observation. Missing intervals must not be spread across dates.

Actual negative mail deltas were found and must not be silently clamped: 2024 October 20→21 has Dawson 2→0, Delta 87→0, Swisher 60→0, Crane 9→0, Coke 65→0, Dickens 21→0, Borden 1→0; Williamson has 7,091→7,090 on October 26→27. In 2026 October 18→19, Eastland has 101→100, Lynn 8→1, Rockwall 340→303, and San Jacinto 150→134. No negative county mail transitions were found within retained October 19–23, 2026 reports.

## Returned, issued, accepted, and completeness

The [SOS 2026 election calendar, early-voting-roster section](https://www.sos.texas.gov/elections/laws/advisory2026-21-november-3-election-law-calendar.shtml) explains that mailed-voter roster information becomes public following receipt of a voted mail ballot. The [Election Code §87.121](https://statutes.capitol.texas.gov/Docs/EL/htm/EL.87.htm#87.121) distinguishes issuance-roster privacy from receipt-triggered publication and county/SOS submission deadlines. Acceptance is a separate ballot-board determination under [§87.041](https://statutes.capitol.texas.gov/Docs/EL/htm/EL.87.htm#87.041). Consequently, the defensible display label is **reported mail** or **mail returned**, with the receipt interpretation identified as an inference from publication rules. The aggregate fields do not certify accepted mail ballots and must not be labeled accepted or issued.

The historical page states that county officials provide the data and the SOS does not change it. Native 2026 county rows all have numeric mail values in examined files: no nulls, with 8 zeros on October 23. These zeros carry no individual completion flag, so a literal zero does not independently certify a completed zero report. The global `date_updated` is not a county timestamp. Preserve source values and disclose their reporting basis; do not infer finality or allocate missing mail using in-person counts or county demographics.

An especially important live counterexample is saved in `analysis/mail-turnout/probe-2026-2026-10-25-summary.json`: requesting future October 25 returned HTTP 200, the requested date string, all 254 counties, zero daily in-person, cumulative in-person **3,504,898** and cumulative mail **192,606**, while `date_updated` remained October 24. Thus successful download, a matching requested date, and 254 rows do **not** certify a completed day's publication. Keep the explicit completed-date cutoff; future current-cycle values must remain null. County/date/measure membership should continue to be matched separately for each observation, with no whole-county exclusion due to an unrelated missing daily point.
