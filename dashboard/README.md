# Texas early vote

Rust scraper, analysis, scheduler and HTTP server. The Counties workspace compares official turnout by partisan and demographic county buckets across all 254 Texas counties. The Precincts workspace retains maps and Census data for 215 counties; turnout comparisons match the available precinct geography at each cutoff. It has Trends for daily buckets and cross-county comparisons and Explore for linked maps, regressions and precinct detail.

```bash
./dashboard/run.sh
```

Open **http://127.0.0.1:8741**. It starts with the saved snapshot and checks official sources immediately, then every hour while running. The browser reloads data once an hour; after a manual refresh, it checks completion only until that requested refresh finishes. Stop with Ctrl+C. No machine-wide service is installed.

The default cutoff is yesterday in America/Chicago, capped at October 30, 2026. Equivalent calendar days are compared from October 19, 2026 and October 21, 2024. Partial current-day voting is excluded. Day controls select cumulative periods. Ellis combines exact-cutoff native cumulative workbooks with independently dated SOS daily reports; later cumulative totals are never allocated backward.

```bash
# One refresh, including new PNG/SVG/CSV exports
cargo run --locked --manifest-path dashboard/Cargo.toml -- refresh --through 2026-10-22

# Saved data only, without background requests (manual Refresh still requests sources)
./dashboard/run.sh --offline

# Different port / interval
TURNOUT_REFRESH_SECONDS=3600 ./dashboard/run.sh --port 8750

# Recheck cached 2024 sources as well as current sources
./dashboard/run.sh --recheck-history
```

Requires Rust/Cargo, `uv`, and `/usr/bin/chromium` (all present on the development machine). `uv` supplies Python transport/render dependencies. Public county sources protected by browser TLS use `curl-cffi`; Dallas additionally requires a temporary Playwright browser challenge. Python transports return bytes through process pipes; current source parsing, voter deduplication, county aggregation, geography matching, scheduling and APIs run in Rust. A memory-only streaming helper builds the immutable 2024 Dallas baseline from its large county workbook, using the county’s unique identifier and independently reconciled daily controls. Plotting uses Matplotlib and installed Nimbus Sans fonts. No API keys or paid scraping service are needed.

`data/reference.json` freezes the prior project's presidential votes and qualified geographic crosswalks, with original file hashes. `data/cache/` contains precinct aggregates only. Historical aggregates are cached; current county sources are fetched anew on each refresh. `data/snapshots/` preserves timestamped aggregate snapshots, and `data/latest.json` is replaced atomically. The latest snapshot includes source hashes, retrieval dates, scope and audit caveats. Voter names, IDs and original rosters are never written to disk or logs.

New images and accessible CSV exports go in `../analysis/updated-through-YYYY-MM-DD/`; each directory contains the aggregate snapshot used for its figures. Existing day-one outputs remain untouched. Native downloads have a 120-second deadline (20 seconds to connect); transient header/body failures and HTTP 5xx server errors retry once, then use the compatible transport. Permanent HTTP errors such as 404 remain failures. A stalled or truncated body is never accepted as a successful download. A failed county download retains its last successful periods and marks them stale; missing dates, mail-only exports and unsupported format changes cannot become valid zero turnout. No arbitrary precinct-label repair or area allocation is performed.

Source selection and October 23 controls are documented in [county A](../sources/refresh-2026-10-23/county-a/findings.md), [county B](../sources/refresh-2026-10-23/county-b/findings.md), and [county C](../sources/refresh-2026-10-23/county-c/findings.md). Some county/state discrepancies remain, including Bell's broader county total and Madison's differing rosters; these are visible under Sources & method. TLC 2026-primary maps remain a proxy for November geography.

```bash
cargo test --locked --manifest-path dashboard/Cargo.toml
cargo clippy --locked --manifest-path dashboard/Cargo.toml -- -D warnings
python dashboard/scripts/verify_refresh.py  # independent four-day source audit
uv run --with playwright python dashboard/tests/browser.py  # running local server
```

The regression chart follows the county, cumulative-day and cohort selectors. Harris vote share is the 2024 two-party share; turnout is cumulative 2026 in-person votes as a percentage of the same early-voting day in 2024. Rust computes an unweighted OLS fit with an intercept, one observation per comparable geographic group. Groups with zero 2024 baseline are omitted; zero current votes and all eligible outliers remain. The line spans observed vote shares; no line is fitted for fewer than two observations or a constant predictor. R² is undefined for a constant response. All-county fits pool groups without county adjustment; use the county selector for within-county comparisons. Points CSV exports the plotted observations. This is descriptive, with no significance or causal claim.

Regression verification (running server):

```bash
uv run --with playwright==1.64.1 python dashboard/tests/regression.py
```

This independently recomputes every exposed county/day/cohort fit, then checks chart points, selectors, CSV, empty states and desktop/mobile layout. Use `TURNOUT_TEST_URL` for a different local port.

The regression chart is divided at 50% Harris share and 100% of 2024 turnout. Each quadrant has a matching tint and dot color: blue (Harris side, at/above 2024), teal (Harris side, below 2024), red (Trump side, at/above 2024), ochre (Trump side, below 2024). Exact divider values use the ≥ side. The pooled OLS fit and all observations are unchanged.


The map/scatter workspace follows the compact analytical presentation documented in [DESIGN.md](DESIGN.md), inspired by VoteHub. Click a chart point to zoom to every current precinct in its comparable geographic group; map clicks select a native precinct and the matching chart point. Hover links the views. Arrow keys navigate chart points; Enter selects. Bucket cells emphasize the matching map areas and observations while leaving the fitted cohort unchanged. Precinct search, sorting, CSV exports, cumulative trend lines, a turnout map layer and reduced-motion support are included.

The county selector inside Precincts filters its timelines, regression and bucket matrix. County workspace filters are independent. Explore opens on a Texas county overview alongside the all-precinct regression. The map selector and precinct county selector share one geographic scope: selecting a county, including by clicking a regression point, shows that county’s precincts and a regression fitted only to that county. All Texas returns both views to the statewide scope; Clear selection keeps the selected county. Clear selection / Reset returns to the full county. Partisan / Demographic switches the analytical denominator; the latter provides Total non-white, Hispanic, Black, Asian and White non-Hispanic shares of residents age 18+, plus the share under 18. Twenty-point demographic buckets divide summed 2026 votes by summed comparable 2024 votes. Demographic matched cohorts include all common geographic groups, including groups excluded from partisan views for mixed margin bands. Unchanged retains the existing strict unchanged flag.

Maps derive from the Texas Legislative Council 2026-primary shapefile, a proxy for November boundaries. Native precincts retain stable IDs and map to the existing common geographic groups. Historical turnout and presidential values belong to those groups; native map selections explicitly label shared historical comparisons. Native 2026 turnout and native Census counts are shown where available. No votes are apportioned to polygons. Locally vendored Leaflet 1.9.4 is MIT licensed; no external map tiles or runtime account are required.

Census profiles use official **2020 Census PL 94-171** block counts published by the Texas Legislative Council, assigned whole to 2026-primary precinct polygons by the Census block internal point. These are block-point precinct estimates, not current population or voter demographics. The original nine counties assign86,608 blocks and5,623,910 residents; the expansion adds511,995 blocks and21,912,897 residents, with all county measures reconciled to official totals. Precincts with zero2020 population retain undefined composition. Split blocks are assigned whole. Black and Asian include combinations and may overlap Hispanic; White non-Hispanic is White alone, not Hispanic. The separate composition bars must not be read as additive. VAP is residents age 18+, not citizen voting-age population. No ACS income or education estimates are imputed.

Sources and reproducible transformations:

- [Map audit](../sources/map-atlas/findings.md), `data/maps/*.geojson`, `scripts/build_maps.py`.
- [Census sources and validation](../sources/census-atlas/findings.md), `data/demographics.json`, `scripts/build_demographics.py`.
- `/api/map/{county}`, `/api/demographics`, and `/api/demographic-view?day=4&cohort=matched&metric=hispanic_vap` expose geometry, resident counts, and computed demographic views. The last endpoint returns all county scopes plus `all`, with coverage exclusions and OLS summaries.

Census and map inputs are fixed vintages; turnout and all derived views update with the existing scraper. To rebuild the fixed geographic/Census assets from the preserved sources:

```bash
uv run dashboard/scripts/build_maps.py
uv run dashboard/scripts/build_demographics.py
```

Additional acceptance checks against a running server:

```bash
TURNOUT_TEST_URL=http://127.0.0.1:8741 python dashboard/tests/verify_demographics.py
TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright python dashboard/tests/atlas.py
```

The independent audit checks 480 demographic views, 2,400 bins and all available map links (8,950 in the expanded215-county snapshot). Browser acceptance covers linked zoom and hover, group/native profiles, all six metrics, buckets, exports, missing cutoffs and responsive geometry. Evidence lives in `../sources/census-atlas/integration-audit.json` and `../analysis/updated-through-2026-10-22/qa/atlas-browser-verification.json`.


Total non-white is the complement of White alone, not Hispanic: `non_white = population - white_nh` and `non_white_vap = vap - white_nh_vap`. The selectable metric uses age 18+ and the existing twenty-point demographic buckets; its group share is formed from summed counts. It includes Hispanic residents of any race and avoids adding overlapping race/ethnicity categories. It is available in the map, regression, bucket table, precinct profile and CSV exports.

Demographic scatterplots color observations by the group's 2024 two-party winner: Harris blue, Trump red, ties or missing presidential votes gray. These colors depend on presidential votes rather than demographic share or turnout. A compact party key replaces quadrant washes; neutral 50% share and 100% turnout reference lines remain. Partisan-mode quadrant colors retain their existing behavior. Demographic Points CSV includes both the chosen population share and the Harris two-party share.


Demographic and primary regression views offer **All / Trump / Harris**2024winner cohorts. Candidate-only choices use complete presidential returns on the matched geographic group, excluding ties and unknowns. Each choice recalculates the plotted points, OLS fit, sample size, automatic range and Points CSV. PNG captions identify the selected cohort. County demographic regressions use the equivalent county winner. The choice affects the regression; county/precinct bucket totals and maps retain their own scopes.

Turnout regressions default to **Auto** vertical scaling across Texas precinct and added-state county views. With at least five points, a shared viewport rule uses Tukey 1.5 interquartile-range fences (with a one-percentage-point spread floor) to identify the central cluster, then adds padding, a minimum span and readable ticks. Smaller samples retain their full observed range. The percentage-share x axis stays at0–100%. **Full range** reveals all points; Texas also retains its optional60–150% band. A compact count marks observations outside the current view. Every eligible observation remains in OLS, sample size and Points CSV; this is a viewport rule, not an outlier exclusion from analysis. Keyboard navigation visits visible points. Changing the scale preserves selection, colors and the fitted cohort. The100% reference and quadrant backgrounds are clipped to the current domain.


Ellis downloads the official dated SOS in-person reports for completed days, retaining each successful daily report alongside its replaceable native cumulative workbook. These recover earlier cutoffs that the rotating workbook cannot supply. A failed individual download does not discard the other observations. Each county workbook keeps its actual filename cutoff. When it advances beyond the requested completed day, the refresh retains previously verified snapshots through that exact requested date (with original retrieval timestamps and hashes). A fresh correction wins for its own date. The later total is saved for later cutoffs, and never allocated backward to reconstruct missing days. An unavailable exact cutoff remains unavailable, and a genuinely failed download still retains last-good data with a stale warning.


The Travis current-election adapter discovers the roster ZIP from the official election page on each refresh. It accepts only the county's HTTPS uploads path and the matching election-year roster ZIP, including renamed versions such as `G26-Voter-Rosters-1.zip`. Workbook dates, headers, ordinary early-vote scope and voter deduplication are still checked after download. The selected URL and content hash are preserved in source provenance; a guessed filename or a genuine 404 cannot be accepted as current data.


An opt-in live-source regression check verifies the three sources implicated in the October 24 moved-link/gateway incident. It uses only in-memory rosters and prints aggregate counts/provenance:

```bash
cargo test --locked --manifest-path dashboard/Cargo.toml --test source_recovery -- --ignored --nocapture
```

After a calendar rollover, a completed voting day can still lack a published precinct export. The dashboard keeps the county's last verified periods and marks the newest comparison unavailable; it never converts an empty response or missing daily ZIP into zero turnout. Earlier day controls remain usable. Source HTTP retries cannot create an unposted report.


Daily tracking compares the same geographic groups across all twelve early-voting days. Select **Daily** or **Cumulative** above the small multiples; the day controls mark the selected comparison cutoff without hiding the later historical trajectory. The 2024 baseline extends through November 1 where verified reports exist. Dates after the completed 2026 cutoff remain null, not forecasts. Hover or keyboard-focus a day for exact paired dates, counts and retention; Daily CSV includes all twelve dates and both measures.

Partisan, Primary and Demographic switches apply to the maps, regressions, bucket matrix and daily charts. Primary uses each group's share of **2026 Democratic primary ballots / (Democratic + Republican primary ballots)**, formed from summed native precinct ballot counts. These are explicit actual ballots cast, never a candidate-vote proxy. Missing party counts, missing precinct matches and zero combined participation remain unclassified. The fixed-vintage source builder and county coverage are documented in [primary participation](../sources/primary-participation/findings.md). Primary and demographic regression dots retain 2024 presidential winner colors. The versioned March evidence in `primary/2026.json` takes precedence over an older retained turnout cache in the native API, daily analyzer and Pages exporter. Rebuilding `scripts/build_primary.py` writes both that edition and the legacy data file; November turnout continues to refresh hourly against this fixed classification. The edition covers 4,351 native precincts across eleven counties, including the added Bexar, Collin, Denton, Harris and Tarrant. Missing precincts remain unclassified; Collin’s 26 unlocated ballots are disclosed and unallocated.

Each daily or cumulative point uses the largest available matched geographic subset for that date and measure. The same precincts appear on both sides of each2026/2024point, while membership can change between points. A missing latest report does not erase earlier observations or other precincts in its county. Historical future-day values remain a baseline; future2026 values remain blank.

The precinct bucket panel offers **By county** and **Demographic × partisan** layouts. The latter opens with Hispanic composition and has its own Census metric selector; it follows the existing county, day and matched/unchanged controls. Rows are the metric's existing demographic buckets and columns are the six established presidential-margin bands plus **Tied / unknown**. Rust computes each joint cell from the same available comparison groups, summing votes before taking the ratio. Partisan columns use the combined 2024 Harris–Trump margin of each compared common geography, including groups whose individual old precincts span different bands. Complete returns for every old member are required; no votes are spatially allocated. Tied, zero-vote or missing presidential returns stay visible in their own column, so row, column and overall totals conserve the complete demographic view. Missing/invalid/zero-population Census observations stay excluded; zero 2024 turnout makes a ratio undefined without discarding reported 2026 votes. These are geographic associations, not individual voter demographics. Joint cells use a saturated orange-to-white-to-teal scale centered on 100% of 2024 turnout, reaching full color at 70% and 130%; text switches to white on dark fills for at least 4.5:1 contrast. Cells expose their vote totals and group counts on hover or keyboard focus. CSV contains the joint cells without duplicate marginal rows; PNG and panel collapsing use the existing matrix controls.

The **Texas counties** section retains all 254 counties, including counties without precinct detail, and defaults to Mail + in person. Search, sort or select a county to compare daily/cumulative trajectories. Each point matches its own available counties in both years. A current SOS daily in-person zero cannot certify that date's cumulative total: the feed can repeat yesterday's positive count. Both remain unavailable unless a dated independent control restores them. County totals have a broader reporting scope than some ordinary-precinct series and are never merged into synthetic precinct buckets.

New public aggregate endpoints:

- `/api/trends?county=all&cohort=matched&view=partisan&metric=partisan`
- `/api/trends?county=dallas&cohort=matched&view=primary&metric=primary_dem_share`
- `/api/trends?county=all&cohort=matched&view=demographic&metric=non_white_vap`
- `/api/primary` and `/api/demographic-view?day=5&cohort=matched&view=primary&metric=primary_dem_share`
- `/api/statewide`

Refresh updates precinct and statewide sources independently, then fills missing historical baseline reports. Immutable 2024 aggregate reports are reused. Statewide last-good caches survive individual source failures. All caches contain public aggregates and provenance; no voter identities are persisted. See [daily tracking](../sources/daily-tracking/findings.md) and [statewide tracking](../sources/statewide-tracking/findings.md).

Verification for the new views (against a running server):

```bash
TURNOUT_TEST_URL=http://127.0.0.1:8741 python dashboard/tests/verify_trends.py
TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright python dashboard/tests/tracking.py
```


Each major dashboard panel has a keyboard-accessible chevron to collapse or expand it. **Collapse all / Expand all** controls sit beside the completed-day selector and act on panels in the current view. Collapsed panels are remembered in this browser; live refreshes keep that layout. Expanding the map preserves its current camera, including after a bulk collapse.

Use **PNG ↓** beside a visual to download a **1600 × 1000 PNG**. Downloads include the current view, county/precinct scope, voting period where relevant, legends and compact source/coverage notes. Each daily bucket has its own download; the daily overview, map, regression, selected-precinct profile, Census composition, precinct trend, bucket matrix/bars, precinct table, county table and county trend can also be exported. Expand a panel before exporting its contents.

Polygon hover in **Precincts → Explore** shows the native precinct's in-person count and Census composition, paired 2024/2026 group counts and turnout ratio, complete 2024 presidential shares, and aligned comparison dates. Multi-precinct comparisons are labeled as group totals; those totals are never assigned to the hovered native precinct. Missing comparisons and incomplete presidential returns remain unknown. The card follows the pointer within the viewport and is also available by keyboard: Tab enters the map, arrow keys move through polygons, Enter selects, and Escape dismisses. Clicking/tapping still opens the existing detailed profile.

The map image retains the displayed extent and highlights. The bucket matrix includes every column even when scrolled on a phone. Table images include the **first twelve rows** in the current filter/sort order (on the current page for precincts), with the limit noted in the image; CSV remains available for complete tables. Census-only images use their population vintage rather than a turnout cutoff. Exports render entirely in the browser, with no new package, upload or social-account connection. Chromium is the verified browser. Blocking local storage does not prevent folding panels; it only prevents remembering the layout.

Image/panel acceptance checks against the running dashboard:

```bash
TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright --with pillow python dashboard/tests/visuals.py
```

The check uses the installed Tesseract OCR tool, downloads all seventeen original visuals across their workspaces, validates actual PNG dimensions and data pixels, uses OCR to check the last Census/table rows and selected filters, checks map camera/fragment preservation, and exercises keyboard folds, reload persistence and desktop/tablet/mobile layouts. Evidence is saved in `../analysis/social-images/qa/`.


Counties opens by default. Choose Partisanship or Demographics, then a measure; the six Census options include Total non-white. Timelines show all 12 aligned calendar days, including actual 2024 future-day values and blank future 2026 values. The cumulative comparison below uses the selected completed day. Click a bucket to filter county records and its aggregate trend; click a county to inspect its own daily/cumulative history. Counties with precinct data offer a Precincts button that opens Explore at that county. Precinct classification, county and cohort choices persist independently while switching workspaces. Direct local links: `/#counties`, `/#precinct-trends`, `/#precinct-explore`.

County buckets classify whole counties using actual 2024 presidential Harris–Trump margins or direct 2020 Census county population counts. They do not classify people who voted. Each bucket divides summed 2026 votes by summed 2024 votes, never averages county turnout ratios. Daily and cumulative county membership is matched independently at each date, requiring paired values only for that point. Counties missing daily reports can remain in cumulative comparisons. Valid native cumulative figures remain independent of daily figures. Unconfirmed current mail zeros and unconfirmed in-person zero reports with stale cumulative values remain unavailable at that date. All254 counties remain searchable with their official selected-day totals even without a selected-day paired comparison. County and precinct reporting scopes are kept separate.

The new county analyzer is `/api/county-buckets?day=5&view=partisan&metric=presidential_margin` or `/api/county-buckets?day=5&view=demographic&metric=non_white_vap`. Responses expose bucket series, separate membership IDs/counts, omitted-county reasons, county rows and source provenance. `data/county-reference.json` is rebuilt with `python dashboard/scripts/build_county_reference.py --offline`; add `--verify-blocks` to reconcile all 254 counties against the retained668,757 Census blocks. The official presidential host returned403; the retained primary governmentJSON came from a pinned preservation mirror with a matching independent source fingerprint and separate statewide controls. Details: [county classification sources](../sources/county-buckets/findings.md).

County timelines, cumulative comparisons and county drilldowns retain PNG and CSV actions. Bucket PNGs identify county geography, classification and reporting scope. County timeline cards can be collapsed independently of precinct views; only visible panels respond to bulk collapse.

County arithmetic, navigation, scope, real images and responsive acceptance:

```bash
TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright --with pillow python dashboard/tests/county_buckets.py
```

The independent audit covers all six Census metrics and partisan buckets, every available selected day, all 12 calendar positions, native daily/cumulative values and all 254 county rows. Browser evidence and actual exported images are saved in `../analysis/county-buckets/qa/`.

The precinct workspace now covers **215 counties and 8,950 native precincts**, including Tarrant, Harris, Collin, Bexar, Denton, Fort Bend, Williamson, Hidalgo, El Paso and Nueces. Texas SOS downloads were checked across all254 counties;206 additional counties were admitted after source and geographic checks. Some counties have incomplete daily cutoffs or historical dates; those remain unavailable, with a compact expandable notice. The county workspace continues to cover all254 official county totals independently.

County comparison tables show12 counties per page, with search and Previous/Next controls. An **All Counties** column stays pinned beside the bucket labels, including during horizontal scrolling. It pools every available county for the selected day, cohort and classification, independently of county selection, search and pagination; ratios divide summed 2026 votes by summed matched 2024 votes. The CSV retains the full selected county scope; matrix images show All Counties alongside the current page/filter. Maps load one county at a time. Partisan and demographic analyses retain their separate coverage: every admitted county has Census estimates and map geometry, while presidential classification includes only native returns or a qualified one-to-one TLC bridge. Certified county presidential returns are used for Harris, Tarrant and Collin. Source qualifications are disclosed by county. Demographic dots with incomplete presidential membership remain neutral and keep their demographic turnout values; a partial presidential sum never becomes a known party share.

Harris uses native dated in-person county ZIPs consistently in both cycles, recovering incomplete SOS current reports. Nueces2026 uses its dated county in-person PDF, discovered from the current county page and parsed through anonymous `pdftotext` pipes; its source was independently checked with a second PDF engine. Tarrant retains a documented narrower SOS series: the audited conflicting historical record is counted once as unassigned, and its county/state total difference is preserved. Duplicate corrections are restricted to specifically audited identical rows and dates. A mail record beside an in-person record does not duplicate the included method. Other in-person identifier collisions remain errors. No voter roster, PDF containing voter data, extracted names or personal IDs are saved.

Use the actual official county name (including spaces) in SOS query parameters. The Rust collector encodes this automatically. Immutable historical aggregates are reused; current sources continue to refresh on the existing schedule and failures preserve prior available cutoffs. A new `rebuild` command reproduces analysis and history from retained aggregates only, without source requests:

```bash
cargo run --locked --manifest-path dashboard/Cargo.toml -- rebuild --through 2026-10-23
TURNOUT_TEST_URL=http://127.0.0.1:8741 uv run --with playwright --with pillow python dashboard/tests/expansion.py
cargo test --locked --manifest-path dashboard/Cargo.toml --test expansion_sources -- --ignored --nocapture
```

The opt-in Rust test checks real source collectors against independently acquired precinct aggregates; it processes voter records only in memory. Use `TURNOUT_VERIFY_COUNTY=nueces` (or another test county) to run a targeted source check. Source discovery, admissions, mapping/Census conservation, certified-return overrides, remaining gaps and reproducible scripts are under [precinct expansion](../sources/precinct-expansion/). The source and calendar audit covers all admitted counties; browser checks include linked points/maps, full-scope CSV, real PNGs, matrix paging/search and desktop/mobile layouts. `dashboard/tests/matrix_total.py` independently verifies the All Counties benchmark, filters, sticky columns and PNGs; set `TURNOUT_MATRIX_SERVED=1` to check served assets. Nueces PDF extraction additionally requires the installed `pdftotext` utility.

Scheduled PNG/SVG comparison tables paginate at nine counties per image, with all pages linked in the generated report; percounty images and full CSV exports retain their scope. The first comparison page retains its existing filename. The current independently checked matched image set is in `../analysis/matched-through-2026-10-23/`. Source-specific qualifications remain in the report and snapshot.


Matched coverage is resolved independently for every date and measure. Each precinct group requires known2024 and2026observations for all of its geographic members. A reported partial county remains available through its supported groups; incomplete latest observations do not remove earlier days. Each bucket divides summed2026votes by summed2024votes over exactly the same groups at that point. Historical future baselines remain visible without implying future2026votes.

Daily reports, exact cumulative snapshots and cumulative snapshots continued with later daily reports are supported separately. Missing IDs are unknown unless a completed source establishes zero. An absent precinct is zero only when its dated roster exactly reconciles to an independent same-scope control and has no unassigned voters, in either cycle. Historical age alone is insufficient. The immutable Harris 2024 archive with verified residence-precinct conflicts retains its explicit observations but cannot certify omitted zeros; its source hash and evidence are documented in [the Texas audit](../sources/texas-stress/source-findings.md). Cumulative prefixes retain only precincts with supported observations throughout the required interval. Missing individual precincts and negative differences are excluded individually, rather than removing the county. Availability identifies reported precinct geography; it does not certify that every voter row in a published precinct has finished arriving. Known source/control gaps remain under Sources.

County views use matched residence-precinct rollups where supported and paired county aggregates otherwise. Native county controls replace known underfilled SOS aggregate values before aggregate fallback. Each daily/cumulative observation exposes its scope and matched precinct/baseline coverage. Dates and reporting scopes are paired within each point, while per-point membership may change. The table, regression, map, profiles and CSV/PNG exports all respect the selected point's availability. Exports are disabled while a replacement view is loading, preventing an older chart from receiving a newly selected cutoff.

The October24 adversarial audit preserves every previously participating county at each cutoff, including all197counties with an October23 Day5cumulative precinct subset; all215native map/Census county entries remain. Tarrant remains included through its supported precinct subsets. Exact group counts and coverage vary by date, measure and source revision. Fort Bend now uses the county's dated native precinct workbook (134784reported voters), with its remaining county-control difference documented, instead of the severely underfilled SOS feed. No missing county votes are allocated to precincts.

`python3 dashboard/scripts/audit_completeness.py --through 2026-10-23` updates native controls. The registry is at `/api/completeness`; it supports zero proof, source diagnostics and native aggregate replacements, not whole-county admission. Source caches are preserved. Rebuild with `cargo run --locked --manifest-path dashboard/Cargo.toml -- rebuild --through 2026-10-23`. New figures are written under `analysis/matched-through-YYYY-MM-DD/`, with frozen source counts and controls. The prior strict whole-county completion policy and its acceptance reports are superseded by this per-date matched policy.

Current acceptance:

```bash
python sources/completeness/verify.py
TURNOUT_TEST_URL=http://127.0.0.1:8743 python dashboard/tests/matched_api.py
TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/matched_browser.py
```

### Additional states

The header state selector adds Georgia, North Carolina, Virginia and Nevada to the same Rust server. Texas retains its precinct/county workspaces. Added states have county trends, county buckets, Census composition, linked county maps and regressions, source details, collapse controls, and individual PNG/CSV exports. Published voter race, age, sex, ethnicity and registration-party groups appear where supported. Registration party and county presidential partisanship remain separate classifications.

Initial October 23 coverage:

| State | Current county/locality coverage | Source and available detail |
| --- | ---: | --- |
| Georgia | 159 | SOS-linked Qlik daily accepted ballots; actual race, age and sex; official county presidential returns |
| North Carolina | 100 | NCSBE accepted absentee/early ballot records aggregated in memory; registration party, race, ethnicity, age, sex, white/non-white; official county presidential returns |
| Virginia | 133 | EPEC's published aggregates of ELECT Daily Absentee Lists, explicitly attributed as an independent archive; county/city daily countable ballots |
| Nevada | 2 | Official Clark and Washoe records; Clark has the 2024 dated baseline; mail registration party where actually published |

Georgia opens with **Statewide voter race**, ahead of the overall turnout trend. Race, Age and Sex controls compare the published voter groups statewide with the equivalent 2024 point; they aggregate the official accepted-ballot categories across matched reporting counties. Age groups run in numerical order. **County demographics** remains a separate classification using Census composition. Explicit classification deep links remain supported.

Each state uses its own opening/closing dates. Calendar dates align by equal days before Election Day: October23,2026 compares with October25,2024. Matching is independent by date, voting method and daily/cumulative measure. Missing data are never zero-filled to create a comparison; future points retain the historical benchmark alone. **2026 reported** totals retain current counties without a historical pair; **matched** columns and charts use the same counties in both years. Nevada's other15counties remain neutral on its17county map rather than receiving invented turnout. Mail in Nevada means returned ballots, including pending processing/signature statuses; it is labeled accordingly and never pooled across states with a different definition.

County demographic buckets use Census Bureau2020–2024ACS special-tabulation adult estimates, with Under18 divided by total population. Black and Asian metrics here are non-Hispanic alone. Total non-white is adult population minus White non-Hispanic adults. These describe county residents; the separate voter-group views describe published participants. Census estimates include sampling uncertainty. Official county2024presidential counts determine partisan buckets and demographic dot colors. Map geometry comes from the Census2020county service, joined by explicitFIPS; no precinct interpolation is used.

The **2026 precincts** inspector exposes native reported counts in NC/NV and the available VA archives. It has no cross-cycle ratio or inferred boundary match. VA's currently published precinct archive stops September23 despite county data continuing through October23; the inspector shows noOctober23precinct observations and exposes its latest reported date. Native aliases remain separate. Current precinct counts never enter county headline totals or regression fits. Source/county reconciliation differences remain in the state findings.

Endpoints:

```text
GET /api/states
GET /api/states/ga?date=2026-10-23&method=in_person&classification=partisan
GET /api/states/nc?method=total&classification=white_nonwhite
GET /api/states/va?classification=demographic&metric=non_white_vap
GET /api/states/nv/map
GET /api/states/nc/precincts?county=37183&date=2026-10-23&method=in_person&measure=cumulative
```

The Rust refresh loop runs all four state collectors in parallel alongside Texas. They retain last-successful observations on source failures; dates beyond the actual published coverage remain unavailable. Eastern/Pacific completed-day cutoffs are state-specific. Only anonymous aggregates and provenance are saved. No paid APIs or new application dependencies were added.

```bash
python3 dashboard/scripts/states/georgia.py --through 2026-10-23
python3 dashboard/scripts/states/north_carolina.py --through 2026-10-23
python3 dashboard/scripts/states/virginia.py --through 2026-10-23
python3 dashboard/scripts/states/nevada.py --through 2026-10-23
python3 dashboard/scripts/build_multistate_reference.py --offline
TURNOUT_TEST_URL=http://127.0.0.1:8743 python3 dashboard/tests/multistate_api.py
TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/multistate_browser.py
TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/georgia_headline.py
```

Primary-source links, transport/scope qualifications, independent controls and retained aggregate evidence: [state findings](../sources/multistate/findings.md). Current acceptance artifacts are under `analysis/multistate/qa/`.

Automatic-range verification: `node --test dashboard/tests/regression-scale.test.cjs` and `TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/regression_auto.py`.

GitHub Pages publication and unattended refresh: see [PAGES.md](PAGES.md).


### Combined turnout and hourly updates

County/state views open with **Mail + in person**. Texas SOS native cumulative mail is preserved for both cycles, including receipts before regular in-person voting opened. Daily mail uses the preceding calendar day's cumulative report; downward revisions, missing prior reports and uncorroborated current literal zeros remain unknown. A positive cumulative mail observation remains usable even if its daily change is unknown. Combined points require both methods on the same geography and date in both years. Independent full-county in-person controls may replace an underfilled SOS in-person count; matched precinct subsets are never added to full-county mail. Sources retain the scope and provenance of each component. Separate Mail and In person controls remain available.

Texas precinct visuals remain explicitly In person. The optional `collect_harris_mail.py` audit validates native records without retaining identities and preserves the last successful output on a failed gate. Its current paired historical source totals disagree with SOS by-mail controls; therefore no combined Harris precinct cohort is published. See `sources/mail-turnout/precinct-findings.md` and `texas-aggregate-findings.md`.

Georgia/NC/Nevada combined counts use their paired mail and early in-person components. Virginia combines MAIL_IN with ON_MACHINE; extra COUNTABLE categories are excluded. Published returned-mail definitions vary by source and are disclosed under Sources. Future dates retain the historical benchmark without filling current-year unknowns.

GitHub Actions is scheduled once an hour at minute17 UTC; actual starts may be delayed by GitHub. Browser data reloads/publication checks and the local Rust default collector interval are hourly. Manual Check updates checks the current publication immediately. Local manual source refresh polls only until that explicitly requested job completes.

If a Pages deployment removes an artifact still referenced by an open tab, the browser checks the publication once, resolves the original selection against the new manifest, and reloads the current view with its filters preserved. Concurrent misses share recovery. An unchanged publication or genuinely missing replacement still reports an error; this recovery does not change the hourly source schedule.

`texas-turnout statewide [--through YYYY-MM-DD] [--offline]` refreshes only county aggregates or rebuilds them from retained native caches. `build_statewide.py --through ... [--offline]` delegates to that canonical Rust implementation. Cached schema1 in-person-only files cannot masquerade as combined turnout; retained native bytes migrate to schema2 or historical sources are fetched again.

### Texas adversarial verification

The audit independently reconstructs publisher controls, tests missing reports and cumulative revisions, validates geographic/classification partitions, and checks plotted SVG positions, CSV/PNG and same-generation publication races. A county update uses its own completed cutoff even while precinct data lags. Existing tabs invalidate derived comparisons on a changed publication; delayed responses cannot overwrite the newer view. Winner colors require complete presidential membership in both the API and browser.

```bash
cargo test --manifest-path dashboard/Cargo.toml --test texas_matching_stress
TURNOUT_TEST_URL=http://127.0.0.1:8743 python3 dashboard/tests/texas_matching_stress.py
TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright --with pillow python dashboard/tests/texas_visual_stress.py
TURNOUT_PAGES_URL=http://127.0.0.1:8745/site/ uv run --with playwright python dashboard/tests/pages_rollover.py
```

For the rollover browser check, set `TURNOUT_PAGES_URL` to a generated static site or the published dashboard. Add `TURNOUT_ROLLOVER_STATUS=410` to exercise deleted artifacts, and `TURNOUT_PAGES_USE_SERVED_ADAPTER=1` to verify the deployed adapter instead of routing the local source.

Source reconstruction requires the retained publisher evidence used by the audit. Reproducible findings and source qualifications: [Texas source audit](../sources/texas-stress/source-findings.md). Native response bytes and anonymous source counts are preserved; unsupported values are never replaced by a maximum, carried forward, or allocated to precincts.

The header's Buy me a coffee button opens [paypal.me/JacksonHannan](https://paypal.me/JacksonHannan) in a separate tab. Contributions are handled by PayPal; the dashboard does not collect payment details or set an amount.


Place types are a categorical classification in both Texas workspaces. The versioned `places/texas.json` combines NCES 2025 Census-based locale polygons with 2020 Census PL 94-171 block age-18+ counts, assigned by the same internal-point method used by the existing precinct Census layer. It includes all 254 county controls and all 8,950 mapped precincts; it is rebuilt with `uv run dashboard/scripts/build_places.py --source-root PATH --offline` after retaining the documented public inputs. The file preserves input URLs/hashes, transformation versions, invalid-ring repairs and unclassified population. No election votes are assigned by area or population.

- Urban: NCES city locales 11–13.
- Suburban: NCES suburb locales 21–23.
- Exurban: NCES town-fringe 31 and rural-fringe 41.
- Rural: NCES distant/remote town 32–33 and rural 42–43, further classified Rural Anglo or Rural Hispanic only when White alone non-Hispanic or Hispanic age-18+ residents exceed half of the geographic group’s total age-18+ population.

A county or common geographic group must have more than half of its age-18+ population in one of those geographic types. Unknown locale assignments remain in the denominator, so they cannot manufacture a majority. Other / unclassified retains mixed types, other rural compositions, uncertain geography and zero-population areas; numeric Census percentage views still require a positive population denominator. The five names are dashboard-derived aggregations, not an official Census five-type standard. See [NCES definitions](https://nces.ed.gov/surveys/annualreports/topical-studies/locale/definitions) and [locale boundaries](https://nces.ed.gov/programs/edge/Geographic/LocaleBoundaries).

`/api/places` exposes the fixed source reference. `view=place&metric=place_type` works in demographic-view, trends and county-buckets. Category codes are identifiers, not continuous measurements: place bucket API views intentionally return no OLS fit. The Explore place regression uses numeric 2024 Harris share and cumulative 2026 votes as a percentage of the same cutoff in 2024; colors and the optional regression filter identify place type. Existing partisan, primary and Census percentage definitions are unchanged.

Measure labels distinguish same-day and cumulative votes. Matrices, profiles, precinct records and regressions are cumulative at the selected cutoff; timeline selectors govern their adjacent trajectories. Ratios mean 2026 votes as a percentage of paired 2024 votes, not turnout as a percentage of registered voters. Coverage notes follow the selected day and distinguish missing paired geography from a retained source after a failed latest download. See [DESIGN.md](DESIGN.md#october-25-visualization-review) for the visualization review and remaining recommendations.

The matrix’s **Buckets × partisanship** layout offers the six Census composition metrics and Place type as row groupings. Place type adds the six categorical rows, including the residual, against every presidential-margin column; vote-weighted marginals and the tied/unknown presidential column remain intact.

Interactive navigation now uses action-driven motion: state, county and precinct maps travel to their selected extent; section switches, panel expansion and changed chart comparisons transition briefly. Maps below the fold defer their entry zoom until visible. Motion is interrupted by newer selections, respects `prefers-reduced-motion` (including a preference change during travel), and settles before PNG capture. Hourly background updates do not trigger these reveals. The shared `static/motion.js` owns timing/camera lifecycle; `tests/motion.py` checks real intermediate camera frames, final extents, cancellation, reduced motion and exports against either Pages fixtures or the public website.


Historical Days 1–5 coverage and the October 25 source recovery are documented in [the coverage audit](../sources/historical-coverage/findings.md). The versioned anonymous edition at `recovery/texas-20261025.json` replaces only the reviewed conflicting Harris archive hash and fills missing dated Ellis, Houston and Leon reports in retained caches. It preserves later unreviewed revisions. Both the native API and Pages exporter apply it before the existing independent completion checks, daily accumulation and geographic matching. Its fingerprint invalidates derived caches even when the raw snapshot timestamp is unchanged. The live Ellis collector now requests dated SOS reports; two historical duplicate exceptions accept one exact repeated row only for the reviewed file hashes.

To independently audit each county/day from the API's anonymous source observations:

```bash
curl --fail http://127.0.0.1:8741/api/data -o /tmp/turnout-snapshot.json
python3 dashboard/scripts/audit_precinct_coverage.py --snapshot /tmp/turnout-snapshot.json --output /tmp/turnout-coverage.json
cargo test --locked --manifest-path dashboard/Cargo.toml --test historical_recovery
# Optional: download the reviewed live reports into memory, with no voter records saved.
cargo test --locked --manifest-path dashboard/Cargo.toml --test historical_recovery -- --ignored --nocapture
```

The audit reconciles every published cumulative pair, including wholly missing county-days. `--require-complete` additionally fails if any native precinct remains unpaired; real source gaps are expected to fail that stronger condition. Availability is separate from presidential/Census/primary classification. `tests/historical_coverage.py` checks all 1,075 county-days, recovered primary/demographic timelines against independently summed groups, future missingness and the actual browser/PNG; `TURNOUT_JOINT_STATIC=1` selects Pages transport.
