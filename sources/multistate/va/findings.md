# Virginia early turnout

The live dashboard uses all 133 localities from EPEC's published aggregate metrics of Virginia ELECT Daily Absentee List files. This is an independent publisher's transformation of official voter-file observations, not an official aggregate API. The [2024 aggregate archive](https://digitalpollwatchers.org/files/DALTracker/2024_November_General/metrics/2024_November_General-DAL-metrics.zip) and [2026 aggregate archive](https://digitalpollwatchers.org/files/DALTracker/2026_November_General/metrics/2026_November_General-DAL-metrics.zip) contain locality and precinct time series; exact downloaded aggregate archives are content-addressed in `raw/`.

Virginia ELECT's [registration/turnout page](https://www.elections.virginia.gov/resultsreports/registrationturnout-statistics/) explicitly publishes statewide turnout after certification. It is not a live daily source. Its final 2024 turnout was not substituted for a day-matched early-voting baseline.

## Transformation

- Morning `FILEDATE` snapshots are attributed to the preceding calendar date. The latest timestamp wins when a date appears more than once. The archive's 2026 October 24 morning snapshot therefore appears as October 23.
- `COUNTABLE` is the overall countable absentee count; `MAIL_IN` and `ON_MACHINE` are separate method series. Their sum can differ from `COUNTABLE`, which also includes separately countable categories such as federal/provisional ballots. No forced reallocation reconciles this difference.
- Cumulative values are each dated snapshot. Daily values are differences between consecutive snapshots when nonnegative. A decline omits only that daily observation; the actual cumulative snapshot survives. These daily changes describe reporting changes and may include corrections; they are not a final-file reconstruction by original ballot-return date.
- The official [Census county gazetteer](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/Gaz_counties_national.zip) supplies locality FIPS identifiers, including independent cities. Historical Bedford City metadata is excluded because it has no current locality observations.
- The series covers September 20–November 4 in 2024 and September 18–October 23 in 2026 on this refresh. The 2024 future reference remains dated; 2026 future dates remain absent.
- Precinct aggregate series exist in the preserved archives, but boundary equivalence and a 2024–2026 crosswalk have not been established. They are not published as purportedly matched precinct comparisons. No voter identities are downloaded from this producer.
- Virginia has no party-registration field comparable to Nevada/North Carolina. Party registration is omitted.

## Official county cross-check and limits

The [Fairfax Office of Elections](https://www.fairfaxcounty.gov/elections/) links its [daily aggregate PDF](https://www.fairfaxcounty.gov/elections/sites/elections/files/Assets/AB%20Daily%20Report/AB%20Daily%20Report%20-%20Nov%203%202026%20-%2009192026.pdf). The file retrieved for this work is updated October 22, 2026 and reports 108,109 ballots: 63,094 in person and 45,015 mail/drop-box returned. EPEC's October 23 morning DAL snapshot (attributed to October 22) reports 105,503 countable, 63,091 on-machine and 42,409 mail-in for Fairfax. These are different published status/reporting definitions, especially for mail; the county returned total does not validate the DAL total as complete. The dashboard keeps the consistent DAL definitions in both cycles and discloses the producer. It does not mix Fairfax's returned count into the statewide countable series or declare unexplained differences to be zero.

## Checks

`python3 -m unittest discover -s dashboard/tests -p test_virginia_nevada.py -v` covers timestamp interpretation and duplicate snapshot replacement. The actual collector requires all 133 localities in each successfully parsed archive, rejects unknown locality names and negative counts, preserves last-successful observations on download/parser failure, and hashes each downloaded source archive. On the October 23 refresh it produced 65,403 dated method/measure observations with no download errors.

Independent actual-archive checks also reconcile all 246 available state/date/method cumulative values exactly to the sum of the 133 locality observations. The October 23 current total is 999,477 countable. Evidence is in `verification.json`.

## Current-cycle reported precinct detail

The collector now separately extracts the producer's 2026 locality/precinct metric series to `precincts/{FIPS5}.json`, with a lightweight `precinct-daily.json` index. It preserves full native precinct code/name labels, including multiple published names sharing a code. There is no alias merge, 2024 comparison, geometry assertion or ratio. Updates replace each county shard atomically. Main county observations are unchanged.

**The precinct series currently ends September 24 morning, representing September 23**, although locality series continue through October 23. A directly fetched Fairfax precinct CSV confirms the same September 24 source timestamp as the ZIP member. No September precinct counts are carried forward to October. The index and every shard state their actual latest date separately from the requested cutoff.

Extraction produced 133 county shards, 3,747 published native labels and 130,888 daily/cumulative method observations. Each cumulative county/date/method sum was checked against the independently published locality metric. Not every precinct sum reconciles: see `precinct-verification.json` for exact dated differences and native alias counts. These are reported groups, not a claim of certified exhaustive precinct coverage; locality headline totals continue to come from locality observations. Nine parser fixture tests, including native alias separation and shard timestamps, pass.
