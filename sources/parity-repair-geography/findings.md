# Six unadmitted counties: bounded geographic and source-scope review

Reviewed November 1, 2026. **No additional county can yet be admitted safely.** Gregg, Guadalupe, Hill, Taylor, Upton and Wood remain outside the paired precinct universe. This pass adds primary-source evidence, a rejected-candidate scope test, and independently useful current native observations; it adds no guessed aliases, turnout allocations or implicit zeros. Production dashboard code/data was not changed.

The existing isolated prerequisite bundle already supplies disjoint old/new native geographic partitions, maps, Census and place data for all six. Rebuilding those assets does not resolve missing source-label relationships or incompatible ballot categories. The admission gate is evidence of ordinary early in-person participation in both years on a native common geography.

## Guadalupe: certified native canvass is the wrong participation scope

The fresh [official 2024 precinct canvass](https://www.guadalupetx.gov/upload/page/0210/docs/2024/11-5-24-GC_General-PrctbyPrct.pdf) has exactly **76** native precinct statistics blocks, matching every staged 2024 native ID. Its Ballots Cast rows conserve all modes: **85,606 total = 14,959 Election Day + 67,411 Early Voting + 3,236 Absentee**. A separately published [official county summary](https://www.guadalupetx.gov/upload/page/0210/docs/2024/11.5.24-GC_General-Official_Results.pdf) agrees exactly. There are no zero/unknown/outside precinct statistics blocks to remove to explain the difference.

However, the signed [official reconciliation](https://www.guadalupetx.gov/upload/page/0210/docs/2024/Official_Totals_Reconciliation.pdf), visually verified after OCR, separately reports:

| Reconciliation quantity | Count |
|---|---:|
| Early voting in-person voters | 67,291 |
| Early voting ballots counted | 67,242 |
| Election-day ballots counted | 14,914 |
| Provisional ballots submitted / rejected / counted | 1,168 / 954 / 214 |
| Total ballots counted | 85,606 |

The native canvass mode differences are **67,411 − 67,242 = 169** early and **14,959 − 14,914 = 45** election-day; **169 + 45 = 214**, exactly the separately counted provisional total. This is strong aggregate evidence that the native canvass redistributes accepted provisionals into its early/day categories. It cannot serve as an ordinary participation baseline. Nor can the 169 be subtracted from arbitrary native precincts. The county's ordinary early voters (67,291), ordinary early counted ballots (67,242), canvass Early Voting (67,411), and SOS administrative early cumulative (66,840) are distinct observations.

For provenance: precinct PDF SHA-256 is `8b4eb4c3d8f98988fe3ac1ed38f4b4ae2819667c903af1163e64c505ba81fd58`; reconciliation SHA-256 is `e65c77e3b58a85c5359623d6470e2dcb30ffa60597e993120b1bf860b6377bd0`. See `analysis/parity-repair/geography/source-facts.json` for the fresh URL/hash/time record for each document. The arithmetic and ordinary-versus-provisional distinction, not equality with SOS, determines rejection.

Fresh twelve-day 2026 SOS collection does independently establish **64 explicitly observed native cells / 51,313 cumulative native votes** before any historical admission. Every daily file passes unique in-file and cross-date identity checks; foreign labels remain verbatim, no source is marked complete and no absent precinct is filled as zero. There are 78 native current precincts and 76 common groups in the staged geometry. A hypothetical canvass substitution would pair 64 precincts, but **that is rejected diagnostic coverage, not newly admitted coverage**.

The rejected alternative is physically isolated at `analysis/parity-repair/geography/staged/guadalupe-UNAPPROVED-canvass-alternative/`. Its proof has `admission_approved:false`; the native canvass file is named `UNAPPROVED-2024-canvass-alternative.json`, and candidate geography is named `candidate-reference-NOT-admitted.json`. It must not be merged into ordinary participation data. `stage_guadalupe.py` reproduces source parsing/current observations and preserves the failed scope gate.

Three avenues were checked: the previously retained May 2025 boundary order (which proves the 208/233 and 415/402 split unions but no historical four-digit aliases); current official election/history/maps pages and certified native reports/reconciliation; and official historical roster/participation-source discovery. The last did not produce a native ordinary 2024 residence roster or per-native provisional exclusion. Required evidence: such a roster or an explicit historical subdivision/native dictionary plus method-compatible participation controls.

## Gregg: current county roster exposes genuine native precincts

The [official October 19, 2026 voter turnout report](https://greggcountyvotes.gov/wp-content/uploads/2026/10/2026-10-19-Voter-Turnout.pdf) has an explicit **Precinct** field containing `01` through `21`, unlike the detailed subdivision codes in the SOS source. Its native field is separate from Polling Place. The anonymous first-day counts are saved in `gregg-roster-schema.json`; PDF SHA-256 `755349cd062e92c545abcb6b63c26c2bece1229f04f0f534690c94ea0fe02cbb`. The roster itself and all voter identifiers remained in memory. This provides a useful current native-source lead without truncating SOS codes.

The [official 2024 election page](https://greggcountyvotes.gov/upcoming-elections/2024-november-election/) has no historical daily-roster links. A bounded metadata request to the official WordPress media endpoint returned **401** anonymously; one direct historical filename patterned after the current reports returned **404**. This is not proof the records do not exist, and no authentication or account changes were attempted.

The county-linked [official 2024 Clarity XML](https://results.enr.clarityelections.com/TX/Gregg/122313/355603/reports/detailxml.zip) contains the 21 native reporting precincts and **46,974 all-mode ballots**, but no explicit native in-person turnout-by-method dictionary or SOS subdivision relationship. Its candidate Early vote totals cannot substitute for turnout; under/over votes are supplied across modes, not separately by early method. The current roster therefore cannot yet be paired to an ordinary native historical baseline.

Three avenues were checked: official native precinct maps; native current/historical roster discovery (including the bounded media attempt); and official Clarity native turnout/dictionary data. Required evidence: an ordinary native 2024 residence roster or explicit 2024 subdivision-to-native code dictionary. If acquired, the current county-native report offers a recurring adapter route. Collecting all twelve current county reports was deferred because historical proof remains absent.

## Hill: ballot style is not a residence-precinct proof

The current [official final-period history report](https://www.co.hill.tx.us/upload/page/7619/docs/2026/Voter%20History%20Report%2010.19-10.30.pdf) now has 99 pages, but its fields remain Name, State ID, Address, Polling Place, Time and **Ballot Style**. There is no residence precinct field. Source SHA-256 `21ef6c5dd048e36852d242c1ef55bb2cfa01308f68ff4d5913a2dae7534c90e8`; only sanitized schema metadata was saved.

The [official sample ballot for precincts 1, 9 and 10](https://www.co.hill.tx.us/upload/page/7619/docs/2026/Sample%20Ballot%20Pct%201%209%2010.pdf) explicitly groups multiple precincts on one ballot design. It supplies no bijective ballot-style/residence-precinct table. Similar sample-ballot links group 2/4/8, 3/7/11/12 and 5/6/13. Matching a ballot style number to a same-number native precinct would be an unsupported inference. The native map universe remains 13 precincts.

Three avenues were checked: updated roster schema, official sample ballots, and retained native geographic prerequisites/map links. Required evidence: an explicit current residence field, or a complete official ballot-style/native-precinct equivalence with ambiguity retained. No current source rows were assigned using polling place, address or ballot style.

## Taylor: new documents still do not explain the literal terminal period

Fresh [Document 4601](https://www.taylorcounty.texas.gov/DocumentCenter/View/4601) is an eight-page scanned cumulative November 5, 2024 results report. First-page OCR verifies county-level modes, not native precinct turnout. [Document 4602](https://www.taylorcounty.texas.gov/DocumentCenter/View/4602) is an election reconciliation form. Neither defines the 34 historical SOS labels ending in a literal period. The refreshed [official election archive](https://www.taylorcounty.texas.gov/549/Archived-Election-Results) still does not link a November 2024 native precinct report. The official 2024 election notice was located in targeted primary-source search, but does not provide verified historical label-equivalence evidence for admission.

The retained native geography/current source labels contain 34 precincts `101` through `409`, while every historical reported label is `101.` through `409.`. A formatting transformation would cover the labels, but coverage alone is not proof that a terminal literal period is merely cosmetic. No punctuation alias was added. Three avenues were checked: official archive/direct result documents, official notice/primary-source discovery, and retained code/universe diagnostics. Required evidence: an explicit historical source/native code dictionary, or a same-election native ordinary report that independently establishes those associations.

## Upton: newly published rosters introduce real decimal codes

The refreshed [official elections page](https://www.co.upton.tx.us/page/upton.elections) now advertises all twelve November 2026 daily roster PDFs, unlike the earlier review. The [first current report](https://www.co.upton.tx.us/upload/page/6648/Monday%20Oct%2019.pdf) has State ID, Polling Place, Time and **PCT**, but its actual PCT values include `3.9`, `1.4`, `4.18`, `6.11`, `6.1`, `2.3` and other decimal labels. The [first historical report](https://www.co.upton.tx.us/upload/page/6648/1021%20PDF.pdf) uses integer PCT 1–6. Neither matches the current map's six full native labels `1-1`, `1-5`, `2-2`, `2-6`, `3-3`, `4-4` directly. Sanitized metadata only was retained; raw voter content remained in memory.

The official sample-ballot links use those six full native labels, but inspected sample ballots supply no complete decimal/subdivision/native dictionary. The retained old/new geographic partition is useful once a source namespace is proved; it cannot supply that proof itself. Three avenues were checked: new native-roster schema, official election notice/sample-ballot labels, and staged native geographic relationships. Required evidence: an explicit decimal/electoral-code crosswalk or an ordinary dated source with actual full native codes. No integer, decimal or hyphen truncation was applied.

## Wood: a genuine extra reporting subdivision reinforces the alias limit

The [official county election results page](https://elections.mywoodcounty.com/election-information/election-results/) links the official Clarity election directory. The discovered [2024 native XML](https://results.enr.clarityelections.com/TX/Wood/122311/358125/reports/detailxml.zip) has **15** reporting units and **24,503 all-mode ballots**: the 14 native parent IDs plus a separate `42 - UHISD` reporting unit. It contains candidate vote methods but not a native ordinary early-participation total that can replace the historical decimal source labels. Candidate sums and all-mode turnout were not used as early turnout.

The historical SOS labels (`11.0`, `11.1`, …) still have no explicit county-published relationship to native 11–44. The separate `42 - UHISD` unit demonstrates that reporting subdivisions can be real. Neither deleting decimals nor coalescing its school suffix without proof is acceptable. Three avenues were checked: official parent maps, official results/directory, and aggregate native reporting-unit/turnout dictionaries. Required evidence: the complete official 2024 split/native dictionary or a native ordinary 2024 residence roster.

## Artifacts and checks

`analysis/parity-repair/geography/source-facts.json` records fresh official URLs, retrieval times, hashes and saved public aggregate/metadata files. Separate roster-schema facts contain only field names and anonymous precinct counts; no raw roster was saved. `sources/parity-repair-geography/raw/` contains public aggregate election reports, sample ballots, landing pages, Clarity aggregate XML/ZIP and public application/metadata files. Reconciliation/ballot OCR images contain no voter records.

`qualify_geography.py` verifies all six staged native partitions and geographic join keys; checks the saved official aggregate hashes; reproduces the 76-row Guadalupe mode totals and provisional arithmetic; and enforces the failed scope gate plus **zero approved county additions**. It records pending proof per county in `analysis/parity-repair/geography/qualification.json`. These checks concern candidate evidence and rejection correctness; no production paired-precinct increase is claimed.
