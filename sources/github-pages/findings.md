# GitHub Pages deployment findings

Primary documentation checked on 2026-10-24. This is deployment research, not evidence that a repository or site has been published. Firecrawl retrieval was working during this check.

## Recommended architecture

Run the existing Rust analysis and collectors in scheduled GitHub Actions jobs. Publish generated HTML, JavaScript, maps, and anonymous aggregate data as a Pages artifact. The public browser must resolve dashboard requests from those static outputs: GitHub Pages serves static files and cannot keep the Rust HTTP process running. A custom Actions build is explicitly supported. [GitHub: creating a Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site#static-site-generators)

Use a project repository such as `JacksonAHannan/early-vote-tracker`, giving the project URL `https://jacksonahannan.github.io/early-vote-tracker/`. Project sites preserve their publishing-directory structure beneath the repository path. Consequently, use a repository base path for assets and data; existing root-relative `/api/...` requests cannot work unchanged. [GitHub: Pages site types](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages#types-of-github-pages-sites)

Implementation inference: static hosting will not execute the existing query handlers. Either export deterministic lookup files for supported combinations or let a browser adapter select from exported aggregate bundles. Test under a non-root prefix and confirm that date, method, measure, metric, county, and regression-filter changes each load the correct output. Keep the Rust implementation as the source of comparison calculations where practical.

## Capacity and cost boundaries

| Item | Current documented limit or behavior |
| --- | --- |
| Published Pages site | At most 1 GB |
| Pages source repository | Recommended maximum 1 GB |
| Pages deployment | Times out after 10 minutes |
| Pages bandwidth | Soft limit 100 GB/month |
| Pages build frequency | Soft limit 10 builds/hour; custom Actions workflows are exempt |

These are the supported Pages limits. [GitHub: Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits#usage-limits)

An upload artifact may technically contain an uncompressed tar below 10 GB, but GitHub's own artifact action explicitly says the supported Pages site maximum remains 1 GB. Larger accepted tarballs are not a supported hosting allowance. No symlinks or hard links belong in the deployment tar. [GitHub's upload-pages-artifact implementation](https://github.com/actions/upload-pages-artifact#artifact-validation)

Git itself warns above 50 MiB and blocks an individual file above 100 MiB. Those are repository-upload constraints, not a reason to commit repeated generated snapshots. GitHub recommends using releases when distributing large files outside ordinary Git history. [GitHub: large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

Standard GitHub-hosted Actions runners are free in public repositories. This does not mean larger runners or unlimited paid cache expansion are free. Use `ubuntu-latest` rather than a paid larger runner. [GitHub: Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage), [GitHub: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

The documented public `ubuntu-latest` runner has 4 CPUs, 16 GB RAM, and 14 GB SSD. Build/cache expansion needs to fit that disk along with downloaded sources and generated data. [GitHub: hosted runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories)

Observed locally during research: `dashboard/data` is 704 MiB and `sources` is 2.3 GiB. Much of the former is repeated 22–26 MiB historical run snapshots. Inference: publish a bounded current bundle, required historical comparison data, and maps; exclude raw downloads, accumulated run snapshots, logs, binaries, and Python caches. Enforce a conservative generated-site budget before uploading and keep the previous deployment if a candidate fails validation. Measure actual exported output rather than assuming its size from the existing data directory.

## Concrete setup and deployment sequence

1. Create the chosen public project repository and push the reviewed source and workflow to its default branch. Public repositories can use Pages on GitHub Free. [GitHub: creating a Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site#creating-a-repository-for-your-site)
2. Enable Pages using `POST /repos/JacksonAHannan/early-vote-tracker/pages` with JSON `{"build_type":"workflow"}`. If already enabled, read its settings and use `PUT` only if a change is required. Setup requires repository administration/maintenance or manage-Pages permission. Classic OAuth/PAT authentication needs `repo`; a fine-grained token needs Pages write **and** Administration write. These setup permissions differ from the workflow deployment token. [GitHub: Pages REST API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-site)
3. Run checkout, cache restore, Rust build, collection, validation, and static export in the build job. Run `actions/configure-pages@v5`, then `actions/upload-pages-artifact@v4` for the generated site directory. The top of that artifact must contain `index.html`. [GitHub: custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [GitHub: site entry file](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site#creating-your-site)
4. Use a dependent deployment job with `needs: build`, `pages: write`, `id-token: write`, and `contents: read`, environment `github-pages`, and `actions/deploy-pages@v4`. Use deployment step output `page_url` as the environment URL. A Pages artifact deployment avoids committing each data refresh to Git history. [GitHub: custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages#deploying-github-pages-artifacts)
5. After first deployment, verify the public project URL, representative data/asset requests, every state, every comparison mode, and a changed regression filter. Inspect the deployment API/action result before reporting publication complete. The deployment-status REST endpoint returns the actual Pages deployment state. [GitHub: deployment status endpoint](https://docs.github.com/en/rest/pages/pages#get-the-status-of-a-github-pages-deployment)

## Refresh scheduling

Use `workflow_dispatch` plus a default-branch schedule such as `17 * * * *` (twice hourly, UTC). GitHub's minimum scheduled interval is five minutes. UTC is the default; current documentation also allows an explicit IANA `timezone` field, so the older assertion that schedules can only use UTC is no longer correct. Avoid the start of each hour, when GitHub warns of higher load. Schedules may be delayed or dropped and are not a real-time service guarantee. In public repositories they automatically disable after 60 days without repository activity. Only default-branch workflow files run on schedule. [GitHub: schedule event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

Inference: show the source's observation cutoff and the last successful collection time, preserve last-successful state on transient source failures, and serialize refresh/deploy jobs so older data does not overwrite a newer export. Do not advertise an exact refresh SLA. Keep manual dispatch available for recovery.

## Cache persistence for anonymous aggregates

The default Actions cache allowance is 10 GB per repository. Entries unaccessed for seven days expire; storage pressure evicts the oldest accessed caches. Increasing the allowance beyond 10 GB can incur charges and should not be enabled for this task. A 700 MiB generation fits within the default allowance, but repeated generations and Rust build caches share that capacity. Cache eviction is expected behavior, so a cold-run reconstruction path is required. [GitHub: cache limits and eviction](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy)

Cache entries are immutable. For data that changes, use a new key per successful generation and a stable restore prefix, or separate restore/save actions. Reusing one exact key does not update the stored aggregate snapshot. Keep immutable historical inputs in a separate cache from changing current-year aggregates. [GitHub's cache update guidance](https://github.com/actions/cache/blob/main/tips-and-workarounds.md#update-a-cache)

Recommended operational pattern: restore the newest compatible aggregate generation; collect sources and atomically retain known-good per-source files when a download fails; validate/export; save only the required anonymous aggregate state under a new generation key; deploy only a valid site. Do not put voter identities, rosters, credentials, token-bearing responses, or huge reproducible raw downloads in a public cache or Pages artifact. A missing cache should bootstrap from pinned aggregate seed inputs or rebuild from official public sources, not publish an empty dashboard. This paragraph is an implementation recommendation, not a GitHub guarantee of durable storage.

## Implemented workflow and local checks

`.github/workflows/pages.yml` implements manual dispatch, the hourly schedule, and relevant default-branch source pushes. Pushes publish validated retained data without scraping; schedules always refresh official sources; manual runs have a Boolean `refresh_sources` input defaulting to true. An intentionally skipped refresh is recorded without a failure warning. This allows the first publication from verified bootstrap data to complete promptly, followed by a separate manual refresh acceptance run. It serializes jobs without interrupting a running refresh. The build job has Contents read and Pages read; a separate persistence job has Contents write; only the deployment job has Pages write and OIDC-token write. No repository secrets or paid services are introduced.

The agreed interfaces are `python3 dashboard/scripts/package_pages_state.py --restore PATH`, the same script with `--output PATH`, and `target/release/texas-turnout pages --output site`. The archive layout is repository-relative. The rolling cached archive falls back to the repository's `data-state` release asset, then the durable `bootstrap` release asset, each named `aggregate-state.tar.gz`. The build and package/export implementations must validate their inputs before this workflow is accepted as an end-to-end deployment.

The workflow uses the then-current first-party action major tags: checkout v7, cache v6, setup-python v6, upload-artifact v7, download-artifact v8, configure-pages v6, upload-pages-artifact v5, and deploy-pages v5. Their `action.yml` files were retrieved from the official GitHub `actions/*` repositories to verify the inputs actually used, rather than assuming examples in the prose docs always list the latest action major. [First-party checkout](https://github.com/actions/checkout), [cache](https://github.com/actions/cache), [upload artifact](https://github.com/actions/upload-artifact), [download artifact](https://github.com/actions/download-artifact), [configure Pages](https://github.com/actions/configure-pages), [upload Pages artifact](https://github.com/actions/upload-pages-artifact), [deploy Pages](https://github.com/actions/deploy-pages), [setup Python](https://github.com/actions/setup-python)

The release tags were independently checked through `GET /repos/actions/{action}/git/ref/tags/{major}`; they are real repository tags, not merely references in the `main` README. The preceding deployment recipe quotes older still-documented action majors; the implementation uses the verified tags below.

| Action tag | Resolved commit at verification |
| --- | --- |
| checkout v7 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| cache v6 | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| upload-artifact v7 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| download-artifact v8 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| configure-pages v6 | `45bfe0192ca1faeb007ade9deae92b16b8254a0d` |
| upload-pages-artifact v5 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| deploy-pages v5 | `368f82528645a54fb793d4d04e342629a3f51346` |
| setup-python v6 | `ece7cb06caefa5fff74198d8649806c4678c61a1` |

Local acceptance evidence: PyYAML parsed the workflow; explicit assertions checked schedule, manual-input schema, push/schedule/manual event matrix, non-canceling concurrency, job dependencies, and permission scopes; every `run` script passed `bash -n` and ShellCheck. No GitHub repository, account settings, release, or deployment was mutated by this research/workflow subtask. Remote Actions execution, official-source refresh from GitHub's network, artifact sizes, and the actual public site remain integration checks for the parent task.
