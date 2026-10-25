# Nevada early turnout

Coverage currently uses the official election departments of Clark and Washoe counties. Those counties are not labeled statewide Nevada. Clark supplies 2024 and 2026 observations; Washoe currently supplies 2026 observations only where a dated public report was available. Missing 2024 Washoe daily history remains unknown, so Washoe is retained in current totals and omitted only from unsupported comparisons.

## Official sources

- [Clark early-voting data](https://www.clarkcountynv.gov/government/departments/elections/reports_data_maps/early-voting-turnout-data) links dated CSV ZIPs, e.g. [2026 October 17](https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/ev_20261017.zip). The same official endpoint retains [2024 October 19](https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/ev_20241019.zip). The county explicitly describes these daily files as unaudited and subject to clerical corrections. All 14 historical 2024 dates are attempted, including future reference dates; 2026 stops at the requested date.
- [Clark mail-ballot data](https://www.clarkcountynv.gov/government/departments/elections/reports_data_maps/mb-data) links [2026 cumulative returns](https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/mbreq26GE.zip) and [2024 cumulative returns](https://elections.clarkcountynv.gov/VoterRequestsTV/EVMB/mbreq24G.zip). Receipt dates, rather than the final cumulative total, form the historical date series. The current archive also contains undeliverable records; these are explicitly excluded.
- [Washoe 2026 election reports](https://www.washoecounty.gov/voters/results/2026data.php) links dated cumulative mail and in-person CSVs. The report-table date is used as the snapshot date. An example current [in-person report](https://www.washoecounty.gov/voters/results/resultsfiles/In-Person-Turnout---Public-Consumption6.csv) includes `VOTER_REG_PARTY`, `PRECINCT` and `DATE_VOTED`.
- [Nevada SOS VIVID](https://www.nvsos.gov/vivid/) was attempted. Its response in this environment was an Incapsula challenge, not election data. It was not bypassed or interpreted as zero turnout.

## Definitions and comparison support

In-person counts are deduplicated by the source voter identifier within each report and aggregated to precinct/event date and county/event date. A complete prefix of Clark daily downloads supports cumulative in-person counts; a missing source date preserves other dates' daily reports without manufacturing a cumulative total across the gap.

Mail means **returned**, including accepted and processing/signature-pending returns. Clark's `UNDELIVERABLE` and canceled records are excluded. Washoe includes `Accepted`, `Returned`, `Signature Cure Needed`, and `Contact County Clerk`; it excludes mailed-only, canceled and surrendered-to-in-person records. A missing return date is not a returned ballot. Historical Clark mail is event-dated from a mature current file, which may reflect later corrections; it is not represented as an archived acceptance-status snapshot. The historical total is never used wholesale as the same-point baseline.

Clark's early file `PARTY`/`PARTY ABBR` describe the **ballot type**, which is NA for general elections per the [official layout](https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:bbc4713e-1412-46a5-b348-87f90d147787/original/as/evlayout.pdf). Those fields do not establish party registration. Clark mail and Washoe reports provide actual `VOTER_REG_PARTY`. Party breakdowns are emitted only where that field exists. Clark combined turnout does not inherit its mail-only partisan split.

Both methods are combined only on dates/geographies for which both are present. Precinct identifiers are retained for future geography work, but a cross-cycle precinct boundary crosswalk has not been validated; county comparisons are the supported geography. Unknown days or precincts are not filled with zero. Only geographic aggregates, actual source hashes, counts and provenance are saved. Voter names, IDs, addresses and downloaded voter files never touch disk and are never served.

## Presidential reference

Clark (Harris 520,187; Trump 493,052) and Washoe (Harris 130,071; Trump 127,443) counts come from the Nevada Secretary of State's [2024 presidential results](https://silverstateelection.nv.gov/USPresidential/index.shtml), preserved in a [UCSB archive of the official page](https://www.presidency.ucsb.edu/sites/default/files/election-maps/2024/2024_nv.pdf). Its PDF is saved content-addressed. Washoe's [official final summary](https://www.washoecounty.gov/voters/results/resultsfiles/2024generalresults.pdf) independently confirms its two candidate counts. These presidential counts classify counties; they are not early-turnout baselines.

## Checks

`python3 -m unittest discover -s dashboard/tests -p test_virginia_nevada.py -v` checks deduplication, undeliverable/pending-return handling, party-field interpretation, source-year validation, malformed precinct rejection and privacy of persisted aggregates. Actual-source coverage and county/party/precinct reconciliation are recorded in `verification.json` after the collector run.

## Independent county site control and unresolved scope

The [official Clark site-turnout table](https://elections.clarkcountynv.gov/ElectionResultsTV/evturnout.aspx) retrieved on October 24 reports October 17–23 daily totals of 14,795 / 8,388 / 13,940 / 13,460 / 12,542 / 11,499 / 14,453, cumulative 89,077. The dated precinct roster reports yield 14,791 / 8,389 / 13,929 / 13,456 / 12,417 / 11,492 / 14,451, cumulative 88,925. The cumulative gap is 152, but October 18 differs in the opposite direction by one voter. The site gives no explanatory classification for this discrepancy. Its current site summary has no documented historical-election selector; bounded historical URL probes did not establish an equivalent 2024 control. These observations do not establish whether provisional/status handling, timing or clerical correction explains the difference.

The dashboard therefore retains the consistent reported-roster series rather than claiming the 152 unexplained votes belong to any particular precinct or retroactively assigning them to a comparison. This is reported coverage, not proof every vote credit in a present precinct has arrived. The content-addressed official HTML and `clark-site-controls.json` preserve the independent check. The county-level figures may be upgraded when an equivalent historical control and matching definition are established.

Final actual-data checks: 153 method/date/measure county totals exactly equal the sum of their reported precinct counts; 54,410 published party breakdowns sum to their corresponding observations; all 115,799 observation identifiers are unique, 2026 future dates are absent, and combined Clark turnout has no inferred party breakdown. Missing source registration values are retained as counted `Unknown` registration rather than assumed zero. Eight parser fixture tests and Python compilation checks pass.
