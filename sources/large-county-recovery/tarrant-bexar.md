# Tarrant and Bexar precinct coverage audit

Audited 2026-10-27. Official voter downloads were processed only in memory; retained artifacts contain precinct aggregates, source URLs and hashes, geographic labels, and counts of identity joins. The county PDFs below were not saved because they contain voter records. The Tarrant final results PDF is an aggregate election-results publication.

## Approved recovery: Tarrant 2024 explicit zero precincts

The [official final November 5, 2024 precinct report](https://www.tarrantcountytx.gov/content/dam/main/elections/2024/1124/reports/precinct.pdf) gives a repeated native-precinct header of the form `1001 1,362 of 1,918 registered voters`. This is the all-method ballot turnout header, above the individual contest tables. It is not the presidential valid-vote total. All 844 native precinct headers agree across their repeated pages. Their ballot totals sum to **828,544** and registrations to **1,299,023**, exactly the printed county headline; the report says `Official Results`, `11/5/2024`, and `844 of 844 = 100.00%`.

**151 native precincts have exactly zero final ballots cast across all methods.** All 151 are exact old-reference IDs, and every existing presidential return for those IDs is also zero. A zero final total gives an exact zero upper bound for each of the 12 early-voting dates, October 21–November 1, 2024. This does not move positive final totals into an earlier date, infer zeros for omitted labels, or certify the rest of the county complete.

The source was re-downloaded on October 27 and matches the retained final PDF byte-for-byte: **41,164,781 bytes**, SHA-256 `b06a673810043ad9d222e1f8f21eaf9b132d0ee9848c706c53a2a9091b3a9518`.

Reproducer:

```sh
python3 dashboard/scripts/certify_tarrant_2024_zeros.py \
  --pdf ../texas-early-vote-2026-11-03/sources/precinct-expansion/native-returns/tarrant/precinct.pdf \
  --output analysis/large-county-recovery/tarrant-bexar/tarrant-2024-zero-certificate.json
```

Against the pinned published coverage, adding only these proved historical zeros restores **52 groups / 71 current precincts on Day 1**; Tarrant's missing current precincts decrease from 139 to 68. Days 2–5 recover 51 groups / 68 precincts; Day 6 recovers 50 / 67; Day 7 recovers 49 / 66. Day 8 needs a current dated source independently of this historical correction.

The [current Tarrant county in-person ZIP](https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_voting_in_person_report.zip) was checked again. Its 35 actual columns have no voting date. Its six-digit ballot-split labels cannot be truncated or its undated cumulative turnout allocated backwards to fill daily holes.

## Bexar: source is available, but its scope is not approved for substitution

The new official [Bexar Elections early-voting page](https://elections.bexar.gov/166/Early-Voting) links [Unofficial Branch Daily Register / EV Rosters, folder 245](https://elections.bexar.gov/DocumentCenter/Index/245). Its public DocumentCenter metadata API lists dated county PDFs titled `Early Vote Ballots ... November 3, 2026 General Election`:

| Date | Document ID | PDF SHA-256 |
|---|---:|---|
| 2026-10-19 | [1953](https://elections.bexar.gov/DocumentCenter/View/1953) | `47b374eeb0f1ca46fffa91aeff60c9674eef3f921d2a8230a4ba7e05fc36c78e` |
| 2026-10-20 | [1957](https://elections.bexar.gov/DocumentCenter/View/1957) | `c18fac5a9b21b91707d763372bfedfddac7b83513ff5e757f0ccd936f782ddef` |
| 2026-10-21 | [1958](https://elections.bexar.gov/DocumentCenter/View/1958) | `7434c5875432502acec2838cf0c8ba673e7cdc5319a6ea34e44b369b44fdabf2` |
| 2026-10-22 | [1961](https://elections.bexar.gov/DocumentCenter/View/1961) | `1aae2962a9c644b531d96fef98c76e8d2765bb253aaccb08de86ec6b3b81f9f6` |
| 2026-10-23 | [1962](https://elections.bexar.gov/DocumentCenter/View/1962) | `14de016501da239409c1f298917ba6196e6e446d1fda0d86d9f24c6ab21c4253` |
| 2026-10-24 | [1965](https://elections.bexar.gov/DocumentCenter/View/1965) | `a33deaff5d4a36fa2e30504c9b8e3f8db2749d6e95a7dc53847689cef0b55a30` |
| 2026-10-25 | [1969](https://elections.bexar.gov/DocumentCenter/View/1969) | `132cd70f32ae64efebe4ad619b67a558a57f603b3e4069db2cba7a5755975068` |
| 2026-10-26 | [1972](https://elections.bexar.gov/DocumentCenter/View/1972) | `7fd5dab71d5986aff7622f75381c9b3baf52c0180df54e8e13e86eb011cc81ac` |

The PDFs contain Name, VUID, Polling Place, and residence Precinct (`P ####` or `S ####.##`). They do not provide a limited/provisional/ordinary ballot flag. The audit checks every voter-shaped line, quarantines residence cells with unusable identifiers, and also quarantines cells implicated by an identity appearing in multiple dated county PDFs. Names and identifiers are not written to disk.

**The county feed must not replace the ordinary historical SOS series.** For Day 1, the original county PDF has 42,776 voter-shaped rows, while the SOS in-person file has 42,070 included voters. Before cross-date quarantine, 751 county identities are absent from SOS and 56 SOS identities are absent from the county file. Thus the county roster is not a demonstrated complete superset of ordinary SOS votes, and the ballot-method discrepancy is unresolved. Some later dates also contain conflicting native residence labels for the same independently joined identity. The PDF is useful evidence of source availability, not authority to declare missing native rows zero.

Across the eight dated PDFs, 1,100 raw county labels have same-date SOS ID evidence. Only 1,046 have exactly one native target across the whole audit; 54 have conflicting mapped targets and remain unresolved. The parser never picks a majority target. Broader county observations in the audit bundle are explicitly marked **unqualified for comparison** and must not be fed to production as approved Daily observations.

One narrowly proved correction preserves the SOS scope: on October 19, a single SOS voter has an unknown label `266` and the same voter appears in the county PDF in `S 1046.05`. That county split has **155 other same-date native-ID joins across the audit, all to native precinct 1046**, and no conflicting native target. Moving only that one already-included SOS vote from unknown `266` to known `1046` preserves the daily SOS total and every other count. The original SOS source SHA is `c870f6cac72d37261c5f55041a6fb1828d99d3678236ccb8014b55ca0ddd0e45`; replacements must remain pinned to that reviewed original. This fixes a label, but does not complete any additional Day 1 geography group because 1046 was already observed.

The October 26 SOS file was empty at audit time. The county's dated October 26 PDF exists, but the unproved ballot-method scope prevents silently substituting its counts into the 2024 ordinary-vote comparison. This is a source/methodology limitation, not evidence of zero turnout.

Reproduction and checks:

```sh
uv run --quiet --with curl-cffi==0.16.3 python dashboard/scripts/collect_bexar_native_recovery.py \
  --output analysis/large-county-recovery/tarrant-bexar/bexar-native-audit.json
python3 -m unittest discover -s dashboard/tests -p test_large_county_native_proofs.py -v
```

The opt-in Bexar audit downloads and parses sources through anonymous process pipes and writes only aggregate output. Nine focused tests cover blank and conflicting identity quarantine, uniqueness across mapped target evidence, retaining already-native SOS labels, unknown-label repair, missing/final-election checks, county conservation, and refusal to turn positive or absent final precinct counts into zeros. Production integration and independent end-to-end coverage verification belong to the parent release task.

## Tarrant October 26 cumulative-anchor candidate

A later bounded check found useful exact-cutoff evidence for the undated county ZIP. The fresh roster has **373,100 rows**, equal to the separately published county **Early Voting In Person Totals** cumulative sum through October 26 (Day 8 = 49,556). The PDF is stamped 8:58:11 PM; its SHA is `a4dfbfb3267569e4e6a6642d7c2465461d84a9380e3102e254337ec8940b267a`. The official ZIP's HTTP Last-Modified is `2026-10-27 02:03:31 GMT` (October 26 at 9:03 PM Central), and its sole member is timestamped October 26 at 9:00:20 PM. This can support an **October 26 cumulative-only** cutoff after separate scope approval; it cannot assign any positive vote backwards to a specific earlier date or derive a Day 8 daily difference against a differently sourced prior cumulative number.

The archive contains 373,053 distinct valid nonblank county IDs and SOS IDs, with no nonblank identity repeats. Another 47 rows lack both identifiers, across 38 reported six-digit county labels. These affected labels must remain unknown unless independently mapped. The six-digit-to-native audit uses exact same-voter SOS joins from available dates, requiring one unique native target per raw county label over the full audit. It produced 611 safely labelled positive native precinct cells; conflicting and unproved labels remain explicit unresolved aggregate categories, and no county-wide completeness is granted. The empty October 26 SOS response supplies no identity proof and is never called zero.

`dashboard/scripts/audit_tarrant_cumulative_anchor.py` writes the anonymous candidate plus alias counters, source hashes, and ZIP timestamp to `analysis/large-county-recovery/tarrant-bexar/tarrant-cumulative-anchor-candidate.json`. It is an audit candidate requiring independent cutoff/scope approval. The parent release assigned a separate agent to implement any production adapter and prevent unsupported same-day differencing.


Root release decision: the one-vote Bexar `266 → 1046` candidate remains audit-only. Its native-filtered alias evidence does not prove that the contradictory foreign SOS target is erroneous rather than an unrepresented precinct. The same strict all-target ambiguity rule used by the Tarrant anchor applies. Neither the Bexar candidate nor its broader unqualified county roster is integrated into comparisons.
