# Social image exports

Checked 26 October 2026. Scope: organic X and LinkedIn posts containing exported turnout graphics. First-party guidance below establishes upload and accessibility constraints; the proposed composition is a design recommendation, not evidence of an engagement increase.

Implementation update: the user subsequently requested framing that follows each chart. Exports now retain 1600px width and use 800–2000px height (2:1 through 4:5), fitting the common organic-image limits below. Narrow charts use taller cards; complete chart proportions and metadata remain intact. The initial 1600×1000 default recommendation remains part of this dated research.

## Platform constraints

| Destination | First-party guidance | Consequence for this dashboard |
| --- | --- | --- |
| X, single organic image | Standard aspect ratios from 2:1 through 3:4 display in full. PNG and JPEG are accepted; photos may be up to 5 MB. | The existing 1600 × 1000 export is within the documented range. Keep PNG for crisp chart labels and check the actual encoded file size. |
| LinkedIn, organic photo | Maximum 5 MB; minimum 552 × 276; LinkedIn recommends at least 1080 pixels wide. Accepted aspect ratios run from 3:1 through 4:5; images outside the range are cropped. | 1600 × 1000, square, and 4:5 portrait all fit. Do not crop a complete chart to make a different aspect ratio. |

Sources: [X photo posting](https://help.x.com/en/using-x/posting-gifs-and-pictures), [LinkedIn organic photo sharing](https://www.linkedin.com/help/linkedin/answer/a527229). X's file-size/type details are in the page's expandable FAQ and were available in the search-indexed first-party text; its aspect-range statement is visible in the page body.

LinkedIn's frequently quoted 1200 × 628 landscape recommendation belongs to **paid single-image advertising**. Its paid specifications also list square and vertical formats. Those are not the requirements for Jackson's organic personal-profile posts. [LinkedIn paid single-image specifications](https://www.linkedin.com/help/linkedin/answer/a427596/).

LinkedIn permits multiple photos, but the layout and cropping depend on the first image and subsequent rows. For an independently readable statistical graphic, prioritize a single-image composition and check the platform composer before posting. [LinkedIn organic photo sharing](https://www.linkedin.com/help/linkedin/answer/a527229).

## Evidence for chart presentation

ONS advises concise, front-loaded chart titles of no more than 15 words, describing the main trend where appropriate. Its accompanying statistical description identifies the measure, geography, and period. ONS also says text must remain visible on mobile and desktop, avoid duplicated information, and include only essential footnotes. For exploratory tools where a single trend title would be misleading, a descriptive title is appropriate. [ONS chart text guidance](https://service-manual.ons.gov.uk/data-visualisation/guidance/chart-text).

The Government Analysis Function recommends removing decorative clutter, using restrained gridlines and horizontal readable labels, and judging font sizes after the image is resized. It explicitly does not give one universal minimum font size. Its preferred chart SVG is useful for websites but is not an accepted replacement for the PNG upload needed here. [Accessible chart checklist](https://analysisfunction.civilservice.gov.uk/policy-store/charts-a-checklist/).

WCAG's contrast benchmarks are 4.5:1 for ordinary text and 3:1 for sufficiently large text. The size refers to the eventual presentation, so a large source-canvas font can become small after downscaling. Essential graphical information should achieve 3:1 against adjacent colors. Brand colors do not exempt informative text from contrast requirements. [W3C text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [W3C non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).

## Recommended export composition

These are application-specific design choices, not platform mandates:

- Keep the 1600 × 1000 landscape chart as the reliable default. A 1200 × 1200 square mode can provide a larger feed presence for a simple visual, but only if the chart is reflowed. A portrait preset needs the same treatment. Format alone does not establish better engagement.
- Design a separate social card, rather than screenshotting toolbar controls. Use a clear headline, one compact context line, the visual, and a restrained attribution strip. Keep the visual dominant.
- Give attribution a permanent home outside the data plot: **Jackson Hannan · X @electionsjack · linkedin.com/in/jackson-hannan**. These account strings come from the user; profile ownership or reach was not independently checked. Plain text remains identifiable if logos fail or the image is reposted.
- Put the title and attribution inside a generous canvas inset. A practical starting point is about 4% of the width (64 pixels on a 1600-pixel image); this is a visual spacing heuristic, not an official safe zone or protection from arbitrary third-party crops.
- Preview the completed image at about 390 pixels wide. Judge headings, key labels, annotations, source text, and both social accounts at that size. Increasing pixel dimensions alone will not make a dense matrix legible in a feed. For wide tables, preserve the complete analytical export; offer focused subsets or separate panels when a compact shareable view cannot honestly fit.
- Retain the user's selected county/state, grouping, comparison period, vote method, and daily/cumulative status in the exported context. An image travels without its dashboard controls. Preserve missing-data hatching/labels, paired-cohort qualifications, and any outlier-range note.
- Keep partisan red/blue semantics stable and make brand accents separate from data encodings. Use direct labels or text where color alone would conceal meaning. A dramatic brand treatment belongs around the chart, not behind its marks.
- Freeze animation at its completed state before capture. Confirm fonts and images have loaded, preserve all plotted data, and enforce the 5 MB limit on the encoded PNG. Never reduce readability silently to meet a file-size target.

No reviewed source supports a numerical promise for more likes, impressions, or shares from a particular layout, palette, aspect ratio, or automated caption. Test audience response over time if such a claim is needed.

## Captions and alternatives

Provide a concise, copyable post caption next to the export: the selected comparison, the most useful supported finding if one is explicitly computed, the date, and the live dashboard URL. Do not automatically infer a statewide result from a selected or incomplete cohort, or invent a trend headline from an exploratory scatterplot. A neutral chart title is preferable to a false finding.

Provide a separate copyable image description; embedded PNG text does not populate either platform's ALT field. X allows 1,000 characters and recommends objective, concise descriptions that summarize important image text and complex visuals. LinkedIn offers an ALT control during photo posting. [X image descriptions](https://help.x.com/en/using-x/write-image-descriptions), [LinkedIn ALT control](https://www.linkedin.com/help/linkedin/answer/a527229).

Suggested description structure: chart type; geography and date; daily or cumulative measure; the two election periods and vote methods; what the axes/colors represent; principal supported pattern; material coverage limitation. Keep fuller underlying values and methodology available through the dashboard link. Attribution should not crowd out the statistical description.

## Verification before release

Check one chart, one map, and the densest matrix/table in the export UI. Inspect the actual PNGs at full resolution and phone-feed width. Confirm dimensions, format, byte size, attribution, no clipped rows/labels, visible comparison context, settled animation, and accurate alternate text. Verify that adding the social frame leaves the data and export completeness unchanged. Platform upload/payment/posting tests are outside this research task; no social post was published.

## Retrieval limitation

The configured Firecrawl account reported −1,000 of 1,000 credits remaining. No chargeable call or paid plan was used. Public first-party pages were checked through the available web-retrieval fallback. Platform interfaces can change; the findings describe the documentation available on the date above.
