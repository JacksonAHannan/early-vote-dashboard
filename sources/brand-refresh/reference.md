# Alabama forecast brand reference

Measured 2026-10-26 from the user's [Alabama legislative forecast](https://jacksonahannan.github.io/alabama-state-house-and-state-senate-model/index.html?model=headline&chamber=house&mode=probability&view=map), using rendered Chromium at 1440×1080 and 390×844. Firecrawl account credits were exhausted; direct browser inspection supplied screenshots, the live CSSOM, computed element styles, DOM structure, and platform font evidence. No paid retrieval was attempted.

## Observed design

The identity is a burgundy masthead and footer framing a pale blue analysis workspace. Black bold sans-serif titles, white square chart surfaces, blue-grey dividers, and blue/red data marks establish hierarchy. The density is deliberate: controls are contiguous rectangular segments; the selected control is ink with white text. The map is the main visual rather than decorative imagery. There are no soft card shadows or rounded containers in the measured key panels.

| Role | Exact live CSS token |
|---|---|
| Page paper | `#dbeaf2` |
| Panel | `#eef5f8` |
| Raised surface | `#f8fbfc` |
| Chart surface | `#ffffff` |
| Primary ink | `#211b1b` |
| Secondary ink | `#394b58` |
| Muted text | `#586772` |
| Divider | `#9db4c1` |
| Soft divider | `#cddbe3` |
| Brand burgundy | `#743b42` |
| Burgundy tint | `#f5e9e8` |
| Copper brand token | `#a86742` (declared; not dominant in the rendered main view) |
| Democratic data | `#2878b5` |
| Republican data | `#c93f49` |
| Neutral/tossup | `#d9cfbd` |

The categorical rating ramp is `#1d5c94`, `#3b7fbd`, `#77a7d6`, `#b3cfe9`, `#d9cfbd`, `#efc0bc`, `#e08a86`, `#cc5752`, `#a3302e`. Missing values have a separate `#c5cbd1` token. These are forecast categories, not a turnout intensity scale.

## Typography and geometry

- UI: `Arial, Helvetica, sans-serif`, base 15px / 1.55. Bold headings use weight 700 and slightly negative tracking. Main title is `clamp(34px, 4.2vw, 56px)`, line-height 1.03, letter-spacing −1.5px: measured 56px desktop and 34px mobile.
- Section headings: 34px / 1.08; compact card headings: 26px / 1.1. Typical small UI is 12–13.5px. Controls use bold 12px, padding 9px 12px, min-height 34px; compact toolbar variants are smaller.
- Reading prose: `Georgia, 'Times New Roman', serif`, typically 17px / 1.6, max-width 840px. It gives methodology and supporting prose a different rhythm from numeric UI.
- Metadata: `Consolas, 'Courier New', monospace`, mostly 11px / 1.4. The reference uses uppercase kickers and tracked metadata. Do not add more of these just to imitate the brand; the dashboard user's explicit preference is fewer secondary labels.
- Desktop centered width 1224px, giving x=108 at a 1440px viewport. General CSS is `width:min(1224px, calc(100% - 56px))`; measured mobile inner width 358px with 16px edges.
- Desktop masthead is 64px high, sticky above 1000px; wordmark 19px bold. Mobile masthead is 89px, portrait/identity on one row and a horizontally scrolling navigation on the next. Desktop links are 12px, weight 600, with an underline for current/hover.
- Two-column top cards: 16px gutter, 604px measured width each; white, 0px radius, 20px 22px 18px padding, 4px upper border. Active upper border uses ink.
- Explorer: white bordered two-column workspace (1.25fr / 1fr), no gap; left map toolbar and right detail rail separated by a rule. 18–22px panel padding. On mobile the content stacks.
- Major analysis sections are separated by a 3px burgundy top rule and ~22px top padding. Other chart surfaces use a 1px blue-grey border. Typical spacing tokens: 4, 8, 12, 16, 24, 32, 48px.
- Tables use ink header rows with white text, thin blue-grey row rules, blue tinted hover/selection; no radius.
- Motion: map fill 250ms, opacity 350ms, map/tile transforms 600ms with `cubic-bezier(.3,.7,.2,1)`. Reduced motion disables transitions. Selection emphasizes a white halo and ink outline while dimming nonselected areas.
- Keyboard focus: 3px `#111` outline, 3px offset.

## Assets and font availability

The only imagery is a square Jackson Hannan portrait provided as an inline JPEG CSS background. It is not exposed as an `<img>` or linked asset; the page has no content photos. The measured identity portrait is 40×40px, square, background-size cover, background-position 50% 34%, 1px pale burgundy border. A 451×443 JPEG has been extracted unchanged to the ignored evidence directory. Parent can copy that existing user-site asset into the dashboard if desired; do not link to the entire inline base64 rule.

No `@font-face`, external font link, or font/image network request was present. The computed stacks above use system fonts and need no downloaded font files. Chromium on this Linux host resolved Arial to Liberation Sans and Georgia to Liberation Serif; monospace fell back to the locally installed iA Writer Mono S. That fallback is environment-specific, not a requirement to bundle it. No font license or redistribution permission was asserted by the site. Keeping the declared system stacks avoids adding a font distribution dependency.

## Suggested dashboard adaptations (design judgment)

1. Reuse the exact paper/burgundy/ink identity, rectangular controls, white chart panels, strong title hierarchy and selective burgundy section rules. Keep the current navigation and chart semantics; the reference's many forecast labels are not a reason to add turnout copy.
2. Use Jackson Hannan as the consistent masthead/export signature and retain the distinctive square portrait only where useful. A small portrait makes identity more recognizable than a second logo graphic.
3. Preserve existing turnout and missing-data color meaning. Use the reference Democratic/Republican colors for partisan identity while retaining a distinct diverging matrix intensity scale and explicit absent-data neutral.
4. Export images should look like pieces of this same publication: pale paper margin, burgundy brand stripe, bold sentence-case chart title, white chart canvas, short date/cohort line, and a legible X/LinkedIn author footer. Avoid scaling the entire dashboard UI into a social image.
5. Mobile should adapt spacing and stack chart/detail panes rather than shrink labels. The reference mobile page is extremely long because its full district table expands; do not copy that weakness into the dashboard.

## Reproducible evidence

All inspection scripts and raw evidence are in the ignored `analysis/brand-refresh/reference/` directory:

- `desktop-viewport.png`: 1440×1080 first screen, best immediate reference.
- `desktop.png`: full rendered desktop page, 1440×5819.
- `mobile-first-view.png`: 390×1250 top crop.
- `mobile.png`: full rendered mobile page, 390×14832.
- `desktop.json`, `mobile.json`: computed styles, bounding boxes, images, metadata and full CSSOM.
- `styles.css`: concatenated live CSSOM (includes the existing inline portrait).
- `fonts.json`: Chromium platform-font and portrait measurements.
- `portrait-reference.jpg`: extracted unchanged original portrait.
- `capture.py`, `fonts.py`: browser capture scripts. Run with `uv run --with playwright python …`; the optional crop extraction used Pillow.
