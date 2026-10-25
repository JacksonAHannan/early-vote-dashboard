# Texas early vote dashboard — VoteHub reference

Capture date: 2026-10-23. Target: existing Rust dashboard and linked map/scatter workspace.

![VoteHub’s first-party early-vote illustration](../sources/map-atlas/votehub-early-featured.png)

This image is an editorial illustration, not a captured operational dashboard. Use its restrained palette and panel hierarchy as inspiration; build original UI and copy.

## Evidence and limits

Primary references: [2024 precinct map](https://votehub.com/2024-map/), [2026 early-vote tracker](https://votehub.com/2026-early-vote-tracker), [Texas primary tracker](https://votehub.com/early-vote-tracker-tx-primary-26), and the [first-party featured image](https://votehub.com/wp-content/uploads/2026/09/2026-early-vote-tracker-fi-1024x576.png). Extracted primary-page controls establish map/result views, geographic search, partisan/demographic modes, and same-date versus final-baseline selection.

Firecrawl credits were exhausted; no additional credit-consuming calls were made. Direct Chromium requests reached Cloudflare security verification; `sources/map-atlas/votehub-precinct.png` and `votehub-early.png` preserve that limitation. They are not visual evidence of VoteHub’s dashboard. Full rendered fonts, CSS, exact layout measurements, dark-mode behavior, and animations could not be verified. Tokens and dimensions marked “recommended” below are original implementation choices.

## Direction

Recommended: light default, white analytical surfaces, cool off-white canvas, fine borders, compact controls, dense numeric rows, and a map that receives most of the workspace. Geometry, color, alignment, and scale should explain the interaction. Keep source/method notes in an expandable area. Use short control names and direct axis units; avoid subtitles repeating what the chart already shows.

## Palette

Measured pixels from the first-party illustration, not CSS tokens:

| Role in illustration | Color |
| --- | --- |
| Dominant panel fill | `#F8F9FC` |
| White surface | `#FFFFFF` |
| Democratic blue | `#026EB6` |
| Intermediate map blue | `#338AC4` |
| Pale map blue | `#DFEBF5` |
| Republican red | `#CC0000` |
| Violet accent | `#7C3AED` |
| Neutral rule | `#D9D9D9` |

Recommended implementation: canvas `#F5F6F8`, surface `#FFFFFF`, ink `#1D2633`, muted ink `#667085`, rules `#E3E7ED`. Use the measured blue/red as directional inspiration with less saturated intermediate choropleth bins. Reserve violet for active UI or selected precincts; demographic sequential scales should differ clearly from partisan red/blue. Keep turnout comparison colors and axis labels stable across views. Give selection both an outline and a color change.

## Layout and typography

Recommended desktop layout: slim header, compact county/day/cohort controls, four short aligned metrics, then one map/scatter workspace. Give the map 56–64% of width and the scatter/detail column 36–44%. Map height 540–620 px at a 1440 px viewport. Use the same surface frame around linked panels, a 1 px divider, and 16–20 px internal padding. Keep selectors immediately above the visualization they govern.

Recommended type: existing system sans stack, 13–14 px controls/body, 11–12 px axis/column headings, 18–20 px panel titles, 28–34 px primary values. Use tabular numerals for every metric/table. Do not import fonts merely to imitate an unverified font. Use 6–8 px control corners, 10–12 px panel corners, restrained shadows on floating map controls only. The illustration’s corners appear roughly 12–14 px, but production UI need not match them.

A four-pixel spacing basis supports a dense 8/12/16/20/24 rhythm. Align labels, values, chart boundaries, and table columns. Avoid individually boxed cards for every minor statistic. Below 980 px, stack map above scatter/details; at mobile widths keep the map at least 360 px high and wrap controls without horizontal page overflow.

## Components and analysis mechanics

Observed primary-page patterns: compact map modes, geographic search, results table, demographic filters, and alternative historical baselines. Adapt these patterns to this analysis:

- Partisan / Demographic is a single segmented switch; the metric selector changes with the mode.
- A regression-point click fits every native polygon in its common geographic group and opens the selected group’s figures. Keep selection when changing metrics.
- Map clicks select the matching scatter point. Hover temporarily emphasizes the match without moving the map. Use a 2–3 px selection boundary and a small halo for tiny polygons.
- A small in-map legend shows the active metric, units, and scale. Its colors also appear in the scatter and bucket chart.
- Show the selected group in one compact strip with precinct identifiers, turnout ratio, Harris share, population, and demographic composition. Name grouped values accurately.
- Place the demographic bucket comparison beneath the linked map/scatter workspace, then the sortable precinct table. Short columns and inline bars support scanning.
- Keep the 100% turnout reference and 50% Harris reference visually lighter than observations. Use subtle quadrant washes, thin OLS line, crisp selected dot, and explicit units.
- Use smooth 300–500 ms map fitting and 120–180 ms state transitions; honor reduced motion. Avoid decorative entrance effects.

## Content and integrity

Use short labels such as County, Day, Cohort, Partisan, Demographic, Harris, Hispanic, Turnout, and Reset. A compact date in the header and an expandable Sources area are sufficient for routine provenance. Keep denominator/vintage details available at selection or source disclosure; never describe population composition as the demographics of people who voted. Preserve undefined values and show missing-data geometry neutrally.

No VoteHub logos, illustrations, proprietary map data, or copy are used as product assets. The downloaded illustration is reference evidence only.

Rerun inputs: workflow `firecrawl-website-design-clone`; source URLs above; target existing Rust dashboard; output `dashboard/DESIGN.md`.


## Analytical navigation

The geographic level is the first choice: Counties (all 254 official aggregate reports) and Precincts (all available native precinct counties). Each workspace owns its classification filters. Counties supports 2024 presidential margin and the six 2020 Census compositions. Primary participation remains in Precincts where acquired party-specific counts support it. A shared completed-day row selects the comparison cutoff.

County tracking leads with a two-by-three timeline grid, then selected-day cumulative comparisons and searchable county drilldown. Bucket selection filters county records and their aggregate trend. The daily and cumulative reporting cohorts have separate counts; native cumulative values remain independent of daily values. The compact comparison row becomes three columns across two rows in a social image so labels remain legible.

Precinct Trends contains daily buckets and the cross-county matrix. Explore contains the linked map/regression, selected geographic profile, local bucket bars and precinct table. Clicking a matrix bucket opens Explore. A county with native precinct coverage offers a direct Precincts action from its county trend. Navigation preserves independent filters and panel collapse state; bulk folds act only on the visible workspace.

Keep metric names in their selectors rather than repeating them in subtitles. Show the Census vintage once beside demographic controls, county coverage beside timelines, and detailed provenance in the source disclosure.


## October 25 visualization review

The analytical sequence is geography → classification → time → selected-place detail. Preserve the existing system sans typography, white surfaces (#FFFFFF), cool canvas (#F5F6F8), ink (#1D2633), muted text (#667085), and rules (#E3E7ED). Blue/red encode presidential support; orange/teal encode turnout below/above 2024; categorical place types need their own discrete legend. Violet remains selection only.

```text
Counties: classification + voting method
  Daily / cumulative trajectories → cumulative cutoff comparison → county records
Precincts: shared county + classification + cohort
  Trends: daily / cumulative trajectories → cumulative bucket matrices
  Explore: shared geography and cumulative comparison period
    Texas county overview / selected county precincts | same-scope regression
    Selected county / precinct profile and local records
```

| Finding | Recommendation / implementation criterion |
| --- | --- |
| County map beside an all-county regression suggests different data are linked | One county state governs both views. Default to a Texas county overview; county selection and point drilldown scope the regression to that county. Returning to Texas resets both. |
| A bare percentage can mean daily share, cumulative share, or turnout rate | Label ratios as cumulative or same-day **2026 as % of 2024**; counts as votes. None is a percent of registered voters. Keep units in charts, tooltips, accessible descriptions and exports. |
| Current-source failures are repeated on historical cutoffs | Describe coverage for the selected day. Distinguish incomplete paired geography, unavailable classifications, and a cached latest download. Show missing values as gaps / gray, never zero. |
| County totals and matched-precinct subsets have different scope | Keep county and precinct workspaces separate; disclose paired subset coverage at the value and in exports. Retain all available same-day pairs. |
| Daily and cumulative data are interspersed | Keep trajectories together and cutoff snapshots together. A measure control governs the trajectories adjacent to it; cumulative snapshots remain labeled cumulative. |
| Geographic labels can imply a universal definition | Use documented Census-based NCES locale boundaries with explicitly derived five-type groups and an Other / unclassified residual. Describe residents, never assume voter ethnicity. |
| Numeric coding of place types invites a meaningless regression | Use category buckets for place comparisons. Any associated OLS keeps a real numeric presidential-share axis and identifies its geographic cohort. |
| Maps make low-population territory visually dominant | Pair the map with vote-weighted tables and the equal-observation scatter; retain counts, denominators and group counts on interaction/export. |
| Auto-scaled regression can conceal outliers | Retain the outside-view count and Full range option; include all eligible observations in fit/CSV. |

Recommendations retained for future analysis: compare within-place-type slopes and report county-clustered uncertainty before interpreting differences; offer fixed-membership trend cohorts as an optional sensitivity view alongside the maximum available per-day comparison. Neither is a causal estimate.

Geographic references: [NCES locale definitions](https://nces.ed.gov/surveys/annualreports/topical-studies/locale/definitions), [NCES locale boundaries](https://nces.ed.gov/programs/edge/Geographic/LocaleBoundaries), and [Census urban/rural geography](https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html). The five requested names are a dashboard aggregation, not an official Census five-category standard.
