# North Carolina early turnout

The [NCSBE absentee download page](https://www.ncsbe.gov/results-data/absentee-and-provisional-data) publishes statewide detailed absentee/early-vote archives and independent aggregate count CSVs for both general elections. The detailed archive includes residence county and precinct, recorded ballot return date and status, registration party, race, ethnicity, age and sex. The collector processes these records in memory, stores no identities or addresses, and retains the archive URL and SHA-256. Only aggregate data are written.

## Sources and meaning

- [2026 detailed archive](https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/absentee_20261103.zip), [2024 detailed archive](https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/absentee_20241105.zip): include only statuses beginning `ACCEPTED` in turnout. Pending cure, cancelled and failed verification are excluded. Accepted-exception and accepted-cured ballots remain included. Official controls count accepted records, including a small number of repeated NCIDs; these are recorded diagnostically rather than silently removed from official totals. Identifiers are retained only in memory for this check.
- [2026 statewide controls](https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_11_03/absentee_counts_state_20261103.csv), [2024 statewide controls](https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/absentee_counts_state_20241105.csv): aggregate totals independently check detailed accepted rows by in-person/mail method. Public controls are saved by content hash. Differences are disclosed, preserving reported county/date observations; they do not exclude an entire year. A failed detailed download retains prior observations.
- [2024 certified precinct election results](https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip): presidential Harris/Trump votes are summed by county for partisan buckets. This archive contains election aggregates and is retained by content hash.
- [Official Census county Gazetteer](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.zip): validates all 100 county FIPS codes, retained as a small aggregate mapping with source hash. FIPS order is not exactly alphabetical around McDowell; no row-number inference is used.
- In-person voting began [October 17, 2024](https://www.ncsbe.gov/news/events/person-early-voting-period-2024-general-election) and [October 15, 2026](https://www.ncsbe.gov/voting/vote-early-person). These dates anchor equivalent early-voting days. Mail returns preceding those dates remain in cumulative totals.

`ballot_rtn_dt` provides the date: mail receipt/return and recorded early in-person ballot return. It is not the download or acceptance processing date. Historical 2024 is reconstructed from currently accepted ballots and their return dates; subsequent cures/rejections can revise that history. These observations describe reported data, not proof that every county uploaded every ballot by publication time.

The main dataset supports all 100 counties, daily and cumulative turnout, in-person/mail/total methods, and separate party, race, age, sex, ethnicity and explicit white/non-white voter breakdowns. Party means voter registration, not candidate choice. Unknown race/ethnicity is retained explicitly: White with unknown ethnicity does not establish non-Hispanic White; affirmative non-White race or Hispanic ethnicity establishes the non-White group. These describe participating voters, separately from Census resident composition.

Each covered county/date/method explicitly includes zero counts for the supported category labels when its statewide accepted-record roster contains no such records. This prevents a real zero from being mistaken for an unavailable group. Dates later than the last reported return date remain absent, rather than receiving manufactured zeros.

The detailed 2024 archive has five more accepted in-person records than the independent statewide count CSV. HTTP metadata puts the CSV publication at December 9, 2024, 17:57:12 UTC, and the detailed archive at 18:15:03 UTC. Different publication times are an observed fact; they do not by themselves prove the cause of the discrepancy. The published detailed records are retained and the five-record difference is disclosed. No county or date is discarded because of this independent control gap.

Precinct daily counts are preserved in `precinct-daily.json`; cross-cycle precinct comparability is deliberately **unproven**. Equal precinct names cannot establish unchanged boundaries. The dashboard may inspect current precinct counts, but comparisons use county geography until a reliable boundary crosswalk is available. No historical precinct ratio is inferred from matching labels.

## Reproduction and verification

```bash
python3 dashboard/scripts/states/north_carolina.py --through 2026-10-23
python3 -m unittest discover -s dashboard/tests -p test_north_carolina.py
```

The collector caches historical aggregate observations, refreshes current observations and controls, preserves last successful year data on failure, and saves validation metadata in `dashboard/data/states/nc.json`. Use `--force-history` to rebuild historical aggregate observations from the official detailed archive. Fixture checks cover accepted statuses, duplicate accepted records, invalid/changing schemas, daily/cumulative method reconciliation, and demographic unknowns. Live totals and calendar coverage are recorded below after collection.

Live collection on October 24, 2026 produced **57,600 county observations**: 2024 from September 20 through November 4, and 2026 from September 4 through October 23. October 23 cumulative reported turnout is **1,453,517**: 1,395,125 in person and 58,392 by mail. The independent current CSV has one fewer in-person ballot and identical mail counts; its publication preceded the detailed archive by 41 minutes. Historical detailed accepted in-person totals exceed the independent CSV by five; mail totals agree exactly. All differences remain explicit.

The separate precinct artifact contains reported counts for 2,658 historical and 2,625 current residence precincts. County presidential totals sum to 2,715,375 Harris and 2,898,423 Trump. All 57,600 rows were independently checked for unique keys, nonnegative values, valid county FIPS, six demographic breakdown sums, method additivity, and daily-to-cumulative arithmetic. Five fixture tests and Python compilation passed. Aggregate verification is saved in `verification.json`.
