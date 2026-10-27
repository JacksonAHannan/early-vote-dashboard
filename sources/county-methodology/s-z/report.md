# S–Z county methodology audit

Pinned snapshot: **2026-10-27 16:30:35 UTC**, through October 26, 2026. All **53 assigned counties** were reviewed individually across **1,043 retained aggregate observations**. No raw voter rosters, identifiers, names or addresses were saved.

The ledger is `analysis/county-methodology/s-z/ledger.json`. Each row records dated official URLs and hashes, turnout counts, native IDs outside the reference, independent control differences, local quarantine, coverage and classification. `screen.py` reproduces the baseline screen; `review-notes.json` retains the fresh findings and adjudication.

## Material findings

- **Tarrant: a proved methodology correction.** The existing cumulative anchor omits the actual cutoff-day SOS file from its alias evidence. Adding October 26 changes 24 label target sets and contradicts 20 previously unique aliases. Twenty-eight formerly published native cells, representing 19,041 previously published votes, now require quarantine. Assigning individually proved native targets then restores 15 cells relative to label-only resolution using the same eight sources. The corrected result has 461 native cells versus the stale 473. This is an accuracy correction, not a reason to retain invalidated aliases.
- **Tarrant conservation:** 373,100 raw county rows equal 206,441 surviving native rows + 592 explicit unknown identified rows + 166,020 withheld identified rows + 47 invalid identity rows. The native ZIP and independent control hashes and timestamps are unchanged. The observation is cumulative only; daily differencing and backward allocation remain disabled. Parent owns production integration.
- **Seven fresh SOS rechecks confirm publication gaps.** Webb and San Patricio October 26 return empty HTTP bodies. Schleicher and Sherman October 26 contain only 6 and 7 mail records. Starr and Swisher October 23 contain only 10 and 4 mail records. Wichita October 26 still reports only 2 in-person voters beside 147 mail records. None of these responses certifies zero in-person turnout.
- **Taylor remains unadmitted.** Thirty-four historical codes end in a literal period; all 34 current native codes match the current source. The official archive currently omits November 2024 native results. Current sample ballots use substantive suffixes, so global punctuation stripping would be unsafe. No explicit official historical-code proof was found in this bounded pass.
- **Wood remains unadmitted.** The county home links the canonical elections subdomain; the obsolete `/page/elections` path returns 404. Fourteen parent voting precinct maps exist, but no official 2024 decimal subdivision to native precinct crosswalk was found. Decimal labels remain verbatim.
- **Upton remains unadmitted.** The current county page lists sample ballots for `1-1`, `1-5`, `2-2`, `2-6`, `3-3` and `4-4`. Its November 2026 roster section has no linked files. This does not prove membership of SOS codes 1–7. Staged geographic inputs already exist; no rebuild is needed.

## Individual county dispositions

| County | Day1 missing / native | Day8 missing / native | Missing/tied presidential groups | Mixed groups | Disposition |
|---|---:|---:|---:|---:|---|
| Sabine | 1 / 8 | 2 / 8 | 0 | 0 | real_source_gap |
| San Augustine | 0 / 11 | 1 / 11 | 0 | 0 | real_source_gap |
| San Jacinto | 0 / 11 | 0 / 11 | 0 | 0 | healthy |
| San Patricio | 0 / 27 | 27 / 27 | 0 | 0 | real_source_gap |
| San Saba | 0 / 6 | 0 / 6 | 0 | 0 | healthy |
| Schleicher | 0 / 4 | 4 / 4 | 0 | 0 | real_source_gap |
| Scurry | 1 / 11 | 4 / 11 | 0 | 0 | real_source_gap |
| Shackelford | 0 / 7 | 5 / 7 | 2 | 0 | real_source_gap |
| Shelby | 0 / 14 | 1 / 14 | 0 | 0 | real_source_gap |
| Sherman | 1 / 7 | 7 / 7 | 0 | 0 | real_source_gap |
| Smith | 0 / 66 | 1 / 66 | 4 | 5 | real_source_gap |
| Somervell | 0 / 4 | 0 / 4 | 1 | 0 | real_source_gap |
| Starr | 0 / 14 | 14 / 14 | 10 | 0 | real_source_gap |
| Stephens | 0 / 5 | 0 / 5 | 2 | 0 | real_source_gap |
| Sterling | 0 / 4 | 2 / 4 | 2 | 0 | real_source_gap |
| Stonewall | 0 / 4 | 4 / 4 | 0 | 0 | real_source_gap |
| Sutton | 0 / 4 | 0 / 4 | 0 | 0 | healthy |
| Swisher | 0 / 7 | 7 / 7 | 0 | 0 | real_source_gap |
| Tarrant | 68 / 707 | 328 / 707 | 67 | 23 | provenfix |
| Taylor | unadmitted | unadmitted | staged | staged | rejected: unproved source/native IDs |
| Terrell | 0 / 4 | 3 / 4 | 2 | 0 | real_source_gap |
| Terry | 0 / 6 | 1 / 6 | 0 | 0 | real_source_gap |
| Throckmorton | 0 / 5 | 4 / 5 | 0 | 0 | real_source_gap |
| Titus | 5 / 19 | 8 / 19 | 2 | 0 | real_source_gap |
| Tom Green | 0 / 35 | 0 / 35 | 2 | 0 | real_source_gap |
| Travis | 24 / 308 | 33 / 308 | 1 | 7 | real_source_gap |
| Trinity | 0 / 20 | 7 / 20 | 8 | 0 | real_source_gap |
| Tyler | 0 / 17 | 12 / 17 | 0 | 0 | real_source_gap |
| Upshur | 0 / 19 | 0 / 19 | 1 | 0 | real_source_gap |
| Upton | unadmitted | unadmitted | staged | staged | rejected: unproved source/native IDs |
| Uvalde | 0 / 14 | 1 / 14 | 0 | 0 | real_source_gap |
| Val Verde | 1 / 17 | 4 / 17 | 17 | 0 | real_source_gap |
| Van Zandt | 0 / 18 | 0 / 18 | 2 | 0 | real_source_gap |
| Victoria | 0 / 35 | 1 / 35 | 0 | 0 | real_source_gap |
| Walker | 0 / 18 | 8 / 18 | 5 | 0 | real_source_gap |
| Waller | 1 / 20 | 2 / 20 | 2 | 0 | real_source_gap |
| Ward | 0 / 8 | 2 / 8 | 0 | 0 | real_source_gap |
| Washington | 1 / 19 | 3 / 19 | 0 | 0 | real_source_gap |
| Webb | 0 / 78 | 78 / 78 | 23 | 0 | real_source_gap |
| Wharton | 0 / 12 | 1 / 12 | 0 | 0 | real_source_gap |
| Wheeler | 0 / 4 | 0 / 4 | 0 | 0 | healthy |
| Wichita | 1 / 40 | 40 / 40 | 0 | 0 | real_source_gap |
| Wilbarger | 0 / 4 | 0 / 4 | 1 | 0 | real_source_gap |
| Willacy | 1 / 17 | 3 / 17 | 2 | 0 | real_source_gap |
| Williamson | 1 / 177 | 5 / 177 | 13 | 3 | real_source_gap |
| Wilson | 0 / 13 | 0 / 13 | 4 | 0 | real_source_gap |
| Winkler | 0 / 5 | 5 / 5 | 0 | 0 | real_source_gap |
| Wise | 0 / 28 | 0 / 28 | 1 | 0 | real_source_gap |
| Wood | unadmitted | unadmitted | staged | staged | rejected: unproved source/native IDs |
| Yoakum | 0 / 6 | 0 / 6 | 0 | 0 | healthy |
| Young | 0 / 8 | 1 / 8 | 0 | 0 | real_source_gap |
| Zapata | 2 / 7 | 2 / 7 | 1 | 0 | real_source_gap |
| Zavala | 0 / 6 | 5 / 6 | 0 | 0 | real_source_gap |

`real_source_gap` includes retained turnout publication gaps and separately labelled presidential-reference gaps. It does not imply a fresh remote download failed for all such counties. The JSON row identifies which case applies and whether a fresh source check was made. `healthy` means all admitted geographic groups are paired on all eight dates and the only potential exclusion is the documented mixed-band rule.

## Verification

The five Tarrant identity tests first ran against the existing label-only implementation and produced three failures. After the scoped candidate change, all five pass. They cover individual exact native targeting, unmatched-row whole-cell quarantine, foreign targets participating in ambiguity, invalid identity quarantine, and cross-date duplicate identities.

Five ledger checks verify the exact assignment and pinned baseline hash, source provenance and next actions for every county, conservation of every published observation, rejection of unproved aliases, and refusal to certify empty or mail-only files as zero.

```sh
python3 -m unittest discover -s dashboard/tests -p 'test_method_s_z*.py' -v
uv run --quiet --with curl-cffi==0.16.3 python sources/county-methodology/s-z/tarrant_identity_anchor.py \
  --through 2026-10-26 --evidence /tmp/tarrant-identity-evidence.json
```

The candidate helper prints only aggregate Daily JSON on stdout. Raw voter data stays in memory. Shared implementation, data, service and publication changes belong to the parent release task.
