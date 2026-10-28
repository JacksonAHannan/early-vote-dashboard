# Recurring SOS download reliability — October 28, 2026

## Scope and finding

The production source URL already follows the current official site's download
method, including `EVR_EARLYVOTING`, election 53815, the requested voting date,
and full county name/ID. The official frontend JavaScript method and hash are
retained in `official-endpoint-proof.json`. No alternative date, upload-date
shift, or precinct-label truncation is appropriate.

A fresh read-only probe of every **248 admitted counties** for **October 27**
returned:

| SOS response | Counties |
|---|---:|
| Valid in-person roster | 62 |
| Mail-only roster | 121 |
| Empty successful HTTP response | 65 |
| Transport, CSV schema, identity, or method validation failure | 0 |

All response payloads and identity sets remained in process memory. The retained
`sos-20261027-availability.json` contains only source URLs, timestamps, response
headers, hashes, method totals, and aggregate validation counts. The reproducible
`probe_sos.py` performs no source/cache mutations and stores no voter records.

Compared with the pinned 15:01 UTC production baseline, Fort Bend's 2,105
in-person records are newly available. Every other valid in-person SOS source
already had a retained report. Seven counties additionally had dated native
county sources despite unavailable state in-person rosters: Dallas, Hays,
Montgomery, Tarrant, Travis, Waller, and Washington. This is evidence for keeping
native alternatives in the recurring pipeline, not for replacing all county
reports with a state-only source.

The independently fetched official county summary reports 61 positive daily
in-person counties and 193 zero-or-unreported counties. Fort Bend's per-county
roster has appeared ahead of that summary's corresponding control. A newly
available positive roster must therefore remain incomplete until independently
qualified; a zero county summary or empty/mail-only roster must never be
converted into precinct zeros. Current response headers explicitly specify
`no-cache, no-store, max-age=0, must-revalidate`; the observed broad gap is not
explained by a cached previous HTTP response.

## Permanent production fix

`dashboard/src/fetch.rs` previously classified HTTP 429 as a hard failure,
immediately abandoning a county/date without either retry or compatible
transport. It now uses the existing bounded retry/fallback path for rate limits,
while retaining hard failures for other client errors.

`dashboard/scripts/transport.py` previously made exactly one compatible HTTP
attempt. A gateway failure or interrupted body at that final transport boundary
could therefore discard the new date for that hourly run. It now retries the
same GET/POST, form fields, URL, and headers once after a short delay for 429,
server errors, and curl request/body failures. A successful complete body is
returned; partial bytes are never exposed. Unposted 202, 400/401/404, and other
hard failures are not retried. Existing host-limited browser handling is
preserved. The Rust caller's existing 240-second child-process limit still
bounds the compatible transport as a whole.

These are recurring request changes, with no hard-coded observation dates,
reviewed hashes, source pooling, parser relaxation, or raw-identity persistence.
They improve transient-failure recovery; they do not manufacture unposted state
rosters. Other agents own native county publication-discovery changes and
hourly scheduler/publication integration.

## Verification

- `cargo test --manifest-path dashboard/Cargo.toml --lib fetch::tests::rate_limit_retries_before_marking_a_county_unavailable`
  failed before the fix with `official download HTTP 429 Too Many Requests`.
- `python -m unittest discover -s dashboard/tests -p test_transport_refresh_reliability.py`
  failed before the fix on gateway/rate-limit/body retries and bounded exhaustion.
  After the fix all **4 tests pass**, including ten GET/POST/status subcases.
- `cargo test --manifest-path dashboard/Cargo.toml --lib fetch::tests` passes
  **11 tests**, retaining body-timeout, truncated-body, gateway, hard-error,
  identity-state, CSV, and deduplication protections.
- `cargo test --manifest-path dashboard/Cargo.toml --test state_refresh_live -- --ignored --nocapture`
  passes the opt-in actual production transport/parser test in **2.87 seconds**
  after compilation. It uses `latest_completed()` rather than a pinned historical
  date and reads Fort Bend, Harris, Bell, and Bexar without writing source data.
- Three existing Georgia transport tests pass, preserving exact request
  forwarding, browser host limits, and memory-only output handling. The complete
  ten-test Georgia suite has one pre-existing failure because the public checkout
  lacks archived `sources/multistate/ga/raw/2d28800a93c4f1dcf5c812398404d3eed20cbaa7860330e38817deb434204e2c.json`;
  no assertions or fixtures were weakened.
- Python compile and scoped Rust formatting checks pass. Root-level checks and
  integrated release verification remain the parent agent's responsibility.

Reproduce the aggregate availability probe:

```sh
uv run --quiet --with curl-cffi==0.16.3 python sources/refresh-reliability/state/probe_sos.py \
  --reference dashboard/data/reference.json --date 2026-10-27 \
  --output analysis/refresh-reliability/state-sos-20261027.json
```

## Fort Bend follow-up: publication timing and per-date failure isolation

At the later live check on October 28, the official landing advertised
`EV_1027.xlsx` (SHA256
`4c6a20f39b7a4f27cba7774374268056b7cd46420a9876944b8243bd402f594a`).
The existing Rust collector independently discovered that link and returned all
nine dates, including **18,666 October 27 votes across 196 native precincts**.
The county's personal-appearance control PDF, revision 11 (SHA256
`0a9db74305902e9c7d8ff4b04a238d595c846ea44082c722799b4b5e9103fef7`),
reported 18,673 for that date. Thus the native source remains an explicitly
incomplete positive subset with seven missing votes, while its current-date
state roster was grossly smaller (2,106 records at the second state probe,
including two foreign precinct labels). The existing native discovery needed
no repair; the earlier missing native date was publication timing. No ad hoc
aggregate was inserted into production caches, and the underfilled SOS file
was not substituted for the richer native publication.

A separate recurring failure-isolation defect was reproduced with a real
`availability_notes` fixture: one out-of-sync dated control aborted all other
valid dates in that refreshed workbook. `dashboard/src/fort_bend.rs` now
withholds each invalid date individually while preserving other validated
positive dates. This does not relax single-date rejection or any shared source
schema, identity, date, host, election, method, daily-control, or cumulative
threshold checks. Available cumulative notes sum only accepted dates; rejected
dates remain missing rather than zero. A date whose own cumulative proof fails
is still withheld.

The new fixture first failed on the previous code with `Fort Bend dated roster
conflicts with a zero/future county control on 2026-10-19`, then passed after
the fix. All **5 Fort Bend unit tests** and `cargo clippy --lib -- -D warnings`
pass. The opt-in `dashboard/tests/fort_bend_refresh_live.rs` uses the actual
latest completed day and current landing/workbook/control sources; its
anonymous aggregate output is kept under `analysis/refresh-reliability/` only
when explicitly requested by environment variable. Before the production fix,
that native fetch already passed with all nine dates. The post-fix live run
also passed with all nine dates in **11.69 seconds**; counts and source hash
were unchanged.
