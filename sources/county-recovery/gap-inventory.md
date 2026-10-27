# Texas county recovery inventory — October 26, 2026

Pinned snapshot: `2026-10-26T22:50:17.827075308+00:00`, Day 7 through 2026 October 25. Anonymous source caches and official publications were checked on October 26. Raw voter records, names and identifiers were processed only in memory when necessary and were not saved. No dashboard data, source collectors or running services were changed by this task.

## Main result

**33 additional counties have proven same-geography, same-day comparisons in retained sources**, giving a potential 248 county precinct universe before any unproven aliases. All 39 previously unadmitted counties now have staged geography/Census/maps/place prerequisites; an independent explicit-observation qualifier selects 17 initial counties plus 16 further counties. Six remain excluded because no native-ID common group can be paired in the retained data.

Two system defects affected the earlier admission inventory:

1. It normalized leading zeros only for entirely numeric IDs. Existing production geography, Census and map builders correctly normalize native alphanumeric IDs too: `001A` → `1A`, `01TC` → `1TC`.
2. It joined the SOS county identifier to TLC `cntykey`; those codes are not interchangeable around Mason/Martin/Matagorda/Maverick/McCulloch/McMullen. The existing geography builder correctly joins official county FIPS to TLC `CNTY`. For example, Maverick is SOS 159, TLC cntykey 162, FIPS 48323; McMullen is SOS 162, TLC cntykey 156, FIPS 48311.

The staged bundles use the existing correct production builders. Both-year normalized native IDs are collision-free, old/new geography partitions are complete, source counts conserve mapped+unlocated totals, and Census/place components reconcile. No geographic vote allocation, suffix guessing or synthetic zeros were used. VTD identifiers retain their separate normalization policy.

## All 39 previously unadmitted counties

The official county total is 2026 in-person cumulative through October 25, useful only for prioritization. Percent mapped uses each retained source cache (normally 12 historical days and 5 current days) against the correct FIPS/native-ID universe; it is not population turnout or certification of a complete report. Pair columns show independently proven cumulative groups on Days 1/5 using only explicit observations on every required date; no completed-source zero inference is used.

[Official Day 7 county aggregate](https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile?type=EVR_EARLYVOTING&electionId=53815&electionDate=10/25/2026). Source URLs, retrieval dates, hashes, unmatched labels and native universes are in [the detailed aggregate inventory](../../analysis/county-recovery/gap-inventory.json).

| County | Official IP Day 7 | Mapped 2024 / 2026 | Explicit groups Day 1 /5 | Disposition |
|---|---:|---:|---:|---|
| Johnson | 31,718 | 61.8% / 99.8% | 31 / 29 | Validated addition; retain only available per-day paired groups. |
| Guadalupe | 29,670 | 0.0% / 99.9% | 0 / 0 | Historical four-digit subprecinct labels vs three-digit native IDs; official crosswalk required. |
| Taylor | 18,035 | 0.0% / 100.0% | 0 / 0 | All 34 historical labels have a terminal period (306. vs native 0306). A reviewed county/year punctuation alias would recover them; none applied here. |
| Gregg | 14,121 | 0.0% / 0.0% | 0 / 0 | Both cycles publish detailed subprecinct codes (1202 etc.) vs 21 native parent precincts; official relationship required. |
| Henderson | 13,939 | 100.0% / 99.9% | 30 / 30 | Validated addition; retain only available per-day paired groups. |
| Hunt | 12,504 | 100.0% / 20.2% | 11 / 1 | Validated addition; retain only available per-day paired groups. |
| Liberty | 10,874 | 100.0% / 75.3% | 18 / 18 | Validated addition; retain only available per-day paired groups. |
| Bowie | 10,741 | 100.0% / 100.0% | 36 / 33 | Validated addition; retain only available per-day paired groups. |
| Medina | 9,673 | 100.0% / 99.8% | 15 / 15 | Validated addition; retain only available per-day paired groups. |
| Wood | 8,088 | 0.0% / 99.9% | 0 / 0 | Historical decimal subdivisions (11.0/11.1 etc.) vs native parent 11; official crosswalk required. |
| Van Zandt | 7,968 | 100.0% / 99.9% | 18 / 18 | Validated addition; retain only available per-day paired groups. |
| Lamar | 7,225 | 100.0% / 100.0% | 26 / 26 | Validated addition; retain only available per-day paired groups. |
| Cooke | 6,114 | 100.0% / 99.9% | 17 / 17 | Validated addition; retain only available per-day paired groups. |
| Hopkins | 5,392 | 100.0% / 7.8% | 3 / 1 | Validated addition; retain only available per-day paired groups. |
| Maverick | 5,253 | 100.0% / 100.0% | 16 / 15 | Validated addition; retain only available per-day paired groups. |
| Aransas | 4,757 | 100.0% / 100.0% | 1 / 1 | Validated addition; retain only available per-day paired groups. |
| Matagorda | 4,710 | 100.0% / 100.0% | 18 / 18 | Validated addition; retain only available per-day paired groups. |
| Cass | 4,397 | 100.0% / 100.0% | 18 / 18 | Validated addition; retain only available per-day paired groups. |
| Gonzales | 3,151 | 90.2% / 99.9% | 13 / 13 | Validated addition; retain only available per-day paired groups. |
| Shelby | 2,669 | 100.0% / 96.2% | 13 / 13 | Validated addition; retain only available per-day paired groups. |
| Somervell | 1,932 | 100.0% / 93.5% | 4 / 4 | Validated addition; retain only available per-day paired groups. |
| Red River | 1,797 | 100.0% / 99.9% | 20 / 19 | Validated addition; retain only available per-day paired groups. |
| Coleman | 1,565 | 100.0% / 100.0% | 3 / 3 | Validated addition; retain only available per-day paired groups. |
| Zavala | 1,441 | 100.0% / 100.0% | 6 / 6 | Validated addition; retain only available per-day paired groups. |
| Zapata | 1,184 | 99.8% / 100.0% | 5 / 5 | Validated addition; retain only available per-day paired groups. |
| Mason | 1,016 | 100.0% / 100.0% | 4 / 4 | Validated addition; retain only available per-day paired groups. |
| Dimmit | 1,009 | 68.4% / 100.0% | 7 / 6 | Validated addition; retain only available per-day paired groups. |
| Mcculloch | 1,001 | 100.0% / 100.0% | 9 / 8 | Validated addition; retain only available per-day paired groups. |
| Ward | 925 | 100.0% / 100.0% | 8 / 6 | Validated addition; retain only available per-day paired groups. |
| Refugio | 918 | 100.0% / 100.0% | 9 / 8 | Validated addition; retain only available per-day paired groups. |
| Culberson | 475 | 100.0% / 100.0% | 5 / 4 | Validated addition; retain only available per-day paired groups. |
| Martin | 450 | 100.0% / 100.0% | 5 / 4 | Validated addition; retain only available per-day paired groups. |
| Upton | 373 | 100.0% / 0.0% | 0 / 0 | Current 1–7 labels differ from native map labels; need official 2026 map/precinct relationship. |
| Roberts | 143 | 100.0% / 100.0% | 4 / 4 | Validated addition; retain only available per-day paired groups. |
| Hudspeth | 121 | 100.0% / 97.3% | 6 / 1 | Validated addition; retain only available per-day paired groups. |
| Borden | 111 | 100.0% / 100.0% | 3 / 3 | Validated addition; retain only available per-day paired groups. |
| Hill | — | 100.0% / 0.0% | 0 / 0 | Retained current reports have only 4 positive unlocated observations across 3 days; county-native current source needed. |
| San Saba | — | 100.0% / 100.0% | 6 / 0 | Validated addition; retain only available per-day paired groups. |
| McMullen | — | 100.0% / 100.0% | 4 / 3 | Validated addition; retain only available per-day paired groups. |

A county is not excluded merely because some source labels are unlocated or a particular date lacks a comparison. Johnson, Hunt and other partial counties retain every verifiable common group. A documented alias/crosswalk can enlarge those comparisons later. Countywide percentage thresholds are not used for admission.

Taylor’s terminal-period candidate maps all 34 historical IDs uniquely to existing native IDs and 100% of its retained historical votes. Hunt’s terminal-dash candidate maps 99.842% of retained current votes, but Hunt already qualifies on an exact-ID subset. These diagnostics are recorded separately; neither formatting transformation was applied to product data or qualification. Guadalupe/Gregg/Wood require source-supported subdivision relationships, not numeric truncation or spatial allocation.

## Existing admitted counties with no Day 7 cumulative pair

Of 23 wholly missing counties, this task investigates 16. Dallas, Montgomery, Navarro, San Patricio, Starr, Waller and Washington are owned by the parent/parallel county-source task. Thus the accounting is 215 previously admitted plus 39 not admitted equals 254 Texas counties.

Fresh official SOS checks for 20 missing county/date observations returned empty HTTP 200 responses or no in-person rows. Five available-date checks reproduced the stored tiny-day counts. Empty responses and omitted precinct rows cannot prove zeros.

| County | Missing 2026 daily sources | Finding |
|---|---|---|
| Dawson | 10-23 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Freestone | 10-24, 10-25 | Both weekend SOS responses empty; county schedules voting both days and publishes scanned reports. Not a closed-weekend zero. |
| Garza | 10-24 | Saturday CSV has no IP rows; official schedule opens October 24 7 am–7 pm. Publication gap, not confirmed zero. |
| Hall | 10-21 | Oct 21 SOS response empty; county workbook contains 34 explicitOct 21 rows but uses S 202.13-style subdivisions requiring verified aliases. |
| Hardeman | None | All 7 files exist. Different tiny-day precinct sets have no all-day intersection; omitted-row zeros lack independent certification. |
| Haskell | 10-24, 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Kent | None | All 7 files exist. Different tiny-day precinct sets have no all-day intersection; omitted-row zeros lack independent certification. |
| Kimble | 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| King | 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Loving | 10-24, 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Panola | 10-20, 10-21 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Rains | 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Real | 10-24, 10-25 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |
| Stonewall | None | All 7 files exist. Different tiny-day precinct sets have no all-day intersection; omitted-row zeros lack independent certification. |
| Swisher | 10-23 | Oct 23 no IP rows. One native precinct also lacks a fully known historical cumulative observation. |
| Winkler | 10-20, 10-22, 10-23 | Missing official observation persists in fresh SOS request. Obtain a dated county-native source/control; do not backfill zero. |

Hardeman demonstrates cumulative coverage loss without a download failure: Saturday reports precincts 2/4, Sunday precinct 1. Until omitted-row zeros are independently established, no precinct has known counts on every day. Kent and Stonewall have the same changing tiny-day membership issue. County-level totals are a separate geography and do not authorize allocating votes among missing precincts.

## County-native publication checks

- [Hall elections](https://www.co.hall.tx.us/page/hall.County.Elections) links the [October 21 workbook](https://www.co.hall.tx.us/upload/page/9609/10202126%20VOTER%20HISTORY.xlsx). Its worksheet title is an old October 19 template, but 34 usable rows have explicit October 21 timestamps and unique state identifiers. The analogous October 20 file has 50 rows, matching retained SOS total 50. All polling locations are the county annex. The `Precinct` field uses `S202.13`-style subdivisions; these counts remain diagnostic until that relationship is documented. The linked October 19 file returns 404. Only anonymous aggregates and file hashes were retained.
- [Freestone elections](https://www.co.freestone.tx.us/page/Freestone.Elections) explicitly schedules October 24/25 voting at Green Barn. Its [Saturday PDF](https://www.co.freestone.tx.us/upload/page/1902/VH%2010%2024%202026%20SATURDAY0001.pdf) has 7 scanned pages; the [Sunday-linked PDF](https://www.co.freestone.tx.us/upload/page/1902/10%2024%202026%20SUNDAY0001.pdf) has 5. Both lack usable text layers. The Sunday filename also says October 24, so date, scope and precinct fields need OCR/visual validation before admission. Neither file nor voter rows were saved.
- [Garza elections](https://www.garzacounty.gov/page/elections) links a [scanned official schedule](https://www.garzacounty.gov/page/open/1683/0/2026%20November%20General%20Election.pdf). In-memory OCR reads October 24 7 am–7 pm and October 25 9 am–3 pm. Therefore Saturday’s missing in-person observation cannot be filled as a closed-day zero. No independent county control was acquired to certify absent precinct rows.

## Reproducible staged bundles

[build_admission_bundle.py](build_admission_bundle.py) imports the unchanged original builders, points them at an isolated mirror and runs offline. All Census block-point inputs were already retained from the statewide place job; GDAL and the pinned GeoPandas stack were available. The initial 17 bundle is immutable after acceptance. The first validation attempt had an adapter-only `.json`/`.geojson` filename error; the corrected final run passed.

- `analysis/county-recovery/admission/`: initial 17 counties;255 native precincts,243 common groups, merged reference/Census/primary 232 county objects; original 215 objects preserved.
- `analysis/county-recovery/admission-additional/`: all 22 remaining candidates built offline. Its unfiltered project reference contains ineligible candidates and must not replace production.
- `analysis/county-recovery/admission-additional/qualified/`: **16 eligible additional counties only**,243 native precincts,219 common groups, additive reference/Census/primary/place objects.
- `analysis/county-recovery/admission-additional/baseline17-proof/qualified/qualification.json`: independently proves eligibility of all 17 accepted counties without changing their bundle.
- [qualify_admission_bundle.py](qualify_admission_bundle.py): explicit-source-only daily/cumulative proof with source hashes; requires at least one cumulative common group with positive historical baseline. It never interprets unknown positive source labels as native zero observations.

Across the 33 additions, this conservative cached-source proof establishes 418 native precincts in 392 cumulative common groups onDay 1, and 375 precincts in 354 groups onDay 5. This is a lower bound before legitimate independently verified zeros or later source updates. Their current caches cover only the first 5 dates, soDay 6/7 absence in this staged proof is a collector-history gap to refresh after integration, not a claim that voting stopped.

Copy only eligible county geography directories/maps and merge additive objects into the parent’s current datasets. Preserve existing counties. Staged logical provenance for new Census points uses `sources/census-atlas/raw/{county}-block-points.json`; those are readonly file symlinks to retained official inputs and can be dereferenced/copied or remapped to equivalent original paths with the same hashes. Do not recursively copy large readonly source-directory symlinks.

Integration, per-day API reconciliation, current source refresh and deployment remain with the parent task. These staged results do not claim live publication or resolution of every missing county/date.

## Admission diagnostic repair

The existing [precinct ID diagnostic](../precinct-expansion/discovery/audit_precinct_ids.py) is now corrected in both projects. It joins native geometry by official FIPS/CNTY, applies the existing native alphanumeric padding rule, and rejects duplicate normalized precinct identities instead of merging them. VTD labels and observed source identifiers are unchanged. Empty observed totals have undefined coverage. Its original CLI/output defaults remain; an optional `--output` directs diagnostics into isolated analysis.

The original script was backed up and SHA256-pinned before replacement. Nine [focused tests](../../dashboard/tests/test_precinct_id_audit.py) passed, including Henderson, Maverick/McMullen, collisions, unchanged unknown labels and isolated writes. Actual anonymous aggregate runs passed for all 244 discovery counties and the 32-county default probe. Both script copies are byte-identical. Evidence is in `analysis/county-recovery/admission-audit-fix/verification.json`; no source caches, dashboard datasets or services were changed. The maximum proven county universe remains **248**.


## Integrated seven-day edition

After refreshing the 33 eligible additions through October 25 with the real SOS collector and repairing Dallas, Montgomery, Waller, Washington and San Patricio, the accepted native/API snapshot has **248 supported counties and 226 counties with a Day 7 cumulative matched comparison**, up from 215 and 192 respectively. The five-day staging figures above describe eligibility before that refresh, not the final displayed availability. Dallas now has 535 current precincts in 490 paired groups; two ambiguous dated precinct cells remain withheld. Montgomery retains 119 current precincts, Waller 18, Washington 16 and San Patricio 9 on the latest matched cutoff. These are supported subsets of each county, never substitutes for full-county totals.

The 22 supported counties without a Day 7 cumulative paired observation are Dawson, Freestone, Garza, Hall, Hardeman, Haskell, Kent, Kimble, King, Loving, Navarro, Panola, Rains, Real, Starr, Stonewall, Swisher, Winkler, Maverick, Hudspeth, San Saba and McMullen. Earlier supported days remain available individually. Six counties—Guadalupe, Taylor, Gregg, Wood, Hill and Upton—still lack a proved native-ID comparison and are not admitted to precinct analysis. All 254 remain within the separate county-level workspace where official paired county observations permit.

Independent reconstruction passed every seven-day county/group sum, 617,796 demographic point comparisons and the exposed OLS fits. Native and actual Pages-subpath browser checks passed all 33 maps/Census/place joins, recovered/latest and representative partial county selections, linked selection, real PNGs, both matrix measures, race guards and responsive layouts. Publication is the parent's remaining integration step.
