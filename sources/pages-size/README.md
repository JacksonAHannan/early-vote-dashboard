# Pages publication size repair

Goal: restore room beneath the existing 900,000,000-byte Pages budget by
compressing the same JSON artifacts more effectively. Preserve routes, JSON
content, missing-data rules and the hosting safety check. The user authorized
committing, pushing and redeploying the verified repair on November 1. Collector
changes and new dependencies remain outside scope.

- [x] Inspect workflow failures and current publication. Run 41323982626 collected
  successfully and exported 5,938 artifacts, then rejected 904,659,916 site bytes.
  The first failure, run 41248264178, rejected 903,130,090 bytes. The live
  publication remains generated at 2026-10-31T18:36:44.791004982+00:00.
- [x] Reproduce inefficient artifact compression with a regression check against
  the real tracked Texas county geometry, including lossless decoding.
- [x] Improve compression in the existing publisher and verify focused tests.
  `Compression::default()` replaces `Compression::fast()` at the existing store
  boundary. All five Pages unit tests pass. The new geometry regression failed
  before the fix (943,202 bytes versus the same fast-gzip baseline), then passed
  with exact decoded-byte equality and at least 15% size savings.
- [x] Build the full retained release before and after the change; compare sizes,
  routes and all artifact content hashes. Retain source identity and measurements.
- [x] Run affected Rust checks and browser decompression acceptance. Record
  evidence and the remaining publication step.
- [x] Commit and push the verified repair to the publication branch.
  Commit `3c26aa24681c8643f63bf20298b87a923761dd16` is on `main`.
  Push-triggered publication `41337556957` was superseded by the explicitly
  dispatched source-refresh/publication run `41337574620`. The duplicate
  retained-data build was canceled to avoid exporting twice before publishing
  fresh source observations. Collection and deployment workflow code is unchanged.
- [x] Complete the GitHub publication workflow and refresh official sources.
- [x] Verify the deployed size, timestamp and browser behavior.

Acceptance: the retained release exports below 900 MB with identical response
content and routes; the compression regression and affected checks pass. The
failed run's newer source inputs were not uploaded, so they cannot be replayed
exactly from GitHub. Validate with the latest retained release rather than claim
that a local build is the failed run's exact edition.

## Reproduce the full publication check

Restore a retained release into an isolated copy of the tracked inputs. This
preserves any local aggregate data. The mutable release asset used for this
investigation was updated at 2026-10-31T18:44:43Z, had 34,282,598 compressed bytes
and SHA-256
`67c68594bda6adc4d25b5cbb5773d599631ee80019dc903145171ba97d737266`.
The validated archive restored 1,496 files and 356,818,173 uncompressed bytes.

```bash
mkdir -p analysis/pages-size/retained
git archive HEAD | tar -x -C analysis/pages-size/retained
gh release download data-state --repo JacksonAHannan/early-vote-dashboard \
  --pattern aggregate-state.tar.gz --dir analysis/pages-size
python3 dashboard/scripts/package_pages_state.py \
  --restore analysis/pages-size/aggregate-state.tar.gz \
  --root analysis/pages-size/retained
TURNOUT_PAGES_ROOT="$PWD/analysis/pages-size/retained/dashboard" \
TURNOUT_PAGES_OUTPUT="$PWD/analysis/pages-size/check-$(date +%s)" \
cargo test --manifest-path dashboard/Cargo.toml --release --locked \
  --test pages_size -- --ignored --nocapture
```

The opt-in integration test calls the production exporter and applies the same
entry-point, symlink and total-byte checks as the workflow. Every output must
use a fresh directory, since the publisher reuses existing content-addressed
blobs. Normal Rust tests exercise the real tracked map without release assets.

The full offline Rust suite passed 168 tests (16 opt-in tests ignored), and
all-target Clippy with warnings denied and formatting passed. The Pages state
tests passed 17 tests and the existing JavaScript suites passed 18 tests.
Build logs and detailed checks remain in ignored `analysis/pages-size/`.

## Accepted full-export evidence

Both full production exports passed the opt-in size check using the same restored
release. The original export reproduces the live publication's revision and
compressed-byte count exactly.

| Measurement | Fast gzip (before) | Standard gzip (after) |
| --- | ---: | ---: |
| Full site bytes | 899,684,364 | 544,195,166 |
| Compressed API artifact bytes | 898,055,832 | 542,566,634 |
| Unique artifacts | 5,938 | 5,938 |

The site is 355,489,198 bytes (39.51%) smaller, with 355,804,834 bytes beneath
the existing safety budget. This measures storage reduction; no runtime speed
improvement is claimed.

`python3 analysis/pages-size/check_exports.py` compared all 5,938 decoded artifact
pairs byte for byte (3,486,679,904 uncompressed bytes), checked each filename's
SHA-256 against the payload, and verified identical manifests, file sets and
other static files. Only the gzip encoding and publication size accounting
changed. The shared revision is
`0190040027dfeef113bb7287863daf23e14de9e6d96f34a05ec79db5db759f8b`.

`uv run --with playwright python analysis/pages-size/check_browser.py` passed
22 checks in Chromium 156 with no JavaScript errors. It served the new output
under a repository subpath, initialized all 248 Texas reference counties,
decoded 15 representative API selections including maps and precinct detail,
loaded all four other state dashboards, downloaded Texas CSV content and
checked the 390px layout.

## Deployed verification

The authorized refreshed publication completed successfully in
[run 41337574620](https://github.com/JacksonAHannan/early-vote-dashboard/actions/runs/41337574620),
using repair commit
[`3c26aa2`](https://github.com/JacksonAHannan/early-vote-dashboard/commit/3c26aa24681c8643f63bf20298b87a923761dd16).
Official-source refresh, static export, size validation, aggregate retention and
Pages deployment all succeeded. The refreshed site measured 547,288,407 bytes;
its 5,938 compressed API artifacts occupy 545,659,875 bytes. The workflow retained
1,511 validated aggregate files for subsequent refreshes.

Public verification at 2026-11-01T18:53:06Z confirmed generation timestamp
`2026-11-01T18:44:02.898263752+00:00` and revision
`6dcec119b4b9b99dbbedc3015c943c537775ebd6b8f5d4d86ebcdaa5c9470653`.
The downloaded manifest matches its revision hash, and its compressed Texas data
matches the content-addressed payload hash. The Texas completed-voting cutoff
remains October 30, with all 248 reference counties; a new publication timestamp
does not imply new voting dates.

`python3 analysis/pages-size/check_live_publication.py` passed, as did all 22
checks in `uv run --with playwright python analysis/pages-size/check_live.py`
against the public URL, with no JavaScript errors. Evidence is retained in
`analysis/pages-size/live-publication.json` and `live-browser.json`.
Repair, refreshed deployment and live verification are complete.
