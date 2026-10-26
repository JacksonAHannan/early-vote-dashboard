# Image export audit

Read-only architecture review, 2026-10-26. No turnout arithmetic or source handling changes are proposed here.

## Rendering owners and shared seam

There are exactly two user-triggered PNG composition owners:

1. `dashboard/static/visuals.js`, `Visuals.download`: Texas. It freezes `Visuals.descriptor(key)` before asynchronous capture, then composes a 1600 × 1000 opaque canvas. `Visuals.capture` clones the current rendered visual into an SVG foreignObject, removes controls, expands scrolled matrix columns, limits tables to 12 rows, and normalizes overview grids to three columns. It already settles animations and waits for fonts.
2. `dashboard/static/states.js`, `downloadImage`: Georgia, North Carolina, Virginia and Nevada. It reuses `Visuals.capture` for most bodies but directly builds map SVG and multi-bucket SVG. It freezes the source view, regression, request and selection key, then refuses the download if selection changes while capture is pending. The final canvas composition is separate and duplicates Texas framing.

The smallest coherent seam is one final canvas compositor on the existing `Visuals` owner, called by both paths after capture. Input should be the captured `{img,width,height}` plus frozen title, state, scope, method, measure, dates, classification, legend, coverage/method notes and source. That owner can apply Alabama brand tokens, wrap long metadata, reserve a social attribution strip, and preserve both callers' capture/race contracts. No need to replace SVG capture, map generation, source APIs, or CSV generation.

The X identity must read `@electionsjack`; the LinkedIn identity should be recognizable as `linkedin.com/in/jackson-hannan`. Keep the complete canonical URL `https://www.linkedin.com/in/jackson-hannan` available in a copied caption or accessible share metadata. Raster PNG text is not a clickable social link. Neither identity is currently drawn by either compositor.

New separate JS requires a native route in `dashboard/src/main.rs` and a script tag before `states.js`; Pages already copies all static files and rewrites root-relative tags in `pages.rs::copy_static`. Extending the existing `Visuals` object avoids a new route.

## Every export branch

| Owner | Keys | Content and required qualifiers |
|---|---|---|
| Texas | `county-daily`, `county-daily-N` | County bucket timeline overview or individual bucket; selected daily/cumulative measure, county method (mail, in person, combined), classification, matched counties varying per day; future 2024 benchmark only |
| Texas | `county-summary` | Cumulative county bucket comparison, matching counties in both years, selected county method |
| Texas | `daily`, `daily-N` | Precinct bucket timeline overview or individual bucket; selected measure and classification; validated in-person only; matched geography can vary per day |
| Texas | `matrix` | County-by-precinct-bucket matrix or demographic/place × partisan matrix; cumulative in-person vote ratio; All Counties may cover more counties than the visible page; keep missing baseline and small-cell markers |
| Texas | `map` | Statewide county overview of matched precincts, or selected county precinct map; either static presidential/Census/primary/place layer or cumulative turnout layer; county overview is not whole-county turnout; keep proxy geography and unavailable gray distinction |
| Texas | `regression` | Cumulative in-person turnout vs chosen metric; selected county/winner/place subset, unweighted OLS, full eligible fit even when axis range hides points; demographic points retain presidential party colors |
| Texas | `profile`, `demographics`, `precinct-trend` | Selected precinct/group profile, Census resident composition, or cumulative in-person timeline; preserve selected geography and changed-boundary comparable-group context; residents are not voter demographics; overlapping categories are not additive |
| Texas | `bucket-bars` | Selected county cumulative bucket bars; current day, source and matched geography |
| Texas | `precinct-table` | First 12 rows on current page/sort/filter; cumulative in-person counts, selected county and comparison geography |
| Texas | `county-table` | First 12 matching counties in current sort; cumulative county method, distinct whole-county vs ordinary-precinct scope |
| Texas | `county-trend` | Selected county or statewide county-total timeline; selected measure and county method; matched geography varies by day |
| Other states | `turnout` | Matched statewide timeline; selected method and measure; actual paired dates and future baseline only |
| Other states | `buckets`, `bucket-N` | Current page of bucket charts or one native-index bucket; selected method/measure/classification; Georgia statewide race/age/sex groups are voter demographics, separate from county Census buckets; page-two native indices must remain correct |
| Other states | `map` | Current map extent and county classification; selected county highlight, Census vintage or presidential party colors; not a turnout layer |
| Other states | `regression` | Always cumulative even when measure selector says daily; selected winner subset, n and R², unweighted OLS and all eligible observations in fit |
| Other states | `county` | Selected county profile and timeline; selected measure/method, resident demographic estimates |
| Other states | `precincts` | NC/NV reported 2026 precinct counts, selected county/method/measure and first 12 current filtered/sorted rows; no cross-cycle boundary match or turnout ratio |
| Other states | `table` | First 12 counties (Virginia localities) in current sort/filter; reported totals and same-date matched totals are distinct |

`Visuals` still has legacy `detail` and `counties` descriptor aliases without current image buttons. Keeping them routed through the compositor is inexpensive. Dynamic individual bucket buttons are inserted after re-render and must remain unique.

## Batch renderer

`dashboard/scripts/render_images.py` generates PNG/SVG/CSV for immutable Texas snapshots and is invoked after a native source refresh (`main.rs`, around line 252). Images have variable figure sizes, include source/comparison notes, and are linked from the generated local report. They are not exposed by any dashboard image button or server image route, and Pages copies only `static/` plus its generated API assets. If the request is interpreted as branding *all generated images* rather than every website export, update this batch renderer too; it cannot call a browser compositor. Its metadata/footer can share identity constants conceptually without adding a new execution dependency. Its existing older narrative notes should not be rewritten as part of a visual-only change.

## Existing test risks

- Roughly 20 browser suites hard-code PNG dimensions `(1600,1000)` or report `[1600,1000]`: `visuals`, `multistate_browser`, `regression_winner`, `regression_auto`, `county_buckets`, `mail_turnout`, `georgia_headline`, `matched_browser`, `completeness_browser`, `explore_scope`, `motion`, `joint_matrix`, `matrix_total`, `expansion`, `texas_revision_stress`, `texas_visual_stress`. A size change requires explicit migration to the new presentation contract, while keeping the real image/type/opacity/content checks.
- `multistate_browser.py` and `regression_winner.py` call `getcolors(1600001)`; larger canvases need `width*height+1` or a bounded sampled-color check rather than an obsolete count cap.
- `visuals.py` checks exact Census palette RGB values and exact blue `(34,102,167)` table ink. Preserve semantic chart colors unless deliberately rebranded; replace obsolete exact-brand-ink tests with text/content/contrast assertions, not removal of body verification.
- `visuals.py` uses fixed body pixel bounds (x 96..1504/y250..850) to ensure mobile overviews use available space. `multistate_browser.py` scans fixed body bounds (48..1552/y210..900) to detect clipped scrollbar runs. Update these to the compositor's content rectangle if framing changes.
- OCR asserts exact useful phrases: `unweighted ols`, `cumulative turnout`, `non-white`, `2020 census`, and `comparison-group turnout`; the turnout-map export must not be relabeled as resident composition. Regressions also assert winner, `n = ...`, `R² = ...`, sources and method through intercepted canvas text/capture descriptions.
- Race guards and filenames are substantive contracts: Texas pending day changes retain the original captured day; other-state pending selection changes abort stale image output. Filenames include actual scope, method, measure, date, winner and bucket page.
- Native asset delivery uses compiled `include_str!`; restart with a rebuilt binary when testing product edits. A running old native service can otherwise produce a false result.

## Bounded acceptance plan

1. Add one compositor contract test covering long wrapped title/source/coverage, empty optional notes, both identities, opaque PNG, chosen aspect ratio, no cropped text, and measured content/safe rectangles. Inspect both actual decoded pixels and canvas text; text interception alone cannot prove the image is readable.
2. Extend existing broad export tests, rather than creating a parallel export implementation oracle: `visuals.py` for Texas and `multistate_browser.py` for the other states. Verify both identities on **every** actual user-triggered export they exercise, including dynamic single buckets and page-two Georgia age exports.
3. Focus additional coverage on semantic edge cases: Texas combined county totals vs in-person precincts; demographic joint matrix; statewide overview vs selected county map; Harris/Trump winner regression; Georgia statewide voter demographics; Virginia archive source attribution; NC/NV current-only precincts; future 2024-only benchmark; county/table row limit and sort/filter scope.
4. Preserve existing request races and animation settling with `motion.py` plus the delayed captures in `visuals.py` and `multistate_browser.py`. Do not rerun source/network stress suites when data collection and arithmetic are unchanged.
5. Render real desktop/mobile screenshots (1512 and 390 px), inspect representative PNGs at native resolution and feed-sized reduction (about 600 px wide), including the densest matrix/table and nine-chart page. Social attribution must remain distinct from data provenance and cannot displace required date/method/coverage qualifiers.
6. Test a static Pages build under a nested base path as well as rebuilt native delivery, because those asset paths differ. Confirm no new external image/font dependency can taint canvas or break offline exports. Record console errors, real download filenames and PNG dimensions.

No platform engagement uplift or optimal aspect ratio is established by this local audit; cite current official platform specs and describe any editorial presentation recommendations as design judgments in the research deliverable.
