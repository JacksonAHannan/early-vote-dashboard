# Large-county missing precincts: engine and Travis audit

The frozen public snapshot is `analysis/large-county-recovery/public-before.json`, generated October27,2026 at07:51UTC, through October26 (Day8). This investigation did not change matching, source adapters, retained observations, references, services or controls. Raw voter workbooks/identities are processed only in memory; saved diagnostics contain county/date/precinct aggregates and source hashes.

## Reproduced mechanism

The engine uses geographic comparison groups, rather than comparing every current native precinct independently. One absent current or historical constituent makes the **whole corresponding group** unavailable. This preserves exactly the same geography in both cycles; it also magnifies the apparent native precinct gap.

| County | Day1 native precincts unavailable | Actually absent current source labels | Current unknown positive labels | Independently controlled historical omissions |
|---|---:|---:|---:|---|
| Harris |160|89|0|2024 completion confirmed; absent2024 labels become zeros|
| Bexar |136|100|18 labels/18 votes|2024 completion confirmed|
| Dallas |181|69|UNASSIGNED=75|2024 UNASSIGNED=54 blocks zero certification; 101 historical labels absent|
| Tarrant |139|35|19 labels/19 votes|2024 county control58587 vs roster58486, UNASSIGNED=1;183 historical labels absent|
| Travis |31|13|0|2024 completion confirmed|
| Collin |17|8|18 labels/19 votes|2024 completion confirmed|
| Denton |23|18|16 labels/17 votes|2024 completion confirmed|
| FortBend |7|4|0|2024 completion confirmed|
| ElPaso |29|13|1 label/1 vote|2024 completion confirmed|

`analysis/large-county-recovery/engine/day1-source-causes.json` retains the precise group constituents, omitted labels, foreign positive labels and original-project controls. Geographic omissions differ from unclassified partisanship: on available Day1 geography, Denton has155 native precincts with missing/tied presidential data; FortBend134. Those are not missing turnout observations and must not be repaired by inventing party scores or removing source safeguards.

Ranked hypotheses tested:

1. **Unproved missing-row zeros:** exact controls or unmapped positive labels prevent certification. Confirmed across the large counties. Original authoritative Harris control104657 differs from roster104658; the Git checkout's older104658 control is stale and must not overwrite it.
2. **One missing constituent blocks a larger comparison group:** confirmed. Travis13 omitted source labels block31 native precincts in10 groups. No geographic allocation is an acceptable shortcut.
3. **Historical absent labels also block comparisons:** confirmed in Dallas/Tarrant; more current rows alone cannot recover those groups.
4. **Partisan classification mistaken for turnout absence:** a separate large effect in Denton/FortBend, not a matching-engine defect.
5. **Global engine flag/normalization bug:** not established. Existing matching correctly refuses positives outside its native universe and unproved zeros.

## Travis exact source discrepancy

The [official election page](https://votetravis.gov/current-election-information/current-election/) links the [G26 roster ZIP](https://votetravis.gov/wp-content/uploads/G26-Voter-Rosters.zip) and [ElectionLink turnout widget](https://updates.electionlink.net/widgets/travistx/2026-11-03/index.html). Fresh aggregate-only diagnostics are reproducible with:

```sh
python3 sources/large-county-recovery/travis_probe.py --output analysis/large-county-recovery/engine/travis-roster-probe.json
```

ZIP SHA256 `6aaaf5070acf3588ec034ced8f4292f96fe20aa224c231cd8a335db00ff0d521`. Day1 has40777 workbook rows but40776 distinct VUIDs, exactly one identical repeated identity in the same precinct, no blank IDs, no conflicting IDs and no cross-date identity duplicates. The county graph reports40777. Day4 has37774 unique roster identities vs graph37773. Other Days2,3,5–8 reconcile exactly. **Do not use a generic ±1 allowance or assume a duplicate explains away an unknown missing voter.** The independent control's precise counting definition does not justify whole-Day1 zero certification.

## Verified bounded zero: Travis159

The [county-linked precinct table](https://updates.electionlink.net/widgets/travistx/2026-11-03/TurnoutByPrecinctTable.html) explicitly publishes Early Vote=0 for precinct159 (one registered voter). It has299 precinct rows. Their ordinary EarlyVote sum275317 exactly equals the sum of eight dated ordinary-EV daily graph observations. ElectionDay and provisional application columns and mail arrays are excluded. Report generation is October27 at04:23Central; all positive dated graph observations end October26. Thus its explicit cumulative zero is bounded through October26, before the active voting day. No retained earlier159 count is positive.

Archived aggregate evidence (no voter information):

- `travis-precinct-20261026.html.gz`: SHA256 `a590bde5167bf00eb1b8ef9042c3f157b7291f089ddfd181d6c7d2e2d9ccfb1d`.
- `travis-daily-20261026.html.gz`: SHA256 `865bf1947b05c8b34623d059fd1586862b84eb5f2c6ed4c29b0e6afc7d4411d6`.

```sh
python3 sources/large-county-recovery/travis_zero_proof.py --table sources/large-county-recovery/travis-precinct-20261026.html.gz --graph sources/large-county-recovery/travis-daily-20261026.html.gz --snapshot analysis/large-county-recovery/public-before.json --through 2026-10-26 --output analysis/large-county-recovery/engine/travis-zero-proof.json
python3 -m unittest discover -s dashboard/tests -p test_travis_explicit_zeros.py -v
```

Ten tests pass. They reject wrong method columns, mismatched totals, duplicate normalized precincts, missing dates, active dates and any contradictory prior positive precinct observation. The proof certifies only literal159 zero, not absent rows or backwards allocation of positive cumulative votes. Nine of the13 missing Day1 native labels are absent from the current vendor's precinct universe; they remain unproven. The other three (248,369,443) have positive cumulative turnout and cannot establish an earlier zero.

Exact-symptom command, run against the actual frozen public input (red,0.3s):

```sh
python3 sources/large-county-recovery/check_travis_159.py --snapshot analysis/large-county-recovery/public-before.json --output analysis/large-county-recovery/engine/travis-red.json
```

It fails because missing159 discards the otherwise fully observed historical127/142/143/145 vs current127/142/143/145/149/158/159 comparison group. Adding only proved159=0 recovers seven native precincts/one group in every cumulative Day1–8, with no controls relaxed: Day1 available277→284; Day8 available268→275. This is a **simulation**, recorded in `engine/travis-simulation.json`; the root agent owns actual integration and post-fix acceptance.

## Collin native alternative under investigation

The [official roster page](https://www.collincountytx.gov/Elections/rosters) links a current county early-voter workbook separately from returned mail ballots and eight dated polling-place check-in PDFs. The October19 PDF has34522 in-person check-ins versus state roster34260. The current county workbook SHA256 is `d9495d5e76a0af99bbe97b13ccb82a4d3ae7206e43e581a18f14e9d0aec875bb` (19.5MB downloaded in memory). Its244801 EarlyVoting rows include244093 Regular and708 Provisional rows. The initial aggregate diagnostic is unfiltered and is **not** an approved publication input; regular-only filtering and local identity quarantines are mandatory. Scope reconciliation is still under investigation. No foreign source precinct is guessed into a native precinct.

The regular-only Collin audit finished. Ordinary county rows contain **no native precinct IDs missing from SOS** for Days1–7. Filtering Provisional is essential: Day1 site34522 includes101 Provisional rows, whereas ordinary rows34421 have five blank voter identities requiring five local cell quarantines. Replacing the public series with this alternative would reduce coverage; no such replacement is proposed. Native county and SOS ordinary counts differ in many already observed cells, and the control's all-checkin scope cannot certify ordinary-roster omitted zeros. `engine/collin-roster-probe-regular.json` is diagnostic only.

## Denton: current control and native presidential recovery

The [actual current roster page](https://www.votedenton.gov/early-voting-election-day-rosters/), reached from the county's current election page, differs from obsolete guessed URLs. Normal urllib requests returned misleading empty bodies; the project's existing browser-impersonation HTTP transport retrieves the published page. It links a current in-person workbook separately from returned mail ballots and the aggregate [polling-place report](https://www.votedenton.gov/wp-content/uploads/2026/10/1126_10-26_ev_by_day_poll_pad.pdf). This report was generated October26 at19:30Central, explicitly excludes mail, and includes privacy voters. All54 polling-site rows individually reconcile daily values to row totals, and all eight summed site columns exactly equal county34739,31563,28359,25964,30136,27858,13629,24468 (cumulative216716). SHA256 `49d3cdefcc6ecaef35a3eccefe8d62fbbf895caa9ffef2ace2aea64c9f6dfa7d`. The separate district report independently agrees but contains legislative/commissioner/JP districts, **not election precincts**. It provides no election-precinct zero evidence. Source-scope matching is still required before any roster zero certification. These observations are in `engine/denton-native-controls-candidate.json` and are not applied to controls here.

The largest verified Denton gap is classification, not missing turnout. Its geographic TLC pipeline supplies presidential returns for94 of240 historical native precincts. The county's [official results archive](https://www.votedenton.gov/election-results-and-maps/election-results/) public SOE endpoint `/ce/mobile/seam/resource/rest/election/getElection?eid=140&lang=en&callback=soeElectionObj.processElection` identifies the November5,2024 general election and links its [official reports ZIP](https://assets01.aws.connect.clarityelections.com/Assets/Connect/RootPublish/denton-tx.connect.clarityelections.com/ElectionResults/2024/1124/2024_General_Election_Results_Reports.zip).

Verified source edition:

- Reports ZIP SHA256 `696dda44fa4afabd7ac1c3f9d7b5bacaed70478321b1f6e95711985e14051c48`.
- Member `Stamped/Denton County Canvass-16-11-2024 12.59.52.pdf`, archived as `denton-2024-presidential-canvass.pdf`, SHA256 `eb531fbe7489d43c34222b612f05216dba62fbc7091cac273c848b61c57c5191`.
- Separate county summary member `Stamped/Denton County Cumulative-16-11-2024 12.42.02.pdf`, archived as `denton-2024-county-summary.pdf`, SHA256 `82647a8409d390e8d1348ace3b846034a3b6b6e818239fbdeeb67f88d7b6ded5`.

The signed canvass contains **exactly the same240 native historical precinct IDs** as the official geographic reference, with no missing or foreign IDs. In every row, ten candidates sum to cast votes; cast+under+over sum to ballots; mail+early+ElectionDay sum to ballots. All18 numeric columns conserve county totals. Trump250521 and Harris191503 also reconcile by method in the separate county cumulative report. All94 existing TLC-derived native returns agree exactly;146 additional native returns can therefore fill the reference without changing any existing presidential vote count or allocating geography. First-page visual inspection confirmed candidate column order, election date, signed official status and separate voting-method ballot columns.

```sh
python3 sources/large-county-recovery/denton_presidential.py --pdf sources/large-county-recovery/denton-2024-presidential-canvass.pdf --summary-pdf sources/large-county-recovery/denton-2024-county-summary.pdf --reference dashboard/data/reference.json --output analysis/large-county-recovery/engine/denton-presidential-candidate.json
python3 -m unittest discover -s dashboard/tests -p test_denton_native_presidential.py -v
```

Twelve tests pass, including exact native universe, missing/foreign/duplicate IDs, every source total column, row ballot arithmetic, independent county-method reconciliation, wrong election/county and refusal to overwrite an existing conflicting presidential return. The actual pinned PDF parser and independent county-summary validation passed.

Simulation using the actual valid published pairs and identical integer margin-band thresholds: Day1 partisan-excluded native precincts155→23, recovering132 native precincts/118 comparison groups. Remaining23 are20 mixed-band constituents and3 zero/tied presidential constituents; they remain unclassified. Days2–3 recover131 native precincts; Days4–7 recover130. None of this changes turnout availability or group geometry. The candidate and `engine/denton-presidential-simulation.json` await root integration and actual post-build checks.
