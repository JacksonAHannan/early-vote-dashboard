# Recurring county collection reliability

The hourly Rust refresh now discovers current county publications, validates each dated observation independently, retries transient transport failures, retains successful dates and preserves the evidence needed to reproduce every comparison. These production changes require no new dated recovery-manifest entries.

- [State downloads and all 248 admitted counties](state/report.md): exact official endpoint/date verification; 62 positive in-person, 121 mail-only and 65 empty responses during the October 27 probe; bounded retries for rate limits, gateway failures and interrupted bodies.
- [Large-county adapters and control continuity](large/report.md): recurring Cameron and Denton discovery, full-label identity proof, Travis/Montgomery date isolation, portable Dallas 2024 controls and correct county-versus-state control priority.
- [Native collector evolution](native/report.md): Collin replacement headers, Panola next-morning exports, next-edition fallback and revalidation of all alias evidence.

The default refresh cutoff remains the last completed Central-time day. A new successful request does not make an empty or mail-only export a precinct report. Missing or contradictory publications remain unavailable and are retried on later hourly runs. No source age, polling-place total or county aggregate is used to fabricate precinct votes. Existing geographic and demographic matching rules remain in force.

New regression tests exercise successive report editions, date-specific failures, alias contradictions, strict control precedence, exact request retries and frozen image qualification. Actual production collectors were run against the official sources, followed by complete refreshes and independent matched-turnout checks. Detailed release evidence and verification are retained in `analysis/refresh-reliability/`; raw voter records remain memory-only.

## Integrated live refresh acceptance

The second complete production refresh finished at `2026-10-28T15:54:53.874374213+00:00`. During the audit the official state feed published additional October 27 reports: admitted counties with a source for that day rose from 68 to 229, and counties with a valid cumulative comparison from 56 to 211. These gains combine publisher timing and repaired collection, and must not all be attributed to new adapters. The recurring adapters had already demonstrated native October 27 recovery before the state batch appeared. A later stronger state report can replace that alternative under the existing qualified-observation policy.

Dallas Days 1–8 retain their previous maximum matched coverage; Day 9 improves from 667 to 672 current precincts. Cameron Day 9 now has 101, Denton 226, Collin 254 and Fort Bend 186. Tarrant Day 9 changes from 346 to 345: newly published cutoff-day identity evidence contradicts one more native cell (`2393`), which is correctly withheld; all earlier matched-group observations remain unchanged. Its cumulative-only source still cannot manufacture same-day differences.

Automatic image generation completed with 211 counties, 24 comparison pages and 2,532 bucket rows, retaining the exact frozen qualification proof. Independent API verification passed 73,653 matched-group comparisons, 794,367 demographic-point comparisons, 35,856 regression checks and six oracle contracts with no errors. The final offline Rust suite passed 162 tests and all-target Clippy. Focused Python verification passed 97 tests; new current-source live checks were run explicitly, rather than counted from their default ignored status. Browser selection and same-day/cumulative matrix checks passed with real CSV and branded PNG exports.
