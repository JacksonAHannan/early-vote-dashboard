# Early vote dashboard

[Open the live dashboard](https://jacksonahannan.github.io/early-vote-dashboard/)

Interactive 2026 early-vote turnout compared with the equivalent 2024 point, covering Texas, Georgia, North Carolina, Virginia and available Nevada counties.

- County/state views default to **Mail + in person**, with separate methods available. Texas preserves the same SOS by-mail definition across both years; native county in-person controls can corroborate that component without allocating mail to precincts.
- Texas precinct views remain explicitly **In person**. A paired Harris mail collector rejected historical source/control discrepancies, so received-mail records are not silently substituted for a different historical mail series.
- Precinct and county comparisons use the largest supported matched geography independently for each day and daily/cumulative measure. Missing reports remain unknown.
- Georgia opens with statewide voter race, with Age and Sex available. Published voter demographics remain separate from Census county composition.
- Demographic regressions offer All, Trump and Harris 2024-winner cohorts, each with its own fit, sample size and exports. Auto focuses the vertical view on the main cluster; Full range reveals outliers while retaining them in the selected cohort's fit.
- Precinct bucket tables offer searchable county checkboxes and whole-county Census demographic/place presets. **All Counties** and **All Selected Counties** stay pinned before individual counties. Selected totals sum matched votes across the entire selection, including other pages; CSV exports include all selected counties. County Census composition selects counties; the table still measures matched precincts.
- Linked maps, future 2024 benchmarks, daily trends, collapsible panels, and individual PNG/CSV downloads remain available.

Georgia covers all 159 counties; North Carolina all 100; Virginia all 133 localities through the attributed EPEC archive of ELECT aggregates. Nevada currently includes Clark and Washoe 2026 reports, with Clark's dated 2024 baseline. Precinct detail and classifications vary by state. Sources and scope qualifications are available inside the dashboard and in `sources/multistate/`.

## Updates and hosting

The presentation matches [Jackson Hannan’s Alabama forecast](https://jacksonahannan.github.io/alabama-state-house-and-state-senate-model/). PNG exports carry X **@electionsjack** and **linkedin.com/in/jackson-hannan**, with copyable captions and ALT text. [Export specifications and research](sources/social-export/findings.md).

GitHub Pages hosts the website. GitHub Actions runs the Rust collectors and analysis once an hour, at minute 17 UTC, then publishes a validated static build. Scheduled runs can be delayed by GitHub; timestamps in the dashboard identify the actual data generation. The browser checks the current publication once per hour. **Check updates** checks the latest publication rather than initiating a new source scrape.

Source failures retain successful observations. Each observed comparison pairs precisely the supported geography and date in both years. Publication never infers missing votes or allocates county totals to precincts. A failed build leaves the prior website in place.

The application uses standard public-repository GitHub runners and Pages. No local computer, external application server, paid hosting service or voter-level records are required to serve the published website.

## Rebuild locally

A clean checkout needs the anonymous aggregate/reference/map inputs distributed as release assets. The mutable `data-state` release contains the retained current inputs; `bootstrap` provides the initial recovery snapshot. Both contain only validated, allowlisted aggregate JSON with file hashes.

```bash
gh release download data-state --repo JacksonAHannan/early-vote-dashboard --pattern aggregate-state.tar.gz
# If no retained-state release exists yet, download the same asset from bootstrap.
python3 dashboard/scripts/package_pages_state.py --restore aggregate-state.tar.gz
cargo build --manifest-path dashboard/Cargo.toml --release --locked --target-dir target
target/release/texas-turnout serve --offline --port 8741
```

For county aggregates alone, run `target/release/texas-turnout statewide`; add `--offline` to rebuild from retained native aggregates. The legacy `build_statewide.py` command delegates to this same Rust parser.

To scrape sources, run `target/release/texas-turnout refresh`. Native PDF and transport fallbacks use Poppler, uv, curl-cffi and Playwright; the workflow installs the required tools. Collector data definitions and verification commands are documented in `dashboard/README.md`.

To generate the Pages site:

```bash
target/release/texas-turnout pages --output site
```

Serve `site/` with a static HTTP server. No API server is required: Rust writes immutable compressed query outputs, and the browser adapter resolves selections beneath the repository URL prefix. Source refresh and static export use the same Rust comparison functions. The published site is checked against a 900 MB safety budget.

## Verification

```bash
cargo test --manifest-path dashboard/Cargo.toml --locked
node --test dashboard/tests/regression-scale.test.cjs dashboard/tests/regression-cohort.test.cjs dashboard/tests/county-selection.test.cjs
python3 -m unittest dashboard/tests/test_pages_state.py
```

Browser acceptance scripts include `pages_browser.py`, `regression_winner.py`, and `regression_auto.py` under `dashboard/tests/`. Set the corresponding test URL to a running local Rust server or generated static site as documented in each script. Source archive audits additionally require their retained source evidence or a fresh collection.

Aggregate inputs, public geometry and source provenance are retained independently from application code. Raw voter identities, credentials, machine logs, process IDs, build products and accumulated snapshots are excluded from the release bootstrap and source repository.
