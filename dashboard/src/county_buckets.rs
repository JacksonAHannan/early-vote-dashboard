//! County aggregates remain independent of the narrower precinct comparison.
//! Daily and cumulative observations each use their own date-specific matched
//! counties; official cumulative values are never reconstructed from daily votes.
use crate::{LABELS, demographics::Metric, ratio, statewide, trends::CALENDAR_DAYS};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CountyReference {
    pub name: String,
    pub fips: String,
    pub harris: Option<u64>,
    pub trump: Option<u64>,
    #[serde(default)]
    pub counts: BTreeMap<String, Option<f64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Reference {
    pub schema_version: u32,
    pub metrics: Vec<Metric>,
    pub counties: BTreeMap<String, CountyReference>,
    #[serde(default)]
    pub sources: Vec<serde_json::Value>,
    #[serde(default)]
    pub method: String,
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
    pub groups: usize,
    pub cumulative_groups: usize,
    pub county_ids: Vec<String>,
    pub cumulative_county_ids: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct Bucket {
    pub id: String,
    pub label: String,
    pub lo: Option<f64>,
    pub hi: Option<f64>,
    /// Number of matched counties on the selected date.
    pub groups: usize,
    pub cumulative_groups: usize,
    pub county_ids: Vec<String>,
    pub cumulative_county_ids: Vec<String>,
    pub days: Vec<Day>,
}

#[derive(Debug, Serialize)]
pub struct CountyRow {
    pub id: String,
    pub name: String,
    pub fips: Option<String>,
    pub bucket: Option<usize>,
    /// Harris two-party share in partisan views; the requested Census share otherwise.
    pub share: Option<f64>,
    pub harris: Option<u64>,
    pub trump: Option<u64>,
    pub daily_included: bool,
    pub cumulative_included: bool,
    pub classification_issue: Option<String>,
    /// Official selected-day cumulative values, independent of classification.
    pub votes_2024: Option<u64>,
    pub votes_2026: Option<u64>,
    pub ratio: Option<f64>,
    pub daily_2024: Option<u64>,
    pub daily_2026: Option<u64>,
    pub registered_2024: Option<u64>,
    pub registered_2026: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct Omission {
    pub county: String,
    pub reason: String,
}

#[derive(Debug, Serialize)]
pub struct Coverage {
    pub total_counties: usize,
    pub classified_counties: usize,
    pub excluded_classification: Vec<Omission>,
    pub included_counties: Vec<String>,
    pub cumulative_included_counties: Vec<String>,
    pub excluded_daily: Vec<Omission>,
    pub excluded_cumulative: Vec<Omission>,
    pub groups: usize,
    pub cumulative_groups: usize,
    pub observed_days: u32,
}

#[derive(Debug, Serialize)]
pub struct View {
    pub schema_version: u32,
    pub generated_at: String,
    pub through: String,
    pub day: u32,
    pub view: String,
    pub metric: String,
    pub label: String,
    pub metric_definition: Option<Metric>,
    pub observed_days: u32,
    pub buckets: Vec<Bucket>,
    pub totals: Bucket,
    pub counties: Vec<CountyRow>,
    pub coverage: Coverage,
    pub method: String,
    pub reference_method: String,
    pub reference_sources: Vec<serde_json::Value>,
    pub turnout_sources: Vec<statewide::Source>,
    pub turnout_errors: Vec<statewide::SourceError>,
}

fn empty_bucket(id: String, label: String, lo: Option<f64>, hi: Option<f64>) -> Bucket {
    Bucket {
        id,
        label,
        lo,
        hi,
        groups: 0,
        cumulative_groups: 0,
        county_ids: vec![],
        cumulative_county_ids: vec![],
        days: (1..=CALENDAR_DAYS)
            .map(|day| Day {
                day,
                date_2024: (crate::start(2024) + chrono::Duration::days(i64::from(day - 1)))
                    .to_string(),
                date_2026: (crate::start(2026) + chrono::Duration::days(i64::from(day - 1)))
                    .to_string(),
                daily_2024: None,
                daily_2026: None,
                cumulative_2024: None,
                cumulative_2026: None,
                groups: 0,
                cumulative_groups: 0,
                county_ids: vec![],
                cumulative_county_ids: vec![],
            })
            .collect(),
    }
}

fn classification<'a>(
    reference: &'a Reference,
    view: &str,
    metric: &str,
) -> Result<(String, Option<&'a Metric>, Vec<Bucket>)> {
    match view {
        "partisan" => {
            ensure!(metric == "presidential_margin", "unknown partisan metric");
            Ok((
                "2024 presidential margin".into(),
                None,
                LABELS
                    .iter()
                    .enumerate()
                    .map(|(i, label)| empty_bucket(i.to_string(), (*label).into(), None, None))
                    .collect(),
            ))
        }
        "demographic" => {
            let m = reference
                .metrics
                .iter()
                .find(|m| m.id == metric)
                .context("unknown demographic metric")?;
            ensure!(m.unit == "percent", "unsupported demographic unit");
            ensure!(
                m.cuts
                    .iter()
                    .all(|x| x.is_finite() && (0.0..=100.0).contains(x))
                    && m.cuts.windows(2).all(|w| w[0] < w[1]),
                "demographic cuts must increase within 0–100"
            );
            let edges: Vec<_> = std::iter::once(0.0)
                .chain(m.cuts.iter().copied().filter(|x| *x > 0.0 && *x < 100.0))
                .chain(std::iter::once(100.0))
                .collect();
            Ok((
                m.label.clone(),
                Some(m),
                edges
                    .windows(2)
                    .enumerate()
                    .map(|(i, w)| {
                        empty_bucket(
                            i.to_string(),
                            format!("{}–{}%", w[0], w[1]),
                            Some(w[0]),
                            Some(w[1]),
                        )
                    })
                    .collect(),
            ))
        }
        _ => anyhow::bail!("unknown county view"),
    }
}

fn county_classification(
    reference: Option<&CountyReference>,
    metric: Option<&Metric>,
    buckets: &[Bucket],
) -> std::result::Result<(usize, f64), &'static str> {
    let reference = reference.ok_or("missing county classification")?;
    if let Some(metric) = metric {
        let numerator = reference
            .counts
            .get(&metric.numerator)
            .copied()
            .flatten()
            .ok_or("missing demographic counts")?;
        let denominator = reference
            .counts
            .get(&metric.denominator)
            .copied()
            .flatten()
            .ok_or("missing demographic counts")?;
        if !numerator.is_finite()
            || !denominator.is_finite()
            || numerator < 0.0
            || denominator < 0.0
            || numerator > denominator
        {
            return Err("invalid demographic counts");
        }
        if denominator == 0.0 {
            return Err("zero demographic denominator");
        }
        let share = numerator / denominator * 100.0;
        let bucket = buckets
            .iter()
            .position(|b| share < b.hi.unwrap())
            .unwrap_or(buckets.len() - 1);
        Ok((bucket, share))
    } else {
        let harris = reference.harris.ok_or("missing presidential counts")?;
        let trump = reference.trump.ok_or("missing presidential counts")?;
        let bucket = crate::classify(harris, trump).ok_or("tied presidential vote")?;
        let share = harris as f64 / (harris as f64 + trump as f64) * 100.0;
        Ok((bucket, share))
    }
}

fn report_day(county: &statewide::County, day: u32) -> Option<&statewide::Day> {
    county.days.iter().find(|d| d.day == day)
}

fn value(county: &statewide::County, day: u32, year: i32, cumulative: bool) -> Option<u64> {
    let d = report_day(county, day)?;
    match (year, cumulative) {
        (2024, false) => d.votes_2024,
        (2026, false) => d.votes_2026,
        (2024, true) => d.cumulative_2024,
        (2026, true) => d.cumulative_2026,
        _ => None,
    }
}

fn reporting_issue(county: &statewide::County, day: u32, cumulative: bool) -> Option<String> {
    for year in [2024, 2026] {
        if value(county, day, year, cumulative).is_none() {
            return Some(format!(
                "{year} day {day}: {} unavailable",
                if cumulative { "cumulative" } else { "daily" }
            ));
        }
    }
    None
}

struct Classified<'a> {
    county: &'a statewide::County,
    bucket: usize,
}

fn populate(
    bucket: &mut Bucket,
    target: Option<usize>,
    classified: &[Classified<'_>],
    observed: u32,
    selected: u32,
) -> Result<()> {
    for day in &mut bucket.days {
        let members = |cumulative: bool| -> Vec<&statewide::County> {
            classified
                .iter()
                .filter(|c| target.is_none_or(|b| b == c.bucket))
                .map(|c| c.county)
                .filter(|c| {
                    value(c, day.day, 2024, cumulative).is_some()
                        && (day.day > observed || value(c, day.day, 2026, cumulative).is_some())
                })
                .collect()
        };
        let daily = members(false);
        let cumulative = members(true);
        let sum = |members: &[&statewide::County], year, cumulative| -> Result<Option<u64>> {
            if members.is_empty() || (year == 2026 && day.day > observed) {
                return Ok(None);
            }
            let mut total = 0u64;
            for county in members {
                total = total
                    .checked_add(
                        value(county, day.day, year, cumulative)
                            .context("matched county value disappeared")?,
                    )
                    .context("county turnout overflow")?;
            }
            Ok(Some(total))
        };
        day.daily_2024 = sum(&daily, 2024, false)?;
        day.daily_2026 = sum(&daily, 2026, false)?;
        day.cumulative_2024 = sum(&cumulative, 2024, true)?;
        day.cumulative_2026 = sum(&cumulative, 2026, true)?;
        day.groups = daily.len();
        day.cumulative_groups = cumulative.len();
        day.county_ids = daily.iter().map(|c| c.id.clone()).collect();
        day.cumulative_county_ids = cumulative.iter().map(|c| c.id.clone()).collect();
        if day.day == selected {
            bucket.groups = day.groups;
            bucket.cumulative_groups = day.cumulative_groups;
            bucket.county_ids = day.county_ids.clone();
            bucket.cumulative_county_ids = day.cumulative_county_ids.clone();
        }
    }
    Ok(())
}

pub fn analyze(
    statewide: &statewide::Data,
    reference: &Reference,
    view: &str,
    metric: &str,
    day: u32,
) -> Result<View> {
    ensure!(
        statewide.schema_version == 1,
        "unsupported statewide schema"
    );
    ensure!(
        reference.schema_version == 1,
        "unsupported county reference schema"
    );
    let observed = crate::days_through(statewide.through)?;
    ensure!(
        (1..=observed).contains(&day),
        "day is outside the available county snapshot"
    );
    let (label, demographic_metric, mut buckets) = classification(reference, view, metric)?;
    let mut coverage = Coverage {
        total_counties: statewide.counties.len(),
        classified_counties: 0,
        excluded_classification: vec![],
        included_counties: vec![],
        cumulative_included_counties: vec![],
        excluded_daily: vec![],
        excluded_cumulative: vec![],
        groups: 0,
        cumulative_groups: 0,
        observed_days: observed,
    };
    let mut counties = vec![];
    let mut classified = vec![];
    let mut ids = BTreeSet::new();
    for county in &statewide.counties {
        ensure!(ids.insert(&county.id), "duplicate statewide county ID");
        let mut days = BTreeSet::new();
        for d in &county.days {
            ensure!(
                (1..=CALENDAR_DAYS).contains(&d.day) && days.insert(d.day),
                "invalid or duplicate county day"
            );
            ensure!(
                d.date_2024 == crate::start(2024) + chrono::Duration::days(i64::from(d.day - 1))
                    && d.date_2026
                        == crate::start(2026) + chrono::Duration::days(i64::from(d.day - 1)),
                "county report date disagrees with calendar day"
            );
        }
        let reference = reference.counties.get(&county.id);
        let classification = county_classification(reference, demographic_metric, &buckets);
        let daily_issue = reporting_issue(county, day, false);
        let cumulative_issue = reporting_issue(county, day, true);
        let (bucket, share, classification_issue) = match classification {
            Ok((bucket, share)) => {
                coverage.classified_counties += 1;
                classified.push(Classified { county, bucket });
                (Some(bucket), Some(share), None)
            }
            Err(reason) => {
                coverage.excluded_classification.push(Omission {
                    county: county.id.clone(),
                    reason: reason.into(),
                });
                (None, None, Some(reason.to_string()))
            }
        };
        let daily_included = classification_issue.is_none() && daily_issue.is_none();
        let cumulative_included = classification_issue.is_none() && cumulative_issue.is_none();
        for (included, issue, members, omitted) in [
            (
                daily_included,
                &daily_issue,
                &mut coverage.included_counties,
                &mut coverage.excluded_daily,
            ),
            (
                cumulative_included,
                &cumulative_issue,
                &mut coverage.cumulative_included_counties,
                &mut coverage.excluded_cumulative,
            ),
        ] {
            if included {
                members.push(county.id.clone());
            } else {
                omitted.push(Omission {
                    county: county.id.clone(),
                    reason: classification_issue
                        .as_ref()
                        .or(issue.as_ref())
                        .unwrap()
                        .clone(),
                });
            }
        }
        let selected = report_day(county, day);
        let old = selected.and_then(|d| d.cumulative_2024);
        let new = selected.and_then(|d| d.cumulative_2026);
        counties.push(CountyRow {
            id: county.id.clone(),
            name: county.name.clone(),
            fips: reference.map(|r| r.fips.clone()),
            bucket,
            share,
            harris: reference.and_then(|r| r.harris),
            trump: reference.and_then(|r| r.trump),
            daily_included,
            cumulative_included,
            classification_issue,
            votes_2024: old,
            votes_2026: new,
            ratio: old.zip(new).and_then(|(old, new)| ratio(new, old)),
            daily_2024: selected.and_then(|d| d.votes_2024),
            daily_2026: selected.and_then(|d| d.votes_2026),
            registered_2024: selected.and_then(|d| d.registered_2024),
            registered_2026: selected.and_then(|d| d.registered_2026),
        });
    }
    for (i, bucket) in buckets.iter_mut().enumerate() {
        populate(bucket, Some(i), &classified, observed, day)?;
    }
    let mut totals = empty_bucket("total".into(), "Compared counties".into(), None, None);
    populate(&mut totals, None, &classified, observed, day)?;
    coverage.groups = totals.groups;
    coverage.cumulative_groups = totals.cumulative_groups;
    Ok(View {
        schema_version: 1,
        generated_at: statewide.generated_at.clone(),
        through: statewide.through.to_string(),
        day,
        view: view.into(),
        metric: metric.into(),
        label,
        metric_definition: demographic_metric.cloned(),
        observed_days: observed,
        buckets,
        totals,
        counties,
        coverage,
        method: "County-level descriptive comparisons of official aggregate in-person turnout. Each county is classified once using its own 2024 presidential two-party margin or Census population share; counties are never assigned a precinct classification. Every date and measure uses all counties with available values in both cycles on that date; an omission on another date does not remove a county. Each observation includes its own county membership and count. Historical future dates use available historical counties; future 2026 dates and missing values remain null. Cumulative series sum native cumulative reports and are never reconstructed from daily reports. Bucket ratios compare summed turnout, never average county ratios. Selected-day county rows preserve official reports and identify that date’s matched membership. Demographic associations describe places, not the demographics of individual voters.".into(),
        reference_method: reference.method.clone(),
        reference_sources: reference.sources.clone(),
        turnout_sources: statewide.sources.clone(),
        turnout_errors: statewide.errors.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn metric() -> Metric {
        Metric {
            id: "non_white_vap".into(),
            label: "Total non-white".into(),
            unit: "percent".into(),
            numerator: "non_white_vap".into(),
            denominator: "vap".into(),
            cuts: vec![20.0, 40.0, 60.0, 80.0],
            source: "Census PL94-171".into(),
            vintage: "2020".into(),
        }
    }

    fn reference_county(name: &str, harris: u64, trump: u64, share: f64) -> CountyReference {
        CountyReference {
            name: name.into(),
            fips: "48001".into(),
            harris: Some(harris),
            trump: Some(trump),
            counts: BTreeMap::from([
                ("non_white_vap".into(), Some(share)),
                ("vap".into(), Some(100.0)),
            ]),
        }
    }

    fn fixture() -> (statewide::Data, Reference) {
        let counties = ["alpha", "beta", "gamma"]
            .into_iter()
            .enumerate()
            .map(|(i, id)| statewide::County {
                id: id.into(),
                name: id.into(),
                state_id: i as u32 + 1,
                days: (1..=12)
                    .map(|day| statewide::Day {
                        coverage: serde_json::Value::Null,
                        day,
                        date_2024: crate::start(2024) + chrono::Duration::days(i64::from(day - 1)),
                        date_2026: crate::start(2026) + chrono::Duration::days(i64::from(day - 1)),
                        votes_2024: Some(u64::from(day) * 10),
                        // Intentionally populate future dates to verify that the
                        // cutoff, rather than accidental input data, governs 2026.
                        votes_2026: Some(u64::from(day) * 20),
                        cumulative_2024: Some(u64::from(day) * 100),
                        cumulative_2026: Some(u64::from(day) * 300),
                        registered_2024: Some(1000),
                        registered_2026: Some(1100),
                        status_2024: "reported".into(),
                        status_2026: "reported".into(),
                    })
                    .collect(),
            })
            .collect();
        (
            statewide::Data {
                schema_version: 1,
                generated_at: "test".into(),
                through: crate::start(2026) + chrono::Duration::days(1),
                counties,
                sources: vec![],
                errors: vec![],
                scope: "Official native totals".into(),
            },
            Reference {
                schema_version: 1,
                metrics: vec![metric()],
                counties: BTreeMap::from([
                    ("alpha".into(), reference_county("alpha", 80, 20, 19.0)),
                    ("beta".into(), reference_county("beta", 20, 80, 20.0)),
                    ("gamma".into(), reference_county("gamma", 60, 40, 100.0)),
                ]),
                sources: vec![],
                method: "Original counts".into(),
            },
        )
    }

    #[test]
    fn daily_and_cumulative_match_each_date_independently_and_preserve_native_totals() {
        let (mut data, reference) = fixture();
        data.counties[1].days[1].votes_2026 = None;
        data.counties[2].days[0].cumulative_2024 = None;
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 1).unwrap();
        assert_eq!(
            result.coverage.included_counties,
            ["alpha", "beta", "gamma"]
        );
        assert_eq!(
            result.coverage.cumulative_included_counties,
            ["alpha", "beta"]
        );
        assert_eq!(result.totals.groups, 3);
        assert_eq!(result.totals.cumulative_groups, 2);
        assert_eq!(result.totals.days[1].daily_2024, Some(40));
        assert_eq!(result.totals.days[1].daily_2026, Some(80));
        assert_eq!(result.totals.days[1].cumulative_2024, Some(600));
        assert_eq!(result.totals.days[1].cumulative_2026, Some(1800));
        assert_ne!(result.totals.days[1].cumulative_2026, Some(40 + 80));
        // Selecting a date describes its own membership; the later gap never
        // erases valid earlier comparisons or the other measure.
        let later = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(result.totals.county_ids, ["alpha", "beta", "gamma"]);
        assert_eq!(later.totals.county_ids, ["alpha", "gamma"]);
        assert_eq!(result.totals.days[0].groups, 3);
        assert_eq!(result.totals.days[1].groups, 2);
        assert_eq!(result.totals.days[0].cumulative_groups, 2);
        assert_eq!(result.totals.days[1].cumulative_groups, 3);
        assert_eq!(result.counties[1].votes_2026, Some(300));
        assert_eq!(result.counties[1].ratio, Some(3.0));
        assert!(result.counties[1].daily_included);
        assert!(result.counties[1].cumulative_included);
        assert_eq!(result.counties[1].bucket, Some(5));
        for (i, day) in result.totals.days.iter().enumerate() {
            for cumulative in [false, true] {
                let values: Vec<_> = result
                    .buckets
                    .iter()
                    .filter_map(|b| {
                        if cumulative {
                            b.days[i].cumulative_2024
                        } else {
                            b.days[i].daily_2024
                        }
                    })
                    .collect();
                let total = if cumulative {
                    day.cumulative_2024
                } else {
                    day.daily_2024
                };
                assert_eq!(Some(values.iter().sum::<u64>()), total);
            }
        }
    }

    #[test]
    fn missing_fifth_day_does_not_remove_a_county_from_the_first_four_days() {
        let (mut data, reference) = fixture();
        data.through = crate::start(2026) + chrono::Duration::days(4);
        data.counties[1].days[4].votes_2026 = None;
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 5).unwrap();
        for day in result.totals.days.iter().take(4) {
            assert_eq!(day.groups, 3);
            assert_eq!(day.cumulative_groups, 3);
            assert_eq!(day.county_ids, ["alpha", "beta", "gamma"]);
            assert_eq!(day.daily_2026, Some(u64::from(day.day) * 60));
        }
        let fifth = &result.totals.days[4];
        assert_eq!(fifth.groups, 2);
        assert_eq!(fifth.daily_2024, Some(100));
        assert_eq!(fifth.daily_2026, Some(200));
        assert_eq!(fifth.cumulative_groups, 3);
        assert_eq!(fifth.cumulative_2026, Some(4500));
        assert_eq!(result.counties.len(), 3);
        assert!(!result.counties[1].daily_included);
        assert!(result.counties[1].cumulative_included);
    }

    #[test]
    fn preserves_complete_historical_future_and_masks_current_future() {
        let (mut data, reference) = fixture();
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(result.totals.days.len(), 12);
        assert_eq!(result.totals.days[11].daily_2024, Some(360));
        assert_eq!(result.totals.days[11].cumulative_2024, Some(3600));
        for day in result.totals.days.iter().skip(2) {
            assert_eq!(day.daily_2026, None);
            assert_eq!(day.cumulative_2026, None);
        }
        data.counties[0].days[11].votes_2024 = None;
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(result.totals.groups, 3);
        assert_eq!(result.totals.days[11].daily_2024, Some(240));
        assert_eq!(result.totals.days[11].groups, 2);
        assert_eq!(result.totals.days[11].cumulative_2024, Some(3600));
    }

    #[test]
    fn demographic_boundaries_classify_counties_without_presidential_requirement() {
        let (data, mut reference) = fixture();
        reference.counties.get_mut("beta").unwrap().harris = Some(80);
        // A presidential tie is excluded only from a partisan classification.
        let result = analyze(&data, &reference, "demographic", "non_white_vap", 2).unwrap();
        assert_eq!(
            result.counties.iter().map(|c| c.bucket).collect::<Vec<_>>(),
            [Some(0), Some(1), Some(4)]
        );
        assert_eq!(result.counties[1].share, Some(20.0));
        assert_eq!(result.counties[2].share, Some(100.0));
        assert_eq!(result.coverage.classified_counties, 3);
        let partisan = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(partisan.coverage.classified_counties, 2);
        assert_eq!(partisan.counties[1].bucket, None);
        assert_eq!(
            partisan.counties[1].classification_issue.as_deref(),
            Some("tied presidential vote")
        );
        // Empty buckets have no observations rather than fabricated zero turnout.
        assert_eq!(result.buckets[2].groups, 0);
        assert!(
            result.buckets[2]
                .days
                .iter()
                .all(|d| d.daily_2024.is_none())
        );
    }

    #[test]
    fn demographic_exclusions_distinguish_missing_invalid_and_zero_denominator() {
        let (data, mut reference) = fixture();
        reference
            .counties
            .get_mut("alpha")
            .unwrap()
            .counts
            .remove("vap");
        reference
            .counties
            .get_mut("beta")
            .unwrap()
            .counts
            .insert("non_white_vap".into(), Some(101.0));
        let counts = &mut reference.counties.get_mut("gamma").unwrap().counts;
        counts.insert("non_white_vap".into(), Some(0.0));
        counts.insert("vap".into(), Some(0.0));
        let result = analyze(&data, &reference, "demographic", "non_white_vap", 2).unwrap();
        assert_eq!(result.coverage.classified_counties, 0);
        assert_eq!(
            result
                .coverage
                .excluded_classification
                .iter()
                .map(|c| c.reason.as_str())
                .collect::<Vec<_>>(),
            [
                "missing demographic counts",
                "invalid demographic counts",
                "zero demographic denominator"
            ]
        );
        assert_eq!(result.totals.days[0].daily_2026, None);
        assert_eq!(result.totals.days[0].cumulative_2026, None);
        // Raw selected-day turnout survives a classification omission.
        assert_eq!(result.counties[0].votes_2026, Some(600));
    }

    #[test]
    fn zero_turnout_is_valid_and_zero_baseline_ratio_is_undefined() {
        let (mut data, reference) = fixture();
        for county in &mut data.counties {
            for day in county.days.iter_mut().take(2) {
                day.votes_2024 = Some(0);
                day.cumulative_2024 = Some(0);
            }
        }
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(result.totals.groups, 3);
        assert_eq!(result.totals.days[0].daily_2024, Some(0));
        assert_eq!(result.counties[0].ratio, None);
    }

    #[test]
    fn unknown_or_malformed_requests_fail_explicitly() {
        let (mut data, mut reference) = fixture();
        for (view, metric, day) in [
            ("primary", "presidential_margin", 1),
            ("partisan", "unknown", 1),
            ("demographic", "unknown", 1),
            ("partisan", "presidential_margin", 0),
            ("partisan", "presidential_margin", 3),
        ] {
            assert!(analyze(&data, &reference, view, metric, day).is_err());
        }
        reference.metrics[0].cuts = vec![40.0, 20.0];
        assert!(analyze(&data, &reference, "demographic", "non_white_vap", 1).is_err());
        data.counties[0].days[0].date_2024 = crate::start(2024) + chrono::Duration::days(1);
        assert!(analyze(&data, &reference, "partisan", "presidential_margin", 1).is_err());
    }

    #[test]
    fn integer_partisan_cut_edges_and_unavailable_counties_are_explicit() {
        let (data, mut reference) = fixture();
        let alpha = reference.counties.get_mut("alpha").unwrap();
        alpha.harris = Some(65);
        alpha.trump = Some(35);
        let beta = reference.counties.get_mut("beta").unwrap();
        beta.harris = Some(85);
        beta.trump = Some(115);
        reference.counties.remove("gamma");
        let result = analyze(&data, &reference, "partisan", "presidential_margin", 2).unwrap();
        assert_eq!(result.counties[0].bucket, Some(0));
        assert_eq!(result.counties[1].bucket, Some(4));
        assert_eq!(result.coverage.total_counties, 3);
        assert_eq!(result.coverage.classified_counties, 2);
        assert_eq!(result.coverage.excluded_classification[0].county, "gamma");
        assert_eq!(result.counties[2].votes_2026, Some(600));
    }
}
