# Dallas and Harris precinct recovery — 2026-10-27

This audit uses official residence-precinct in-person rosters and independently
dated county controls. Mail, site totals, and county totals never become
precinct votes. Voter identifiers, names, addresses, raw workbooks and voter CSVs
stay in memory/anonymous pipes; the persisted proofs contain only precinct
counts, dates, source URLs, hashes and validation diagnostics.

## Dallas: recover blank precincts by exact official identity

The published Day 1 comparison had 610 of 791 current native precincts available.
The missing groups involved 76 current precincts lacking a historical observation,
47 lacking a current observation, and 58 lacking both. This is common-group
coverage, so the attribution can exceed the number of absent native labels.

Both county workbooks contain valid voters with blank residence `PRECINCT`:
210 across the twelve 2024 days, and 192 across current Days 1–7. These records
were retained as `UNASSIGNED`, correctly preventing county-wide absent-row zero
inference even when total votes agreed with independent county controls.

The same-date official SOS CSV supplies a valid residence precinct for every one
of those 402 records. Recovery requires the county row's `SOS VOTERID` to occur
exactly once in the whole native workbook, exactly one same-date in-person SOS
`ID_VOTER` row, and one precinct in that year's native reference universe. Names,
addresses, ballot styles, prefix matching, and spatial allocation are not used.
The complete native source remains authoritative for every other row, date,
precinct and vote total. No unrelated SOS rows are imported. Blank-identifier
quarantines remain in force.

| Day | 2024 date | 2024 resolved | 2026 date | 2026 resolved |
| --- | --- | ---: | --- | ---: |
| 1 | Oct 21 | 54 | Oct 19 | 75 |
| 2 | Oct 22 | 24 | Oct 20 | 35 |
| 3 | Oct 23 | 32 | Oct 21 | 20 |
| 4 | Oct 24 | 10 | Oct 22 | 29 |
| 5 | Oct 25 | 14 | Oct 23 | 11 |
| 6 | Oct 26 | 15 | Oct 24 | 13 |
| 7 | Oct 27 | 12 | Oct 25 | 9 |
| 8 | Oct 28 | 6 | Oct 26 | unavailable |
| 9 | Oct 29 | 17 | — | — |
| 10 | Oct 30 | 12 | — | — |
| 11 | Oct 31 | 3 | — | — |
| 12 | Nov 1 | 11 | — | — |

Historical county workbook:
<https://www.dallascountyvotes.org/wp-content/uploads/2024/11/In-Person-Early-Voting-Turnout-Report_11.01.24.xlsx>
SHA-256 `ad886583efbd1dd0054489141de4ef86e71af58e228799e05b550edf7dfad05a`.
Current county workbook:
<https://www.dallascountyvotes.org/wp-content/uploads/2026/10/In-Person-Early-Voting-Turnout-Details-Report_10.26.2026.xlsx>
SHA-256 `37e2fbf7fd1f5baca92723a78053c00d5e985fe02518f46e33856cfde95b1959`.
The hashes match the frozen public source edition, rather than a different file
being substituted accidentally.

Historical SOS endpoint:
<https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do>,
POST `idElection=49664`, `selectedDate=YYYY-MM-DD 00:00:00.0`,
`electionDate=,`, `earlyVoteFlag=true`, `downloadElectionFileCSVFlag=true`,
`idTown=57`. Current endpoint:
<https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat>,
GET `type=EVR_EARLYVOTING`, `electionId=53815`,
`electionDate=MM/DD/YYYY`, `county=DALLAS`, `countyId=57`, `format=csv`.
All per-date SOS hashes and aggregate destination counts are retained in
`analysis/large-county-recovery/harris-dallas/dallas-*-enrichment.json` and the
recovery edition's source notes.

All twelve enriched 2024 totals exactly match independent county controls.
The current native totals remain
`77854, 65084, 56092, 49469, 54345, 36613, 19183, 44140`.
Current Day 1 remains one below its 77,855 control. The Oct 23 precinct 2130,
Oct 24 precinct 4640, and Oct 26 precinct 1040 cells remain quarantined.
The current Oct 26 SOS endpoint returned no usable export, so six blank-precinct
rows remain unassigned. The Oct 25 county roster has revised to 19,183 while
the retained Oct 25 control still has 19,180. These discrepancies never certify
missing precincts as zero.

The final integrated eight-day rebuild, using freshly downloaded independent
controls, increases Day 1 paired current-precinct coverage from **610 to 686**
and Day 8 from **533 to 560**. An earlier projection of 631 on Day 8 used older
retained controls and was rejected: newer historical controls differ by one vote
on some dates and cannot certify omitted precincts as zero. Native daily totals
are unchanged. Recovery of a paired precinct is separate from eligibility for a
partisan bucket or a ratio with a positive 2024 denominator.

The durable current-Dallas adapter performs this exact-ID enrichment before
aggregation, using the already downloaded native workbook. SOS failures leave
native observations unchanged. Four concurrent optional identity-source requests
are bounded to 60 seconds each. A successful date gets a derived SHA-256 over the
canonical native/SOS input-hash and method manifest, with both source URLs and
original input hashes in the note. The recovered historical edition is pinned
to the reviewed native archive, preserving the original county `IDNUMBER`
identity contract and its documented reused historical SOS identifier.

## Why whole SOS roster substitution is insufficient

Dallas 2024 SOS totals are one below county controls on Oct 24, Oct 29 and
Oct 30, and 92 above on Nov 1. The current Day 1 SOS report totals 77,830,
with 26 one-vote labels outside the current native universe. These reports
cannot be blindly substituted, merged, or used to certify missing zeros.
The exact-ID process imports only a proven residence label for an existing
native row and conserves every native daily total.

## Harris: verified publication/control gaps remain

The actual official roster landing is an iframe:
<https://app.harrisvotes.com/ElectionResults/ElectionRosters>, linked from
<https://www.harrisvotes.com/Election-Results/Election-Rosters>.
Its current Nov 2026 in-person link is explicitly labeled **October 19 through
October 25, 2026**. No alternate Oct 26 in-person roster or daily CSV is offered.
The mail roster is separately labeled and never substitutes for in-person data.

The advertised native ZIP remains
<https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_ToPost_1126.zip>,
SHA-256 `040ef10b9c79f9e5eea6ee32c19c7d94fdc0a1bf39301c243497f34223c703f2`.
It contains exactly seven dated CSV members, October 19–25. The retained source
was re-downloaded and inspected, rather than assuming its cached date range.

The current independently dated check-in control is
<https://appfiles.harrisvotes.com/harrisvotes/prd/docs/Uploads/EVPA_unofficial.pdf>,
SHA-256 `2233477e32f6deedecebe1662977893085e2a85a501c1df80d39a1148f3f0667`.
Its in-person row reports Oct 19 **104,657**, Oct 23 **95,107** and Oct 26
**79,474**. Independently summing all 75 location rows reproduces these totals,
and every location's daily/cumulative arithmetic agrees. The current native ZIP
reports 104,658 and 95,108 on Oct 19/23, one above each revised control.
The Oct 19 SOS in-person roster independently totals 104,606, also incomplete.

Therefore Harris Day 1/5 omissions cannot safely become zeros, and Day 8 county
aggregate availability does not establish unpublished precinct counts. This is
an official-source mismatch/publication delay; the existing positive native
precinct observations stay available. A current source revision should be
rechecked automatically on the normal refresh schedule.

## Verification

- Red-capable actual-parser regression: `cargo test --manifest-path dashboard/Cargo.toml dallas_exact_identity_recovers --lib` failed with 0 versus 1 recovered row before implementation, then passed.
- Full library unit suite passed 127 tests after the shared `zero_evidence` constructor addition. Focused library Clippy passed with `-D warnings`; the root release verification covers later integrated county changes.
- `python3 sources/large-county-recovery/test_dallas_identity.py`: six tests passed, covering unique matches, cross-date/native ambiguity, repeated SOS identities, foreign labels, partial recovery and native count conservation.
- Opt-in real current-Dallas acceptance: `TURNOUT_DALLAS_IDENTITY_OUTPUT=... cargo test --manifest-path dashboard/Cargo.toml --test dallas_identity_live -- --ignored --nocapture` passed in 83.06 seconds. Its first seven dates agree with the independent Python evidence in every precinct count, derived source hash and quarantine; anonymous output is `analysis/large-county-recovery/harris-dallas/dallas-native-live-enriched.json`, with reconciliation in `dallas-live-reconciliation.json`.
