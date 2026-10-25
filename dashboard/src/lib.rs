pub mod county;
pub mod county_buckets;
pub mod demographics;
pub mod fetch;
pub mod fort_bend;
pub mod interstate;
pub mod matching;
pub mod pages;
pub mod places;
pub mod quality;
pub mod rebuild;
pub mod regression;
pub mod statewide;
pub mod trends;

use anyhow::{Result, ensure};
use chrono::{NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const LABELS: [&str; 6] = [
    "Harris 30+",
    "Harris 15–30",
    "Harris 0–15",
    "Trump 0–15",
    "Trump 15–30",
    "Trump 30+",
];
pub const GEOGRAPHY: &str = "TLC 2024 general → 2026 primary precincts; November boundaries remain a proxy. Mixed-margin groups are excluded; votes are never allocated by area.";
pub type Counts = BTreeMap<String, u64>;

#[derive(Clone, Deserialize, Serialize)]
pub struct Reference {
    pub id: String,
    pub name: String,
    pub state_id: u32,
    pub groups: Vec<Group>,
    pub exact_pairs: Vec<[String; 2]>,
    pub presidential: BTreeMap<String, Party>,
    pub references: serde_json::Value,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Group {
    pub old: Vec<String>,
    pub new: Vec<String>,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Party {
    pub harris: u64,
    pub trump: u64,
}
#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct Daily {
    #[serde(default)]
    pub complete: bool,
    pub county: String,
    pub date: NaiveDate,
    pub counts: Counts,
    pub source: String,
    pub sha256: String,
    pub retrieved_at: String,
    pub note: String,
    #[serde(default)]
    pub cumulative: bool,
}
#[derive(Clone, Deserialize, Serialize, Debug, Default)]
pub struct Cohort {
    pub groups: u64,
    pub votes_2024: u64,
    pub votes_2026: u64,
    pub ratio: Option<f64>,
}
impl Cohort {
    fn add(&mut self, old: u64, new: u64) {
        self.groups += 1;
        self.votes_2024 += old;
        self.votes_2026 += new;
    }
    fn finish(&mut self) {
        self.ratio = ratio(self.votes_2026, self.votes_2024);
    }
}
#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct Bucket {
    pub label: String,
    pub matched: Cohort,
    pub unchanged: Cohort,
}
fn available_default() -> bool {
    true
}
#[derive(Clone, Deserialize, Serialize, Debug, Default)]
pub struct MatchedCoverage {
    pub available_groups: u64,
    pub total_groups: u64,
    pub available_precincts: u64,
    pub total_precincts: u64,
    pub baseline_votes_2024: u64,
    pub available_baseline_votes_2024: u64,
    pub reported_votes_2024: u64,
    pub reported_votes_2026: u64,
}
#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct GroupResult {
    #[serde(default = "available_default")]
    pub available: bool,
    pub old: Vec<String>,
    pub new: Vec<String>,
    pub votes_2024: u64,
    pub votes_2026: u64,
    pub bucket: Option<usize>,
    pub unchanged: bool,
    pub reason: String,
    pub harris: u64,
    pub trump: u64,
}
#[derive(Clone, Deserialize, Serialize, Debug)]
pub struct Period {
    #[serde(default)]
    pub coverage: MatchedCoverage,
    pub day: u32,
    pub through_2024: String,
    pub through_2026: String,
    pub county_2024: u64,
    pub county_2026: u64,
    pub county_ratio: Option<f64>,
    pub unassigned_2024: u64,
    pub unassigned_2026: u64,
    pub matched: Cohort,
    pub unchanged: Cohort,
    pub buckets: Vec<Bucket>,
    pub groups: Vec<GroupResult>,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct County {
    #[serde(default)]
    pub reference_groups: Vec<GroupResult>,
    pub id: String,
    pub name: String,
    pub status: String,
    pub checked_at: String,
    pub error: Option<String>,
    pub periods: Vec<Period>,
    pub sources: Vec<Daily>,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Snapshot {
    #[serde(default)]
    pub completeness_sha256: String,
    #[serde(default)]
    pub reference_sha256: String,
    pub schema_version: u32,
    pub generated_at: String,
    pub through: String,
    pub days: u32,
    pub geography: String,
    pub counties: Vec<County>,
}

/// Keep previously verified cumulative cutoffs when a county replaces its live
/// workbook with a later one. A freshly downloaded snapshot wins for its date.
pub fn retain_cumulative_cutoffs(values: &mut Vec<Daily>, cached: &[Daily], through: NaiveDate) {
    for saved in cached {
        if saved.cumulative
            && saved.date <= through
            && !values.iter().any(|value| value.date == saved.date)
        {
            values.push(saved.clone());
        }
    }
}

pub fn preserve_failure(prior: Option<County>, reference: &Reference, error: String) -> County {
    let mut county = prior.unwrap_or(County {
        reference_groups: vec![],
        id: reference.id.clone(),
        name: reference.name.clone(),
        status: "missing".into(),
        checked_at: String::new(),
        error: None,
        periods: vec![],
        sources: vec![],
    });
    county.status = if county.periods.is_empty() {
        "missing"
    } else {
        "stale"
    }
    .into();
    county.checked_at = Utc::now().to_rfc3339();
    county.error = Some(error);
    county
}

pub fn normalize(s: &str) -> String {
    let s = s.trim().trim_start_matches('\u{feff}').to_uppercase();
    // Numeric padding also occurs before lettered precinct suffixes (001A).
    let unpadded = s.trim_start_matches('0');
    if unpadded.is_empty() && !s.is_empty() {
        "0".into()
    } else {
        unpadded.into()
    }
}
pub fn ratio(new: u64, old: u64) -> Option<f64> {
    if old == 0 {
        None
    } else {
        Some(new as f64 / old as f64)
    }
}
pub fn classify(h: u64, t: u64) -> Option<usize> {
    if h == t {
        return None;
    }
    let total = u128::from(h) + u128::from(t);
    let margin = u128::from(h.abs_diff(t)) * 100;
    let band = if margin >= total * 30 {
        2
    } else if margin >= total * 15 {
        1
    } else {
        0
    };
    Some(if h > t { 2 - band } else { 3 + band })
}
pub fn start(year: i32) -> NaiveDate {
    NaiveDate::from_ymd_opt(year, 10, if year == 2024 { 21 } else { 19 }).unwrap()
}
pub fn days_through(date: NaiveDate) -> Result<u32> {
    let n = date.signed_duration_since(start(2026)).num_days() + 1;
    ensure!((1..=12).contains(&n), "cutoff must be October 19–30, 2026");
    Ok(n as u32)
}
pub fn latest_completed() -> NaiveDate {
    let yesterday = Utc::now()
        .with_timezone(&chrono_tz::America::Chicago)
        .date_naive()
        .pred_opt()
        .unwrap();
    yesterday.min(NaiveDate::from_ymd_opt(2026, 10, 30).unwrap())
}
pub fn sum_days(days: &[Daily], year: i32, n: u32) -> Result<Counts> {
    let cutoff = start(year) + chrono::Duration::days(i64::from(n) - 1);
    let cumulative: Vec<_> = days
        .iter()
        .filter(|d| d.cumulative && d.date == cutoff)
        .collect();
    ensure!(cumulative.len() <= 1, "duplicate cumulative cutoff");
    if let Some(d) = cumulative.first() {
        return Ok(d.counts.clone());
    }
    let mut result = Counts::new();
    let mut seen = BTreeSet::new();
    for daily in days {
        if !daily.cumulative
            && daily.date >= start(year)
            && daily.date < start(year) + chrono::Duration::days(i64::from(n))
        {
            ensure!(
                seen.insert(daily.date),
                "duplicate daily export for {}",
                daily.date
            );
            for (key, value) in &daily.counts {
                *result.entry(key.clone()).or_default() += value;
            }
        }
    }
    ensure!(
        seen.len() == n as usize,
        "missing daily export: {year} day {n}; incomplete periods are not summed"
    );
    Ok(result)
}
pub fn analyze(reference: &Reference, old: &Counts, new: &Counts, day: u32) -> Result<Period> {
    let mut buckets: Vec<Bucket> = LABELS
        .iter()
        .map(|label| Bucket {
            label: label.to_string(),
            matched: Cohort::default(),
            unchanged: Cohort::default(),
        })
        .collect();
    let mut groups = Vec::new();
    let mut seen_old = BTreeSet::new();
    let mut seen_new = BTreeSet::new();
    let exact: BTreeSet<_> = reference
        .exact_pairs
        .iter()
        .map(|p| (&p[0], &p[1]))
        .collect();
    let mut matched = Cohort::default();
    let mut unchanged = Cohort::default();
    for group in &reference.groups {
        ensure!(
            !group.old.is_empty() && !group.new.is_empty(),
            "empty geography group"
        );
        for p in &group.old {
            ensure!(seen_old.insert(p.clone()), "duplicate 2024 geography: {p}");
        }
        for p in &group.new {
            ensure!(seen_new.insert(p.clone()), "duplicate 2026 geography: {p}");
        }
        let v24 = group
            .old
            .iter()
            .map(|p| old.get(p).copied().unwrap_or(0))
            .sum();
        let v26 = group
            .new
            .iter()
            .map(|p| new.get(p).copied().unwrap_or(0))
            .sum();
        let bins: Vec<_> = group
            .old
            .iter()
            .map(|p| {
                reference
                    .presidential
                    .get(p)
                    .and_then(|r| classify(r.harris, r.trump))
            })
            .collect();
        let band = if bins.iter().all(|b| *b == bins[0]) {
            bins[0]
        } else {
            None
        };
        let strict = group.old.len() == 1
            && group.new.len() == 1
            && exact.contains(&(&group.old[0], &group.new[0]));
        let reason = if bins.contains(&None) {
            "Missing or tied presidential return"
        } else if band.is_none() {
            "Mixed margin bands"
        } else {
            ""
        };
        if let Some(b) = band {
            buckets[b].matched.add(v24, v26);
            matched.add(v24, v26);
            if strict {
                buckets[b].unchanged.add(v24, v26);
                unchanged.add(v24, v26);
            }
        }
        groups.push(GroupResult {
            available: true,
            old: group.old.clone(),
            new: group.new.clone(),
            votes_2024: v24,
            votes_2026: v26,
            bucket: band,
            unchanged: strict && band.is_some(),
            reason: reason.into(),
            // Partial returns cannot establish a group's partisan share or winner.
            // Zero/zero is the existing unknown convention; demographic All views
            // retain the group's valid turnout and population observations.
            harris: if group
                .old
                .iter()
                .all(|p| reference.presidential.contains_key(p))
            {
                group
                    .old
                    .iter()
                    .map(|p| reference.presidential[p].harris)
                    .sum()
            } else {
                0
            },
            trump: if group
                .old
                .iter()
                .all(|p| reference.presidential.contains_key(p))
            {
                group
                    .old
                    .iter()
                    .map(|p| reference.presidential[p].trump)
                    .sum()
            } else {
                0
            },
        });
    }
    for b in &mut buckets {
        b.matched.finish();
        b.unchanged.finish();
    }
    matched.finish();
    unchanged.finish();
    let county_2024 = old.values().sum();
    let county_2026 = new.values().sum();
    let unassigned_2024 = old
        .iter()
        .filter(|(p, _)| !seen_old.contains(*p))
        .map(|(_, v)| v)
        .sum();
    let unassigned_2026 = new
        .iter()
        .filter(|(p, _)| !seen_new.contains(*p))
        .map(|(_, v)| v)
        .sum();
    ensure!(
        groups.iter().map(|g| g.votes_2024).sum::<u64>() + unassigned_2024 == county_2024,
        "2024 reconciliation failed"
    );
    ensure!(
        groups.iter().map(|g| g.votes_2026).sum::<u64>() + unassigned_2026 == county_2026,
        "2026 reconciliation failed"
    );
    Ok(Period {
        coverage: MatchedCoverage::default(),
        day,
        through_2024: (start(2024) + chrono::Duration::days(i64::from(day) - 1)).to_string(),
        through_2026: (start(2026) + chrono::Duration::days(i64::from(day) - 1)).to_string(),
        county_2024,
        county_2026,
        county_ratio: ratio(county_2026, county_2024),
        unassigned_2024,
        unassigned_2026,
        matched,
        unchanged,
        buckets,
        groups,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_band_edges_and_ties() {
        assert_eq!(classify(65, 35), Some(0));
        assert_eq!(classify(115, 85), Some(1));
        assert_eq!(classify(114, 86), Some(2));
        assert_eq!(classify(35, 65), Some(5));
        assert_eq!(classify(85, 115), Some(4));
        assert_eq!(classify(86, 114), Some(3));
        assert_eq!(classify(50, 50), None);
        assert_eq!(classify(0, 0), None);
    }
    fn reference() -> Reference {
        serde_json::from_value(serde_json::json!({"id":"test","name":"Test","state_id":1,"groups":[{"old":["1","2"],"new":["3"]},{"old":["4"],"new":["4"]}],"exact_pairs":[["4","4"]],"presidential":{"1":{"harris":80,"trump":20},"2":{"harris":20,"trump":80},"4":{"harris":65,"trump":35}},"references":{}})).unwrap()
    }
    #[test]
    fn mixed_merges_unassigned_and_zero_baseline() {
        let r = reference();
        let old = Counts::from([("1".into(), 100), ("2".into(), 200)]);
        let new = Counts::from([("3".into(), 250), ("4".into(), 20), ("UNKNOWN".into(), 7)]);
        let p = analyze(&r, &old, &new, 4).unwrap();
        assert_eq!(p.county_2026, 277);
        assert_eq!(p.unassigned_2026, 7);
        assert_eq!(p.matched.votes_2026, 20);
        assert_eq!(p.buckets[0].matched.ratio, None);
        assert_eq!(p.unchanged.groups, 1);
        assert_eq!(p.groups[0].reason, "Mixed margin bands");
    }
    #[test]
    fn missing_presidential_does_not_become_zero() {
        let mut r = reference();
        r.presidential.remove("4");
        let p = analyze(&r, &Counts::new(), &Counts::from([("4".into(), 20)]), 1).unwrap();
        assert_eq!(p.matched.groups, 0);
        assert!(p.groups[1].reason.starts_with("Missing"));
    }
    #[test]
    fn duplicate_geography_rejected() {
        let mut r = reference();
        r.groups.push(r.groups[0].clone());
        assert!(analyze(&r, &Counts::new(), &Counts::new(), 1).is_err());
    }
    #[test]
    fn missing_or_duplicate_days_are_not_partial_sums() {
        assert!(sum_days(&[], 2024, 4).is_err());
        let d = Daily {
            complete: false,
            county: "x".into(),
            date: start(2024),
            counts: Counts::new(),
            source: String::new(),
            sha256: String::new(),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: false,
        };
        assert!(sum_days(&[d.clone(), d], 2024, 1).is_err());
    }
}

#[cfg(test)]
mod recovery_tests {
    use super::*;
    #[test]
    fn failed_refresh_preserves_last_good_period_and_provenance() {
        let reference:Reference=serde_json::from_value(serde_json::json!({"id":"x","name":"X","state_id":1,"groups":[],"exact_pairs":[],"presidential":{},"references":{}})).unwrap();
        let p = analyze(
            &reference,
            &Counts::from([("UNASSIGNED".into(), 10)]),
            &Counts::from([("UNASSIGNED".into(), 8)]),
            1,
        )
        .unwrap();
        let old = County {
            reference_groups: vec![],
            id: "x".into(),
            name: "X".into(),
            status: "current".into(),
            checked_at: "before".into(),
            error: None,
            periods: vec![p],
            sources: vec![],
        };
        let result = preserve_failure(Some(old), &reference, "download unavailable".into());
        assert_eq!(result.status, "stale");
        assert_eq!(result.periods[0].county_2026, 8);
        assert_eq!(result.periods[0].day, 1);
        let empty = preserve_failure(None, &reference, "download unavailable".into());
        assert_eq!(empty.status, "missing");
        assert!(empty.periods.is_empty());
    }
    #[test]
    fn newer_cumulative_workbook_keeps_exact_requested_cutoff_without_allocation() {
        let through = start(2026) + chrono::Duration::days(3);
        let old = Daily {
            complete: false,
            county: "ellis".into(),
            date: through,
            counts: Counts::from([("1".into(), 9)]),
            source: "county".into(),
            sha256: "old-hash".into(),
            retrieved_at: "old-time".into(),
            note: "verified earlier cutoff".into(),
            cumulative: true,
        };
        let mut later = old.clone();
        later.date += chrono::Duration::days(1);
        later.counts = Counts::from([("1".into(), 15)]);
        let mut values = vec![later.clone()];
        assert!(sum_days(&values, 2026, 4).is_err());
        retain_cumulative_cutoffs(&mut values, std::slice::from_ref(&old), through);
        assert_eq!(sum_days(&values, 2026, 4).unwrap()["1"], 9);
        assert_eq!(sum_days(&values, 2026, 5).unwrap()["1"], 15);
        let saved = values.iter().find(|v| v.date == through).unwrap();
        assert_eq!(saved.sha256, "old-hash");
        assert_eq!(saved.retrieved_at, "old-time");
        // Fresh corrections at the same cutoff supersede historical cache.
        let mut corrected = old.clone();
        corrected.counts = Counts::from([("1".into(), 10)]);
        let mut fresh = vec![corrected];
        retain_cumulative_cutoffs(&mut fresh, &[old, later], through);
        assert_eq!(fresh.len(), 1);
        assert_eq!(sum_days(&fresh, 2026, 4).unwrap()["1"], 10);
    }

    #[test]
    fn cumulative_snapshot_cannot_reconstruct_an_earlier_day() {
        let d = Daily {
            complete: false,
            county: "x".into(),
            date: start(2026) + chrono::Duration::days(3),
            counts: Counts::from([("1".into(), 9)]),
            source: "county".into(),
            sha256: String::new(),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: true,
        };
        assert_eq!(sum_days(std::slice::from_ref(&d), 2026, 4).unwrap()["1"], 9);
        assert!(sum_days(&[d], 2026, 3).is_err());
    }
}
