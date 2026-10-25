# Georgia early-vote coverage

The [Georgia Secretary of State's unofficial turnout hub](https://sos.ga.gov/page/election-data-hub-unofficial-turnout) embeds its [public Qlik application](https://d11khjvhu86vzz.cloudfront.net/DH.ELECTION2024/index.html). The [host configuration](https://d11khjvhu86vzz.cloudfront.net/shared-config.js) and [application configuration](https://d11khjvhu86vzz.cloudfront.net/DH.ELECTION2024/js/vars.js) identify the official tenant and current app. The collector discovers these on each run rather than relying on an old app ID.

The app exposes county, ballot acceptance date, ballot style, race, age and sex. It does not expose a precinct dimension. All 159 counties are supported, with daily and cumulative accepted-ballot series for the 2024 and 2026 general elections. Race/age/sex are actual official voter aggregate categories, not Census estimates of who voted. General-election ballot styles do not identify a voter's political party; this data does not establish 2026 primary participation among current general-election voters.

The [official app's chart definitions](https://d11khjvhu86vzz.cloudfront.net/DH.ELECTION2024/index.html) use accepted ballots, including `ExtraBallotCounter`. The collector uses `SUM(Ballots_Accepted_Counter)+SUM(ExtraBallotCounter)` grouped by county, `Ballot Accepted Date`, ballot style, and one demographic dimension at a time. It requests only public aggregate cubes. The app's ordinary anonymous read session is opened with its public token endpoint, with credentials retained only in memory. No voter records, names, registration IDs, addresses or birth dates are requested or written to disk.

In-person and mail are separate methods. Mail combines the native `Absentee by mail` and `Electronic Ballot Delivery` styles. Requested, issued, outstanding, rejected and Election Day ballots are excluded. Dates mean ballot acceptance dates, not download dates. The SOS warns that county officials continue uploading credit and reconciling after Election Day, so historical daily counts can be revised. These are reported ballots, not a certification that every county has finished every upload.

The official advance-voting openings are October 13, 2026 and October 15, 2024 ([2026 Georgia.gov event](https://georgia.gov/events/2026-10-13/general-election-early-voting), [2024 SOS first-day report](https://sos.ga.gov/news/georgia-voters-smash-records-first-day-early-voting)). The dashboard aligns calendar days since each cycle's in-person opening. Day 1 cumulative includes accepted mail from before that opening. Full 2024 pre-election history is retained for future baseline days. Current-cycle observations end at the requested date or the last dated source observation, whichever is earlier.

The full county/date cubes suppress zero cells. Known zero categories are explicitly materialized inside observed coverage, including counties with no ballots on a particular day. Every demographic cube must reconcile exactly to its base cube, and every county/date/method demographic sum must equal the corresponding total. A source reload during extraction rejects the mixed snapshot and preserves the prior normalized output.

The 2024 source contains malformed dates such as years 1924, 1951 and 2224, plus a small number of dates outside the general-election window. Those records are not assigned to a guessed date. In-person observations must be between the official opening and the day before Election Day; mail acceptance must fall in the 60 days before Election Day. Unknown/out-of-window dates are excluded from dated curves. Raw aggregate responses remain archived so exclusions can be audited.

Native `Other/Unknown` race is a combined category. It must remain unknown when constructing total non-white; subtracting White from all voters would falsely classify unknown race. The native null race is retained as `Unknown`. The official app displays age labels `35-40`, `40-45`, etc. as `35-39`, `40-44`, etc.; the collector follows that display convention and preserves `18-24`, `25-29`, `30-34`, and `100+`.

County partisanship uses the [SOS certified 2024 presidential county returns](https://results.sos.ga.gov/results/public/api/elections/Georgia/2024NovGen/data/ballot-item/01000000-d884-2e72-6367-08dcda4b86b5), not an estimate of current voters' preferences. All 159 county Harris/Trump counts must sum to the official statewide 2,548,017 Harris and 2,663,117 Trump totals. Stable county FIPS identifiers come from the [Census official county code file](https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt).

## Refresh and verification

`python3 dashboard/scripts/states/georgia.py --through 2026-10-23`

`python3 -m unittest dashboard/tests/test_georgia.py -v`

Raw aggregate source responses, source configurations, official county returns and Census codes are preserved under `sources/multistate/ga/raw/` using content-addressed names. The normalized file records source URLs, retrieval timestamps, SHA-256 hashes, query dimensions and expressions. A failed refresh leaves `dashboard/data/states/ga.json` intact.

## Verified snapshot

The successful collector run produced 30,528 normalized observations: 159 counties × three methods × two measures × (21 historical + 11 current calendar days). The official app reload was `2026-10-24T22:33:11.218Z`. Source cubes contain 5,295,967 accepted ballots for the historical election across all methods/dates and 1,701,400 for the current election including October 24; the dashboard cuts current observations to October 23 and excludes Election Day methods.

| Matched calendar point | Total | In person | Mail |
| --- | ---: | ---: | ---: |
| 2026-10-23, Day 11 | 1,634,797 | 1,555,492 | 79,305 |
| 2024-10-25, Day 11 | 2,635,632 | 2,460,878 | 174,754 |
| 2024-11-04, future baseline | 4,038,361 | 3,768,089 | 270,272 |

Date validation excludes 25 historical and seven current accepted-ballot counts with malformed/out-of-window dates, with no reassignment. The full aggregate date exclusions and verified totals are in `verification.json`. Four tests passed, including actual raw-source, county-return, demographic-sum, method-sum and cumulative-prefix reconciliation.

## Dashboard headline

Georgia defaults to statewide voter race, with Age and Sex alongside it. These curves sum the SOS accepted-ballot demographic categories across the matched reporting counties independently for each date and daily/cumulative measure; they do not estimate voter race from county composition. Each native demographic partition reconciles to statewide turnout. Unknown and Other/Unknown remain published categories. County demographic composition is a separate Census view. Explicit method, measure, date and classification links still select their requested view.
