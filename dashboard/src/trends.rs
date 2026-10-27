//! Date-specific common-geography turnout. Missing reports and future dates remain null.
use crate::{
    Counts, Daily, GroupResult, LABELS, Reference, Snapshot, county, demographics::Data, fetch,
    start,
};
use anyhow::{Context, Result, ensure};
use chrono::{Datelike, Utc};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::Arc,
};

pub const CALENDAR_DAYS: u32 = 12;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct CountyHistory {
    #[serde(default)]
    pub sources: Vec<Daily>,
    #[serde(default)]
    pub errors: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct History {
    pub schema_version: u32,
    pub generated_at: String,
    pub counties: BTreeMap<String, CountyHistory>,
}
impl Default for History {
    fn default() -> Self {
        Self {
            schema_version: 1,
            generated_at: String::new(),
            counties: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Day {
    pub day: u32,
    pub date_2024: String,
    pub date_2026: String,
    pub daily_2024: Option<u64>,
    pub daily_2026: Option<u64>,
    pub cumulative_2024: Option<u64>,
    pub cumulative_2026: Option<u64>,
    pub daily_groups: usize,
    pub cumulative_groups: usize,
    pub daily_counties: usize,
    pub cumulative_counties: usize,
}

#[derive(Debug, Serialize)]
pub struct Bucket {
    pub id: String,
    pub label: String,
    pub lo: Option<f64>,
    pub hi: Option<f64>,
    pub groups: usize,
    pub cumulative_groups: usize,
    pub days: Vec<Day>,
}

#[derive(Debug, Serialize)]
pub struct CountyCoverage {
    pub county: String,
    pub included: bool,
    pub reason: String,
    pub groups: usize,
    pub eligible_groups: usize,
    pub excluded_classification: usize,
    pub daily_days_2024: Vec<u32>,
    pub daily_days_2026: Vec<u32>,
    pub cumulative_days_2024: Vec<u32>,
    pub cumulative_days_2026: Vec<u32>,
    pub issues: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct Coverage {
    pub included_counties: Vec<String>,
    pub excluded_counties: Vec<String>,
    pub counties: Vec<CountyCoverage>,
    pub groups: usize,
    pub excluded_classification: usize,
    pub baseline_complete: bool,
    pub observed_days: u32,
}

#[derive(Debug, Serialize)]
pub struct View {
    pub county: String,
    pub cohort: String,
    pub metric: String,
    pub label: String,
    pub observed_days: u32,
    pub buckets: Vec<Bucket>,
    pub totals: Bucket,
    pub coverage: Coverage,
    pub method: String,
}

#[derive(Clone, Default)]
struct ResolvedDay {
    daily: Option<Counts>,
    cumulative: Option<Counts>,
    daily_complete: bool,
    cumulative_complete: bool,
}

pub fn merge_sources(values: impl IntoIterator<Item = Daily>) -> Vec<Daily> {
    // Later exact-cutoff observations replace older observations; do not merge
    // cumulative and daily scope or allocate a late cumulative roster backwards.
    let mut by_cutoff: BTreeMap<_, Daily> = BTreeMap::new();
    for value in values {
        let key = (value.date, value.cumulative);
        if by_cutoff
            .get(&key)
            .is_none_or(|prior| value.retrieved_at >= prior.retrieved_at)
        {
            by_cutoff.insert(key, value);
        }
    }
    by_cutoff.into_values().collect()
}

fn resolve(sources: &[Daily], year: i32, observed: u32) -> (Vec<ResolvedDay>, Vec<String>) {
    resolve_with_ids(sources, year, observed, &BTreeSet::new())
}

fn resolve_with_ids(
    sources: &[Daily],
    year: i32,
    observed: u32,
    ids: &BTreeSet<String>,
) -> (Vec<ResolvedDay>, Vec<String>) {
    let values = resolved_matching(sources, year, observed, ids);
    let mut issues = vec![];
    for day in 2..=CALENDAR_DAYS {
        if year == 2026 && day > observed {
            break;
        }
        let date = start(year) + chrono::Duration::days(i64::from(day - 1));
        let current = sources.iter().find(|s| s.date == date && s.cumulative);
        let previous = sources
            .iter()
            .find(|s| s.date == date - chrono::Duration::days(1) && s.cumulative);
        if let (Some(current), Some(previous)) = (current, previous)
            && current
                .counts
                .iter()
                .any(|(id, n)| previous.counts.get(id).is_some_and(|p| n < p))
        {
            issues.push(format!("{year} day {day}: a cumulative precinct decreased; only that precinct's daily change is unavailable"));
        }
    }
    (values, issues)
}

fn classification(data: Option<&Data>, metric: &str) -> Result<(String, Vec<Bucket>)> {
    if let Some(data) = data {
        ensure!(
            data.schema_version == 1,
            "unsupported classification schema"
        );
        let m = data
            .metrics
            .iter()
            .find(|m| m.id == metric)
            .context("unknown classification metric")?;
        if crate::places::is_metric(m) {
            return Ok((
                m.label.clone(),
                crate::places::LABELS
                    .iter()
                    .enumerate()
                    .map(|(i, label)| Bucket {
                        id: i.to_string(),
                        label: (*label).into(),
                        lo: None,
                        hi: None,
                        groups: 0,
                        cumulative_groups: 0,
                        days: empty_days(),
                    })
                    .collect(),
            ));
        }
        ensure!(m.unit == "percent", "unsupported classification unit");
        ensure!(
            m.cuts
                .iter()
                .all(|x| x.is_finite() && (0.0..=100.0).contains(x))
                && m.cuts.windows(2).all(|w| w[0] < w[1]),
            "classification cuts must increase within 0–100"
        );
        let edges: Vec<_> = std::iter::once(0.0)
            .chain(m.cuts.iter().copied().filter(|x| *x > 0.0 && *x < 100.0))
            .chain(std::iter::once(100.0))
            .collect();
        Ok((
            m.label.clone(),
            edges
                .windows(2)
                .enumerate()
                .map(|(i, w)| Bucket {
                    id: i.to_string(),
                    label: format!("{}–{}%", w[0], w[1]),
                    lo: Some(w[0]),
                    hi: Some(w[1]),
                    groups: 0,
                    cumulative_groups: 0,
                    days: empty_days(),
                })
                .collect(),
        ))
    } else {
        ensure!(
            metric == "partisan",
            "partisan metric required without classification data"
        );
        Ok((
            "2024 presidential margin".into(),
            LABELS
                .iter()
                .enumerate()
                .map(|(i, label)| Bucket {
                    id: i.to_string(),
                    label: (*label).into(),
                    lo: None,
                    hi: None,
                    groups: 0,
                    cumulative_groups: 0,
                    days: empty_days(),
                })
                .collect(),
        ))
    }
}

fn group_bucket(
    group: &GroupResult,
    county: &str,
    data: Option<&Data>,
    metric: &str,
    bins: &[Bucket],
) -> Option<usize> {
    let Some(data) = data else {
        return group.bucket;
    };
    let m = data.metrics.iter().find(|m| m.id == metric)?;
    let county = data.counties.get(county)?;
    if crate::places::is_metric(m) {
        let counts = crate::demographics::group_counts(Some(county), &group.new, m).ok()?;
        return crate::places::classify(&counts);
    }
    if group.new.is_empty() {
        return None;
    }
    let mut numerator = 0.0;
    let mut denominator = 0.0;
    for id in &group.new {
        let counts = &county.precincts.get(id)?.counts;
        let n = counts.get(&m.numerator).copied().flatten()?;
        let d = counts.get(&m.denominator).copied().flatten()?;
        if !n.is_finite() || !d.is_finite() || n < 0.0 || d < 0.0 || n > d {
            return None;
        }
        numerator += n;
        denominator += d;
    }
    if !numerator.is_finite() || !denominator.is_finite() || denominator == 0.0 {
        return None;
    }
    let share = numerator / denominator * 100.0;
    Some(
        bins.iter()
            .position(|b| share < b.hi.unwrap())
            .unwrap_or(bins.len() - 1),
    )
}

fn empty_days() -> Vec<Day> {
    (1..=CALENDAR_DAYS)
        .map(|day| Day {
            day,
            date_2024: (start(2024) + chrono::Duration::days(i64::from(day - 1))).to_string(),
            date_2026: (start(2026) + chrono::Duration::days(i64::from(day - 1))).to_string(),
            daily_2024: None,
            daily_2026: None,
            cumulative_2024: None,
            cumulative_2026: None,
            daily_groups: 0,
            cumulative_groups: 0,
            daily_counties: 0,
            cumulative_counties: 0,
        })
        .collect()
}

struct CountySeries<'a> {
    groups: Vec<(&'a GroupResult, usize)>,
    old: Vec<ResolvedDay>,
    new: Vec<ResolvedDay>,
}

fn available_group(counts: &Counts, complete: bool, group: &GroupResult, year: i32) -> Option<u64> {
    let ids = if year == 2024 { &group.old } else { &group.new };
    if ids.is_empty() {
        return None;
    }
    ids.iter().try_fold(0u64, |total, id| {
        total.checked_add(counts.get(id).copied().or_else(|| complete.then_some(0))?)
    })
}

fn matched_observation(
    series: &[CountySeries<'_>],
    index: Option<usize>,
    day: usize,
    cumulative: bool,
    observed: u32,
) -> (Option<u64>, Option<u64>, usize, usize) {
    let future = day >= observed as usize;
    let mut old_total = 0u64;
    let mut new_total = 0u64;
    let mut groups = 0;
    let mut counties = 0;
    for county in series {
        let old = if cumulative {
            county.old[day].cumulative.as_ref()
        } else {
            county.old[day].daily.as_ref()
        };
        let new = if cumulative {
            county.new[day].cumulative.as_ref()
        } else {
            county.new[day].daily.as_ref()
        };
        let Some(old) = old else { continue };
        if !future && new.is_none() {
            continue;
        }
        let mut county_groups = 0;
        for (group, bucket) in &county.groups {
            if !index.is_none_or(|target| target == *bucket) {
                continue;
            }
            let Some(old_votes) = available_group(
                old,
                if cumulative {
                    county.old[day].cumulative_complete
                } else {
                    county.old[day].daily_complete
                },
                group,
                2024,
            ) else {
                continue;
            };
            let new_votes = if future {
                0
            } else {
                let Some(votes) = new.and_then(|new| {
                    available_group(
                        new,
                        if cumulative {
                            county.new[day].cumulative_complete
                        } else {
                            county.new[day].daily_complete
                        },
                        group,
                        2026,
                    )
                }) else {
                    continue;
                };
                votes
            };
            let Some(old_sum) = old_total.checked_add(old_votes) else {
                return (None, None, 0, 0);
            };
            let Some(new_sum) = new_total.checked_add(new_votes) else {
                return (None, None, 0, 0);
            };
            old_total = old_sum;
            new_total = new_sum;
            groups += 1;
            county_groups += 1;
        }
        counties += usize::from(county_groups > 0);
    }
    if groups == 0 {
        (None, None, 0, 0)
    } else {
        (
            Some(old_total),
            (!future).then_some(new_total),
            groups,
            counties,
        )
    }
}

fn populate(bucket: &mut Bucket, index: Option<usize>, series: &[CountySeries<'_>], observed: u32) {
    for (i, day) in bucket.days.iter_mut().enumerate() {
        let daily = matched_observation(series, index, i, false, observed);
        let cumulative = matched_observation(series, index, i, true, observed);
        day.daily_2024 = daily.0;
        day.daily_2026 = daily.1;
        day.daily_groups = daily.2;
        day.daily_counties = daily.3;
        day.cumulative_2024 = cumulative.0;
        day.cumulative_2026 = cumulative.1;
        day.cumulative_groups = cumulative.2;
        day.cumulative_counties = cumulative.3;
        if day.day == observed {
            bucket.groups = day.daily_groups;
            bucket.cumulative_groups = day.cumulative_groups;
        }
    }
}

fn resolved_matching(
    sources: &[Daily],
    year: i32,
    observed: u32,
    ids: &BTreeSet<String>,
) -> Vec<ResolvedDay> {
    // Reference IDs bound zero inference. Source labels cannot expand that scope.
    // Calendar-only callers without a reference retain the generic source universe.
    let universe = if ids.is_empty() {
        sources
            .iter()
            .filter(|s| s.date.year() == year)
            .flat_map(|s| s.counts.keys().cloned())
            .collect()
    } else {
        ids.clone()
    };
    (1..=CALENDAR_DAYS)
        .map(|day| {
            if year == 2026 && day > observed {
                return ResolvedDay::default();
            }
            ResolvedDay {
                daily: crate::matching::counts_with_ids(sources, year, day, false, &universe),
                cumulative: crate::matching::counts_with_ids(sources, year, day, true, &universe),
                daily_complete: crate::matching::full_with_ids(
                    sources, year, day, false, &universe,
                ),
                cumulative_complete: crate::matching::full_with_ids(
                    sources, year, day, true, &universe,
                ),
            }
        })
        .collect()
}

/// Daily matrix cells reuse the same per-precinct resolver as the timelines.
/// In particular, aggregate cumulative differences cannot establish daily pairs.
pub fn matrix_view(
    snapshot: &Snapshot,
    history: &History,
    references: &[Reference],
    classification: Option<&Data>,
    day: u32,
    cohort: &str,
    metric: &str,
) -> Result<serde_json::Value> {
    ensure!((1..=snapshot.days).contains(&day), "unknown completed day");
    ensure!(matches!(cohort, "matched" | "unchanged"), "unknown cohort");
    let mut daily = snapshot.clone();
    for c in &mut daily.counties {
        let reference = references
            .iter()
            .find(|r| r.id == c.id)
            .context("missing geographic reference")?;
        let sources = merge_sources(
            history
                .counties
                .get(&c.id)
                .into_iter()
                .flat_map(|h| h.sources.iter().cloned())
                .chain(c.sources.iter().cloned()),
        );
        c.periods = crate::matching::period(reference, &sources, day, false)
            .into_iter()
            .collect();
        c.sources.clear();
    }
    let mut views = serde_json::Map::new();
    if let Some(classification) = classification {
        for county in std::iter::once("all").chain(daily.counties.iter().map(|c| c.id.as_str())) {
            views.insert(
                county.into(),
                serde_json::to_value(crate::demographics::analyze(
                    &daily,
                    classification,
                    county,
                    day,
                    cohort,
                    metric,
                )?)?,
            );
        }
    }
    // Only matrix fields travel to the browser; reference membership is retained
    // for the all-county coverage denominator, including unavailable counties.
    let counties: Vec<_> = daily.counties.iter().map(|c| serde_json::json!({
        "id":c.id,"name":c.name,"periods":c.periods,
        "reference_groups":c.reference_groups.iter().map(|g| serde_json::json!({"new":g.new})).collect::<Vec<_>>()
    })).collect();
    Ok(
        serde_json::json!({"generated_at":snapshot.generated_at,"measure":"daily","counties":counties,"views":views}),
    )
}

pub fn analyze(
    snapshot: &Snapshot,
    history: &History,
    data: Option<&Data>,
    county: &str,
    cohort: &str,
    metric: &str,
) -> Result<View> {
    ensure!(history.schema_version == 1, "unsupported history schema");
    ensure!(matches!(cohort, "matched" | "unchanged"), "unknown cohort");
    ensure!(
        county == "all" || snapshot.counties.iter().any(|c| c.id == county),
        "unknown county"
    );
    ensure!(
        snapshot.days <= CALENDAR_DAYS,
        "snapshot exceeds early-vote calendar"
    );
    let (label, mut buckets) = classification(data, metric)?;
    let mut coverage = Coverage {
        included_counties: vec![],
        excluded_counties: vec![],
        counties: vec![],
        groups: 0,
        excluded_classification: 0,
        baseline_complete: true,
        observed_days: snapshot.days,
    };
    let mut selected = Vec::new();
    for c in snapshot
        .counties
        .iter()
        .filter(|c| county == "all" || c.id == county)
    {
        let sources = merge_sources(
            history
                .counties
                .get(&c.id)
                .into_iter()
                .flat_map(|h| h.sources.iter().cloned())
                .chain(c.sources.iter().cloned()),
        );
        let latest = c.periods.iter().max_by_key(|p| p.day);
        let reference_groups = if c.reference_groups.is_empty() {
            latest.map(|p| p.groups.as_slice()).unwrap_or_default()
        } else {
            &c.reference_groups
        };
        let old_ids = reference_groups
            .iter()
            .flat_map(|g| g.old.iter().cloned())
            .collect();
        let new_ids = reference_groups
            .iter()
            .flat_map(|g| g.new.iter().cloned())
            .collect();
        let (old, mut issues) = resolve_with_ids(&sources, 2024, snapshot.days, &old_ids);
        let (new, new_issues) = resolve_with_ids(&sources, 2026, snapshot.days, &new_ids);
        issues.extend(new_issues);
        let eligible: Vec<_> = reference_groups
            .iter()
            .filter(|g| cohort != "unchanged" || g.unchanged)
            .collect();
        let groups: Vec<_> = eligible
            .iter()
            .filter_map(|g| group_bucket(g, &c.id, data, metric, &buckets).map(|b| (*g, b)))
            .collect();
        let daily_days_2024: Vec<_> = old
            .iter()
            .enumerate()
            .filter_map(|(i, d)| d.daily.as_ref().map(|_| i as u32 + 1))
            .collect();
        let daily_days_2026: Vec<_> = new
            .iter()
            .enumerate()
            .filter_map(|(i, d)| d.daily.as_ref().map(|_| i as u32 + 1))
            .collect();
        // Classifications remain stable, while reporting membership is resolved
        // separately for every day and for daily versus cumulative measures.
        let county_series = CountySeries {
            groups: groups.clone(),
            old: old.clone(),
            new: new.clone(),
        };
        let has_match = |day: usize, cumulative: bool| {
            matched_observation(
                std::slice::from_ref(&county_series),
                None,
                day,
                cumulative,
                snapshot.days,
            )
            .2 > 0
        };
        let included =
            (0..snapshot.days as usize).any(|day| has_match(day, false) || has_match(day, true));
        let reason = if reference_groups.is_empty() {
            "No geographic comparison"
        } else if groups.is_empty() {
            "No complete classification"
        } else if !included {
            "No matched observations on observed dates"
        } else {
            ""
        };
        let excluded_classification = eligible.len() - groups.len();
        coverage.counties.push(CountyCoverage {
            county: c.id.clone(),
            included,
            reason: reason.into(),
            groups: if snapshot.days > 0 {
                matched_observation(
                    std::slice::from_ref(&county_series),
                    None,
                    snapshot.days as usize - 1,
                    false,
                    snapshot.days,
                )
                .2
            } else {
                0
            },
            eligible_groups: eligible.len(),
            excluded_classification,
            daily_days_2024,
            daily_days_2026,
            cumulative_days_2024: old
                .iter()
                .enumerate()
                .filter_map(|(i, d)| d.cumulative.as_ref().map(|_| i as u32 + 1))
                .collect(),
            cumulative_days_2026: new
                .iter()
                .enumerate()
                .filter_map(|(i, d)| d.cumulative.as_ref().map(|_| i as u32 + 1))
                .collect(),
            issues,
        });
        if included {
            coverage.included_counties.push(c.id.clone());
            coverage.excluded_classification += excluded_classification;
        } else {
            coverage.excluded_counties.push(c.id.clone());
        }
        if !groups.is_empty() {
            selected.push(county_series);
        }
    }
    if selected.is_empty() {
        coverage.baseline_complete = false;
    }
    for (index, bucket) in buckets.iter_mut().enumerate() {
        populate(bucket, Some(index), &selected, snapshot.days);
    }
    let mut totals = Bucket {
        id: "total".into(),
        label: "Compared precincts".into(),
        lo: None,
        hi: None,
        groups: 0,
        cumulative_groups: 0,
        days: empty_days(),
    };
    populate(&mut totals, None, &selected, snapshot.days);
    coverage.groups = totals.groups;
    coverage.baseline_complete = totals.days.iter().all(|d| d.daily_2024.is_some());
    Ok(View {county:county.into(),cohort:cohort.into(),metric:metric.into(),label,observed_days:snapshot.days,buckets,totals,coverage,
        method:"Common geographic groups are classified consistently and matched separately for each date and measure. A group contributes only when every constituent precinct has available counts in both cycles for that observation. Missing precincts or dates never remove other available groups or earlier observations. Each point reports its own matched group and county counts. Historical future dates use available historical groups; future 2026 values remain null. Cumulative reports yield daily changes only between consecutive available, nondecreasing counts for that precinct. Votes are never allocated across precincts or dates.".into()})
}

fn atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension("tmp");
    std::fs::write(&temp, bytes)?;
    std::fs::rename(temp, path)?;
    Ok(())
}

fn validate_dallas_history(days: &[Daily]) -> Result<()> {
    let dates: BTreeSet<_> = days.iter().map(|d| d.date).collect();
    ensure!(
        days.len() == CALENDAR_DAYS as usize && dates.len() == days.len(),
        "Dallas history must contain 12 distinct daily reports"
    );
    ensure!(
        days.iter().all(|d| d.county == "dallas"
            && !d.cumulative
            && d.date.year() == 2024
            && !d.counts.is_empty()),
        "Invalid Dallas historical aggregate scope"
    );
    ensure!(
        resolve(days, 2024, CALENDAR_DAYS)
            .0
            .iter()
            .all(|d| d.daily.is_some()),
        "Dallas historical calendar is incomplete"
    );
    Ok(())
}

async fn collect_dallas_history(root: &Path) -> Result<Vec<Daily>> {
    // The historical workbook has one reused SOS identifier belonging to two
    // distinct county IDs. The streaming collector validates unique county IDs,
    // all 12 location controls, and the original five-day precinct aggregates.
    let script = root
        .parent()
        .context("dashboard has no project parent")?
        .join("sources/daily-tracking/collect_dallas_history.py");
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(360),
        tokio::process::Command::new("python")
            .arg(script)
            .kill_on_drop(true)
            .output(),
    )
    .await
    .context("Dallas streaming history collection timed out")??;
    ensure!(
        output.status.success(),
        "Dallas historical source validation failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let days: Vec<Daily> = serde_json::from_slice(&std::fs::read(
        root.join("data/history-cache/dallas/2024-series.json"),
    )?)?;
    validate_dallas_history(&days)?;
    Ok(days)
}

/// Fetch only historical precinct aggregates. Adapters decode voter rows solely
/// in memory; caches and history contain counts, dates, URLs and content hashes.
pub async fn refresh_history(
    client: &reqwest::Client,
    root: &Path,
    references: &[Reference],
    snapshot: &Snapshot,
) -> Result<History> {
    let mut history: History = std::fs::read(root.join("data/history.json"))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    let mut jobs = tokio::task::JoinSet::new();
    let semaphore = Arc::new(tokio::sync::Semaphore::new(3));
    for r in references {
        let r = r.clone();
        let client = client.clone();
        let root = root.to_path_buf();
        let semaphore = semaphore.clone();
        let old = history.counties.remove(&r.id).unwrap_or_default();
        let snapshot_sources = snapshot
            .counties
            .iter()
            .find(|c| c.id == r.id)
            .map(|c| c.sources.clone())
            .unwrap_or_default();
        jobs.spawn(async move {
            let _permit = semaphore.acquire_owned().await?;
            let cache = root.join(format!("data/history-cache/{}/2024-series.json", r.id));
            let cached: Vec<Daily> = std::fs::read(&cache)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
            let regular: Vec<Daily> =
                std::fs::read(root.join(format!("data/cache/{}/2024-series.json", r.id)))
                    .ok()
                    .and_then(|b| serde_json::from_slice(&b).ok())
                    .unwrap_or_default();
            let mut values = merge_sources(
                old.sources
                    .into_iter()
                    .chain(cached)
                    .chain(regular)
                    .chain(snapshot_sources),
            );
            let mut errors = BTreeMap::new();
            let full = resolve(&values, 2024, CALENDAR_DAYS)
                .0
                .iter()
                .all(|d| d.daily.is_some());
            if !full && r.id == "dallas" {
                match collect_dallas_history(&root).await {
                    Ok(days) => values = merge_sources(values.into_iter().chain(days)),
                    Err(error) => {
                        errors.insert("2024".into(), format!("{error:#}"));
                    }
                }
            } else if !full && county::has_adapter(&r.id, 2024) {
                match tokio::time::timeout(
                    std::time::Duration::from_secs(300),
                    county::collect(&client, &r, 2024, CALENDAR_DAYS),
                )
                .await
                {
                    Ok(Ok(days)) => values = merge_sources(values.into_iter().chain(days)),
                    Ok(Err(e)) => {
                        errors.insert("2024".into(), format!("{e:#}"));
                    }
                    Err(_) => {
                        errors.insert("2024".into(), "County history download timed out".into());
                    }
                }
            } else if !full {
                let mut identities = BTreeSet::new();
                for day in 1..=CALENDAR_DAYS {
                    let date = start(2024) + chrono::Duration::days(i64::from(day - 1));
                    if values.iter().any(|d| d.date == date && !d.cumulative) {
                        continue;
                    }
                    match fetch::fetch_state(&client, &r, date, &mut identities).await {
                        Ok(d) => {
                            values = merge_sources(values.into_iter().chain(std::iter::once(d)))
                        }
                        Err(e) => {
                            errors.insert(date.to_string(), format!("{e:#}"));
                        }
                    }
                    let only_old: Vec<_> = values
                        .iter()
                        .filter(|d| d.date.year() == 2024)
                        .cloned()
                        .collect();
                    atomic(&cache, &serde_json::to_vec_pretty(&only_old)?)?;
                }
            }
            let only_old: Vec<_> = values
                .iter()
                .filter(|d| d.date.year() == 2024)
                .cloned()
                .collect();
            atomic(&cache, &serde_json::to_vec_pretty(&only_old)?)?;
            for day in 1..=CALENDAR_DAYS {
                if resolve(&values, 2024, CALENDAR_DAYS).0[day as usize - 1]
                    .daily
                    .is_none()
                {
                    let date = start(2024) + chrono::Duration::days(i64::from(day - 1));
                    errors.entry(date.to_string()).or_insert_with(|| {
                        "No complete historical precinct report; not assumed zero".into()
                    });
                }
            }
            eprintln!(
                "history {}: {}/12 historical daily reports",
                r.id,
                resolve(&values, 2024, CALENDAR_DAYS)
                    .0
                    .iter()
                    .filter(|d| d.daily.is_some())
                    .count()
            );
            Ok::<_, anyhow::Error>((
                r.id,
                CountyHistory {
                    sources: values,
                    errors,
                },
            ))
        });
    }
    while let Some(job) = jobs.join_next().await {
        let (id, value) = job??;
        history.counties.insert(id, value);
    }
    history.schema_version = 1;
    history.generated_at = Utc::now().to_rfc3339();
    atomic(
        &root.join("data/history.json"),
        &serde_json::to_vec_pretty(&history)?,
    )?;
    Ok(history)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{County, Period};
    use serde_json::json;

    fn daily(county: &str, year: i32, day: u32, counts: &[(&str, u64)], cumulative: bool) -> Daily {
        Daily {
            allow_daily_difference: None,
            zero_evidence: Vec::new(),
            unavailable_precincts: Vec::new(),
            county: county.into(),
            date: start(year) + chrono::Duration::days(i64::from(day - 1)),
            counts: counts.iter().map(|(id, n)| ((*id).into(), *n)).collect(),
            source: "official source".into(),
            sha256: "aggregate-fixture".into(),
            retrieved_at: "".into(),
            note: "".into(),
            cumulative,
            complete: false,
        }
    }

    #[test]
    fn unmapped_positive_labels_do_not_expand_the_reference_certification_universe() {
        let ids = BTreeSet::from(["1".into(), "2".into()]);
        let mut first = daily("x", 2026, 1, &[("1", 10), ("99999", 1)], false);
        first.complete = true;
        let mut second = daily("x", 2026, 2, &[("1", 5)], false);
        second.complete = true;
        let resolved = resolved_matching(&[first, second], 2026, 2, &ids);
        assert_eq!(resolved[0].daily.as_ref().unwrap()["99999"], 1);
        assert!(!resolved[0].daily.as_ref().unwrap().contains_key("2"));
        assert!(!resolved[0].daily_complete);
        assert!(!resolved[1].cumulative.as_ref().unwrap().contains_key("2"));
        assert!(!resolved[1].cumulative_complete);
        assert_eq!(resolved[1].daily.as_ref().unwrap()["2"], 0);
    }

    fn group(old: &[&str], new: &[&str], bucket: Option<usize>, unchanged: bool) -> GroupResult {
        GroupResult {
            old: old.iter().map(|s| (*s).into()).collect(),
            new: new.iter().map(|s| (*s).into()).collect(),
            votes_2024: 0,
            votes_2026: 0,
            bucket,
            unchanged,
            reason: "".into(),
            harris: 60,
            trump: 40,
            available: true,
        }
    }

    fn period(day: u32, groups: Vec<GroupResult>) -> Period {
        serde_json::from_value(json!({"day":day,"through_2024":"","through_2026":"","county_2024":0,"county_2026":0,
            "county_ratio":null,"unassigned_2024":0,"unassigned_2026":0,"buckets":[],"groups":groups,
            "matched":{"groups":0,"votes_2024":0,"votes_2026":0,"ratio":null},
            "unchanged":{"groups":0,"votes_2024":0,"votes_2026":0,"ratio":null}})).unwrap()
    }

    fn county(id: &str, groups: Vec<GroupResult>, sources: Vec<Daily>) -> County {
        County {
            id: id.into(),
            name: id.into(),
            status: "current".into(),
            checked_at: "".into(),
            error: None,
            periods: vec![period(2, groups)],
            sources,
            reference_groups: vec![],
        }
    }

    fn snapshot(counties: Vec<County>, days: u32) -> Snapshot {
        Snapshot {
            completeness_sha256: String::new(),
            reference_sha256: "".into(),
            schema_version: 1,
            generated_at: "".into(),
            through: "".into(),
            days,
            geography: "".into(),
            counties,
        }
    }

    #[test]
    fn matrix_daily_pairs_do_not_subtract_changing_cumulative_geography() {
        let reference = Reference {
            id: "x".into(),
            name: "X".into(),
            state_id: 1,
            groups: vec![
                crate::Group {
                    old: vec!["a".into()],
                    new: vec!["a".into()],
                },
                crate::Group {
                    old: vec!["b".into()],
                    new: vec!["b".into()],
                },
            ],
            exact_pairs: vec![["a".into(), "a".into()], ["b".into(), "b".into()]],
            presidential: [
                (
                    "a".into(),
                    crate::Party {
                        harris: 80,
                        trump: 20,
                    },
                ),
                (
                    "b".into(),
                    crate::Party {
                        harris: 20,
                        trump: 80,
                    },
                ),
            ]
            .into(),
            references: json!({}),
        };
        let sources = vec![
            daily("x", 2024, 1, &[("a", 100), ("b", 200)], true),
            daily("x", 2024, 2, &[("a", 120), ("b", 240)], true),
            daily("x", 2026, 1, &[("a", 100), ("b", 200)], true),
            // a has a downward revision; only b retains a valid daily change.
            daily("x", 2026, 2, &[("a", 90), ("b", 260)], true),
        ];
        let mut c = county("x", vec![], sources.clone());
        c.reference_groups = crate::analyze(&reference, &Counts::new(), &Counts::new(), 1)
            .unwrap()
            .groups;
        let snapshot = snapshot(vec![c], 2);
        let view = matrix_view(
            &snapshot,
            &History::default(),
            std::slice::from_ref(&reference),
            None,
            2,
            "matched",
            "partisan",
        )
        .unwrap();
        let period = &view["counties"][0]["periods"][0];
        assert_eq!(period["county_2024"], 40);
        assert_eq!(period["county_2026"], 60);
        assert_eq!(period["coverage"]["available_groups"], 1);
        assert_eq!(period["groups"][0]["available"], false);
        assert_eq!(period["buckets"][5]["matched"]["ratio"], 1.5);
        assert_eq!(snapshot.counties[0].sources.len(), 4);
        assert!(
            matrix_view(
                &snapshot,
                &History::default(),
                &[reference],
                None,
                3,
                "matched",
                "partisan"
            )
            .is_err()
        );
        // A missing prior observation cannot be inferred from another precinct.
        let mut partial = sources;
        partial[2].counts.remove("b");
        assert!(
            !crate::matching::counts(&partial, 2026, 2, false)
                .unwrap()
                .contains_key("b")
        );
    }

    #[test]
    fn cumulative_gaps_do_not_become_daily_zero_or_spread_across_dates() {
        let sources = vec![
            daily("x", 2026, 4, &[("1", 100)], true),
            daily("x", 2026, 5, &[("1", 150)], true),
            daily("x", 2026, 6, &[("1", 30)], false),
        ];
        let (r, issues) = resolve(&sources, 2026, 5);
        assert!(issues.is_empty());
        assert!(r[0].daily.is_none());
        assert!(r[3].daily.is_none());
        assert_eq!(r[3].cumulative.as_ref().unwrap()["1"], 100);
        assert_eq!(r[4].daily.as_ref().unwrap()["1"], 50);
        assert_eq!(r[4].cumulative.as_ref().unwrap()["1"], 150);
        assert!(r[5].daily.is_none());
        assert!(r[5].cumulative.is_none());
    }

    #[test]
    fn precinct_decrease_only_blocks_that_precincts_derived_daily_count() {
        let sources = vec![
            daily("x", 2024, 1, &[("a", 5), ("b", 5)], true),
            daily("x", 2024, 2, &[("a", 4), ("b", 7)], true),
        ];
        let (r, issues) = resolve(&sources, 2024, 12);
        assert_eq!(r[0].daily.as_ref().unwrap().values().sum::<u64>(), 10);
        assert_eq!(
            r[1].daily.as_ref().unwrap(),
            &Counts::from([("b".into(), 2)])
        );
        assert_eq!(r[1].cumulative.as_ref().unwrap().values().sum::<u64>(), 11);
        assert_eq!(issues.len(), 1);
    }

    #[test]
    fn date_specific_membership_keeps_other_dates_and_full_historical_future() {
        let sources = |id: &str, missing_first: bool| {
            (1..=12)
                .map(|day| daily(id, 2024, day, &[("old", 10)], false))
                .chain(
                    (1..=2)
                        .filter(|day| !missing_first || *day != 1)
                        .map(|day| daily(id, 2026, day, &[("new", 20)], false)),
                )
                .collect()
        };
        let s = snapshot(
            vec![
                county(
                    "a",
                    vec![group(&["old"], &["new"], Some(0), true)],
                    sources("a", false),
                ),
                county(
                    "b",
                    vec![group(&["old"], &["new"], Some(0), true)],
                    sources("b", true),
                ),
            ],
            2,
        );
        let v = analyze(&s, &History::default(), None, "all", "matched", "partisan").unwrap();
        assert_eq!(v.coverage.included_counties, vec!["a", "b"]);
        assert!(v.coverage.excluded_counties.is_empty());
        assert!(v.coverage.baseline_complete);
        assert_eq!(v.totals.days[0].daily_2026, Some(20));
        assert_eq!(v.totals.days[1].daily_2026, Some(40));
        assert_eq!(v.totals.days[0].daily_groups, 1);
        assert_eq!(v.totals.days[1].daily_groups, 2);
        assert_eq!(v.totals.days[1].cumulative_groups, 1);
        assert_eq!(v.totals.days[2].daily_2026, None);
        assert_eq!(v.totals.days[11].daily_2024, Some(20));
        assert_eq!(v.totals.days[11].cumulative_2024, Some(240));
        let b = analyze(&s, &History::default(), None, "b", "matched", "partisan").unwrap();
        assert_eq!(b.totals.days[0].daily_2026, None);
        assert_eq!(b.totals.days[1].daily_2026, Some(20));
        assert_eq!(b.totals.days[1].cumulative_2026, None);
    }

    #[test]
    fn fifth_day_missing_precinct_and_county_preserve_every_other_matched_observation() {
        let mut a_sources = vec![];
        let mut b_sources = vec![];
        for day in 1..=12 {
            a_sources.push(daily("a", 2024, day, &[("o1", 10), ("o2", 20)], false));
            b_sources.push(daily("b", 2024, day, &[("old", 5)], false));
            if day <= 5 {
                a_sources.push(daily(
                    "a",
                    2026,
                    day,
                    if day == 5 {
                        &[("n1", 20)]
                    } else {
                        &[("n1", 20), ("n2", 40)]
                    },
                    false,
                ));
                if day < 5 {
                    b_sources.push(daily("b", 2026, day, &[("new", 10)], false));
                }
            }
        }
        let mut a_groups = vec![
            group(&["o1"], &["n1"], Some(0), true),
            group(&["o2"], &["n2"], Some(0), true),
        ];
        a_groups[1].available = false;
        let a = county("a", a_groups, a_sources);
        let mut b = county("b", vec![], b_sources);
        b.reference_groups = vec![group(&["old"], &["new"], Some(0), true)];
        b.periods.clear(); // Daily matching does not require any cumulative Period.
        let v = analyze(
            &snapshot(vec![a, b], 5),
            &History::default(),
            None,
            "all",
            "matched",
            "partisan",
        )
        .unwrap();
        for day in v.totals.days.iter().take(4) {
            assert_eq!(day.daily_2024, Some(35));
            assert_eq!(day.daily_2026, Some(70));
            assert_eq!(day.daily_groups, 3);
            assert_eq!(day.daily_counties, 2);
            assert_eq!(day.cumulative_groups, 3);
        }
        let fifth = &v.totals.days[4];
        assert_eq!((fifth.daily_2024, fifth.daily_2026), (Some(10), Some(20)));
        assert_eq!(
            (fifth.cumulative_2024, fifth.cumulative_2026),
            (Some(50), Some(100))
        );
        assert_eq!((fifth.daily_groups, fifth.cumulative_groups), (1, 1));
        assert_eq!((fifth.daily_counties, fifth.cumulative_counties), (1, 1));
        assert_eq!(v.coverage.included_counties, ["a", "b"]);
        assert_eq!(v.totals.groups, 1);
        assert_eq!(v.totals.days[11].daily_2024, Some(35));
        assert_eq!(v.totals.days[11].daily_2026, None);
    }

    #[test]
    fn proved_complete_roster_allows_precinct_zero_but_unproved_absence_is_missing() {
        let mut old = daily("x", 2024, 1, &[], false);
        let mut new = daily("x", 2026, 1, &[], false);
        old.complete = true;
        new.complete = true;
        let c = county(
            "x",
            vec![group(&["old"], &["new"], Some(0), true)],
            vec![old.clone(), new.clone()],
        );
        let v = analyze(
            &snapshot(vec![c], 1),
            &History::default(),
            None,
            "x",
            "matched",
            "partisan",
        )
        .unwrap();
        assert_eq!(
            (v.totals.days[0].daily_2024, v.totals.days[0].daily_2026),
            (Some(0), Some(0))
        );
        assert_eq!(v.totals.days[0].daily_groups, 1);
        new.complete = false;
        let c = county(
            "x",
            vec![group(&["old"], &["new"], Some(0), true)],
            vec![old, new],
        );
        let v = analyze(
            &snapshot(vec![c], 1),
            &History::default(),
            None,
            "x",
            "matched",
            "partisan",
        )
        .unwrap();
        assert_eq!(v.totals.days[0].daily_2024, None);
        assert_eq!(v.totals.days[0].daily_2026, None);
        assert_eq!(v.totals.days[0].daily_groups, 0);
    }

    #[test]
    fn membership_uses_latest_groups_once_for_every_date() {
        let mut c = county(
            "x",
            vec![group(&["old"], &["new"], Some(5), true)],
            vec![
                daily("x", 2024, 1, &[("old", 10)], false),
                daily("x", 2024, 2, &[("old", 15)], false),
                daily("x", 2026, 1, &[("new", 20)], false),
                daily("x", 2026, 2, &[("new", 25)], false),
            ],
        );
        c.periods
            .insert(0, period(1, vec![group(&["old"], &["new"], Some(0), true)]));
        let s = snapshot(vec![c], 2);
        let v = analyze(&s, &History::default(), None, "x", "matched", "partisan").unwrap();
        assert_eq!(v.buckets[5].days[0].daily_2024, Some(10));
        assert_eq!(v.buckets[5].days[1].cumulative_2026, Some(45));
        assert_eq!(v.buckets[0].groups, 0);
        assert_eq!(v.buckets[0].days[0].daily_2024, None);
        assert!(!v.coverage.baseline_complete);
    }

    #[test]
    fn generic_classification_weights_native_counts_and_excludes_incomplete_groups() {
        let s = snapshot(
            vec![county(
                "x",
                vec![
                    group(&["o1"], &["n1", "n2"], None, false),
                    group(&["o2"], &["missing"], Some(0), true),
                ],
                vec![
                    daily("x", 2024, 1, &[("o1", 10), ("o2", 99)], false),
                    daily(
                        "x",
                        2026,
                        1,
                        &[("n1", 8), ("n2", 4), ("missing", 99)],
                        false,
                    ),
                ],
            )],
            1,
        );
        let d:Data=serde_json::from_value(json!({"schema_version":1,"metrics":[{"id":"dem_primary","label":"Democratic primary ballots",
            "unit":"percent","numerator":"dem","denominator":"total","cuts":[0,20,40,60,80,100],"source":"official","vintage":"2026"}],
            "counties":{"x":{"precincts":{"n1":{"counts":{"dem":10,"total":10}},"n2":{"counts":{"dem":0,"total":90}}}}}})).unwrap();
        let v = analyze(
            &s,
            &History::default(),
            Some(&d),
            "x",
            "matched",
            "dem_primary",
        )
        .unwrap();
        assert_eq!(v.coverage.groups, 1);
        assert_eq!(v.coverage.excluded_classification, 1);
        assert_eq!(v.buckets[0].groups, 1);
        assert_eq!(v.buckets[0].days[0].daily_2024, Some(10));
        assert_eq!(v.buckets[0].days[0].daily_2026, Some(12));
        assert_eq!(v.totals.days[0].cumulative_2026, Some(12));
    }

    #[test]
    fn newest_exact_cutoff_replaces_older_observation_without_dropping_other_cutoffs() {
        let sources = merge_sources([
            daily("x", 2026, 4, &[("1", 100)], true),
            daily("x", 2026, 5, &[("1", 150)], true),
            daily("x", 2026, 5, &[("1", 151)], true),
        ]);
        assert_eq!(sources.len(), 2);
        let (resolved, _) = resolve(&sources, 2026, 5);
        assert_eq!(resolved[4].daily.as_ref().unwrap()["1"], 51);
    }

    #[test]
    fn older_snapshot_cannot_replace_newer_historical_observation() {
        let mut new = daily("x", 2024, 1, &[("1", 11)], false);
        new.retrieved_at = "2026-10-24T12:00:00Z".into();
        let mut old = daily("x", 2024, 1, &[("1", 10)], false);
        old.retrieved_at = "2026-10-23T12:00:00Z".into();
        let merged = merge_sources([new, old]);
        assert_eq!(merged[0].counts["1"], 11);
    }

    #[test]
    fn cold_dallas_aggregate_validation_rejects_duplicate_dates_and_wrong_scope() {
        let days: Vec<_> = (1..=12)
            .map(|day| daily("dallas", 2024, day, &[("1", 10)], false))
            .collect();
        assert!(validate_dallas_history(&days).is_ok());
        let mut duplicate = days.clone();
        duplicate[11] = duplicate[10].clone();
        assert!(validate_dallas_history(&duplicate).is_err());
        let mut wrong_county = days.clone();
        wrong_county[11].county = "other".into();
        assert!(validate_dallas_history(&wrong_county).is_err());
        let mut cumulative = days;
        cumulative[11].cumulative = true;
        assert!(validate_dallas_history(&cumulative).is_err());
    }
}
