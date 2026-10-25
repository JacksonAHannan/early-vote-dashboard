//! Descriptive turnout comparisons using aggregate Census population counts.
//! Percentages are formed after summing complete current-boundary group counts.
use crate::{Cohort, Snapshot, regression};
use anyhow::{Result, bail, ensure};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

const COHORT_METHOD: &str = "Demographic matched cohorts include all common geographic groups with complete demographic counts, including mixed partisan-margin groups. Partisan classification exclusions apply only to partisan views. The unchanged cohort retains the existing strict unchanged flag.";

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Metric {
    pub id: String,
    pub label: String,
    pub unit: String,
    pub numerator: String,
    pub denominator: String,
    pub cuts: Vec<f64>,
    pub source: String,
    pub vintage: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Precinct {
    #[serde(default)]
    pub counts: BTreeMap<String, Option<f64>>,
    #[serde(default)]
    pub quality: serde_json::Value,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct CountyData {
    #[serde(default)]
    pub precincts: BTreeMap<String, Precinct>,
    #[serde(default)]
    pub coverage: serde_json::Value,
    #[serde(default)]
    pub census_totals: serde_json::Value,
    #[serde(default)]
    pub assigned_totals: serde_json::Value,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Data {
    pub schema_version: u32,
    pub metrics: Vec<Metric>,
    pub counties: BTreeMap<String, CountyData>,
    #[serde(default)]
    pub sources: Vec<serde_json::Value>,
    #[serde(default)]
    pub method: String,
}

/// Fixed March-primary evidence is versioned with the application, so an older
/// retained November-turnout cache cannot silently restore six-county coverage.
/// Development checkouts without that edition retain the legacy aggregate path.
pub fn primary_path(root: &std::path::Path) -> std::path::PathBuf {
    let edition = root.join("primary/2026.json");
    if edition.is_file() {
        edition
    } else {
        root.join("data/primary.json")
    }
}

#[derive(Debug, Serialize)]
pub struct Point {
    pub county: String,
    /// Stable within a county snapshot; the map must highlight every new member.
    pub id: String,
    pub group_index: usize,
    pub old: Vec<String>,
    pub new: Vec<String>,
    pub x: f64,
    /// Percentage of the comparable 2024 turnout; undefined for a zero baseline.
    pub y: Option<f64>,
    pub votes_2024: u64,
    pub votes_2026: u64,
    pub bucket: usize,
    pub counts: BTreeMap<String, f64>,
}

#[derive(Debug, Serialize)]
pub struct Bin {
    pub label: String,
    pub lo: f64,
    pub hi: f64,
    pub groups: u64,
    pub votes_2024: u64,
    pub votes_2026: u64,
    /// Fraction, consistent with the existing turnout bucket endpoint.
    pub ratio: Option<f64>,
}

#[derive(Debug, Default, Serialize)]
pub struct Coverage {
    pub eligible: Cohort,
    pub included: Cohort,
    pub missing_demographics: Cohort,
    pub invalid_demographics: Cohort,
    pub zero_denominator: Cohort,
    pub omitted_zero_baseline: usize,
    pub counties_missing_period: Vec<String>,
}

/// The existing Census buckets crossed with the established partisan bands.
/// The last column retains mixed-margin, tied and missing presidential groups.
#[derive(Debug, Serialize)]
pub struct PartisanMatrix {
    pub columns: Vec<String>,
    pub cells: Vec<Vec<Cohort>>,
    pub totals: Vec<Cohort>,
}

impl PartisanMatrix {
    fn new(rows: usize) -> Self {
        let columns: Vec<_> = crate::LABELS
            .iter()
            .copied()
            .chain(["Mixed / unknown"])
            .map(str::to_owned)
            .collect();
        Self {
            cells: vec![vec![Cohort::default(); columns.len()]; rows],
            totals: vec![Cohort::default(); columns.len()],
            columns,
        }
    }

    fn add(&mut self, row: usize, partisan: Option<usize>, old: u64, new: u64) {
        let column = partisan
            .filter(|&index| index < crate::LABELS.len())
            .unwrap_or(crate::LABELS.len());
        self.cells[row][column].add(old, new);
        self.totals[column].add(old, new);
    }

    fn finish(&mut self) {
        for cell in self
            .cells
            .iter_mut()
            .flatten()
            .chain(self.totals.iter_mut())
        {
            cell.finish();
        }
    }
}

#[derive(Debug, Serialize)]
pub struct View {
    pub county: String,
    pub day: u32,
    pub cohort: String,
    pub metric: Metric,
    pub points: Vec<Point>,
    pub bins: Vec<Bin>,
    pub partisan_matrix: PartisanMatrix,
    pub n: usize,
    pub fit: Option<regression::Fit>,
    pub coverage: Coverage,
    pub method: String,
}

fn edges(metric: &Metric) -> Result<Vec<f64>> {
    ensure!(
        metric.unit == "percent",
        "unsupported demographic metric unit"
    );
    ensure!(
        metric
            .cuts
            .iter()
            .all(|c| c.is_finite() && (0.0..=100.0).contains(c))
            && metric.cuts.windows(2).all(|w| w[0] < w[1]),
        "demographic bucket cuts must increase within 0–100"
    );
    Ok(std::iter::once(0.0)
        .chain(
            metric
                .cuts
                .iter()
                .copied()
                .filter(|c| *c > 0.0 && *c < 100.0),
        )
        .chain(std::iter::once(100.0))
        .collect())
}

enum Exclusion {
    Missing,
    Invalid,
    ZeroDenominator,
}

fn group_counts(
    county: Option<&CountyData>,
    members: &[String],
    metric: &Metric,
) -> std::result::Result<BTreeMap<String, f64>, Exclusion> {
    if members.is_empty() {
        return Err(Exclusion::Invalid);
    }
    let county = county.ok_or(Exclusion::Missing)?;
    let records: Vec<_> = members
        .iter()
        .map(|id| county.precincts.get(id).ok_or(Exclusion::Missing))
        .collect::<std::result::Result<_, _>>()?;
    let mut numerator = 0.0;
    let mut denominator = 0.0;
    for record in &records {
        let n = record
            .counts
            .get(&metric.numerator)
            .copied()
            .flatten()
            .ok_or(Exclusion::Missing)?;
        let d = record
            .counts
            .get(&metric.denominator)
            .copied()
            .flatten()
            .ok_or(Exclusion::Missing)?;
        if !n.is_finite() || !d.is_finite() || n < 0.0 || d < 0.0 || n > d {
            return Err(Exclusion::Invalid);
        }
        numerator += n;
        denominator += d;
    }
    if !numerator.is_finite() || !denominator.is_finite() {
        return Err(Exclusion::Invalid);
    }
    if denominator == 0.0 {
        return Err(Exclusion::ZeroDenominator);
    }
    // Only expose additional count fields when every member has a valid value.
    // A missing unrelated field never makes the requested metric unavailable.
    let mut counts = BTreeMap::new();
    for key in records[0].counts.keys() {
        let values: Option<Vec<f64>> = records
            .iter()
            .map(|r| {
                r.counts
                    .get(key)
                    .copied()
                    .flatten()
                    .filter(|v| v.is_finite() && *v >= 0.0)
            })
            .collect();
        if let Some(values) = values {
            let total: f64 = values.into_iter().sum();
            if total.is_finite() {
                counts.insert(key.clone(), total);
            }
        }
    }
    counts.insert(metric.numerator.clone(), numerator);
    counts.insert(metric.denominator.clone(), denominator);
    Ok(counts)
}

pub fn analyze(
    snapshot: &Snapshot,
    demographics: &Data,
    county: &str,
    day: u32,
    cohort: &str,
    metric: &str,
) -> Result<View> {
    ensure!(
        demographics.schema_version == 1,
        "unsupported demographic schema"
    );
    ensure!(matches!(cohort, "matched" | "unchanged"), "unknown cohort");
    ensure!(
        (1..=snapshot.days).contains(&day),
        "day is outside the available snapshot"
    );
    ensure!(
        county == "all" || snapshot.counties.iter().any(|c| c.id == county),
        "unknown county"
    );
    let Some(metric) = demographics.metrics.iter().find(|m| m.id == metric) else {
        bail!("unknown demographic metric");
    };
    let edges = edges(metric)?;
    let mut bins: Vec<_> = edges
        .windows(2)
        .map(|w| Bin {
            label: format!("{}–{}%", w[0], w[1]),
            lo: w[0],
            hi: w[1],
            groups: 0,
            votes_2024: 0,
            votes_2026: 0,
            ratio: None,
        })
        .collect();
    let mut partisan_matrix = PartisanMatrix::new(bins.len());
    let mut points = Vec::new();
    let mut coverage = Coverage::default();
    for county in snapshot
        .counties
        .iter()
        .filter(|c| county == "all" || c.id == county)
    {
        let Some(period) = county.periods.iter().find(|p| p.day == day) else {
            coverage.counties_missing_period.push(county.id.clone());
            continue;
        };
        for (group_index, group) in period.groups.iter().enumerate().filter(|(_, g)| {
            if !g.available {
                return false;
            }
            if cohort == "unchanged" {
                g.unchanged
            } else {
                true
            }
        }) {
            coverage.eligible.add(group.votes_2024, group.votes_2026);
            let counts =
                match group_counts(demographics.counties.get(&county.id), &group.new, metric) {
                    Ok(counts) => counts,
                    Err(exclusion) => {
                        let total = match exclusion {
                            Exclusion::Missing => &mut coverage.missing_demographics,
                            Exclusion::Invalid => &mut coverage.invalid_demographics,
                            Exclusion::ZeroDenominator => &mut coverage.zero_denominator,
                        };
                        total.add(group.votes_2024, group.votes_2026);
                        continue;
                    }
                };
            let x = counts[&metric.numerator] / counts[&metric.denominator] * 100.0;
            let bucket = bins.iter().position(|b| x < b.hi).unwrap_or(bins.len() - 1);
            let bin = &mut bins[bucket];
            bin.groups += 1;
            bin.votes_2024 += group.votes_2024;
            bin.votes_2026 += group.votes_2026;
            partisan_matrix.add(bucket, group.bucket, group.votes_2024, group.votes_2026);
            coverage.included.add(group.votes_2024, group.votes_2026);
            if group.votes_2024 == 0 {
                coverage.omitted_zero_baseline += 1;
            }
            points.push(Point {
                county: county.id.clone(),
                id: format!("{}:{group_index}", county.id),
                group_index,
                old: group.old.clone(),
                new: group.new.clone(),
                x,
                y: crate::ratio(group.votes_2026, group.votes_2024).map(|r| r * 100.0),
                votes_2024: group.votes_2024,
                votes_2026: group.votes_2026,
                bucket,
                counts,
            });
        }
    }
    partisan_matrix.finish();
    for bin in &mut bins {
        bin.ratio = crate::ratio(bin.votes_2026, bin.votes_2024);
    }
    for total in [
        &mut coverage.eligible,
        &mut coverage.included,
        &mut coverage.missing_demographics,
        &mut coverage.invalid_demographics,
        &mut coverage.zero_denominator,
    ] {
        total.finish();
    }
    let xy: Vec<_> = points
        .iter()
        .filter_map(|p| p.y.map(|y| (p.x, y)))
        .collect();
    Ok(View {
        county: county.into(),
        day,
        cohort: cohort.into(),
        metric: metric.clone(),
        n: xy.len(),
        fit: regression::fit(&xy),
        points,
        bins,
        partisan_matrix,
        coverage,
        method: format!("{} {COHORT_METHOD}", demographics.method)
            .trim()
            .into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn versioned_primary_precedes_retained_cache() {
        let root = std::env::temp_dir().join(format!(
            "turnout-primary-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("primary")).unwrap();
        assert_eq!(primary_path(&root), root.join("data/primary.json"));
        std::fs::write(root.join("primary/2026.json"), b"fixed March evidence").unwrap();
        assert_eq!(primary_path(&root), root.join("primary/2026.json"));
        std::fs::remove_dir_all(root).unwrap();
    }

    fn inputs(groups: serde_json::Value, precincts: serde_json::Value) -> (Snapshot, Data) {
        let snapshot = serde_json::from_value(json!({
            "schema_version":1,"generated_at":"","through":"","days":1,"geography":"",
            "counties":[{"id":"test","name":"Test","status":"current","checked_at":"","error":null,
                "sources":[],"periods":[{"day":1,"through_2024":"","through_2026":"", "county_2024":0,
                    "county_2026":0,"county_ratio":null,"unassigned_2024":0,"unassigned_2026":0,
                    "matched":{"groups":0,"votes_2024":0,"votes_2026":0,"ratio":null},
                    "unchanged":{"groups":0,"votes_2024":0,"votes_2026":0,"ratio":null},
                    "buckets":[],"groups":groups}]}]
        })).unwrap();
        let data = serde_json::from_value(json!({
            "schema_version":1,"metrics":[{"id":"share","label":"Share","unit":"percent", "numerator":"n",
                "denominator":"d","cuts":[20,40,60,80],"source":"Census","vintage":"2020"}],
            "counties":{"test":{"precincts":precincts}},"method":"block points"
        })).unwrap();
        (snapshot, data)
    }

    fn group(new: &[&str], old: u64, current: u64) -> serde_json::Value {
        json!({"old":["old"],"new":new,"votes_2024":old,"votes_2026":current,
            "bucket":0,"unchanged":true,"reason":"","harris":60,"trump":40})
    }

    #[test]
    fn merges_population_counts_instead_of_averaging_percentages() {
        let (s, d) = inputs(
            json!([group(&["1", "2"], 100, 120), group(&["3"], 100, 80)]),
            json!({
                "1":{"counts":{"n":10,"d":10,"other":4}},
                "2":{"counts":{"n":0,"d":90}},"3":{"counts":{"n":80,"d":100}}
            }),
        );
        let view = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        assert_eq!(view.points[0].x, 10.0);
        assert_eq!(view.points[0].counts["d"], 100.0);
        assert!(!view.points[0].counts.contains_key("other"));
        assert_eq!(view.bins[0].ratio, Some(1.2));
        assert_eq!(view.n, 2);
        let fit = view.fit.unwrap();
        assert!((fit.slope + 4.0 / 7.0).abs() < 1e-10);
    }

    #[test]
    fn missing_one_member_or_null_field_excludes_the_whole_group() {
        let (s, d) = inputs(
            json!([group(&["1", "2"], 100, 120), group(&["3"], 10, 8)]),
            json!({
                "1":{"counts":{"n":10,"d":100}},"3":{"counts":{"n":null,"d":100}}
            }),
        );
        let v = analyze(&s, &d, "test", 1, "matched", "share").unwrap();
        assert!(v.points.is_empty());
        assert_eq!(v.coverage.missing_demographics.groups, 2);
        assert_eq!(v.coverage.missing_demographics.votes_2026, 128);
        assert_eq!(v.coverage.included.ratio, None);
    }

    #[test]
    fn empty_population_member_contributes_zero_without_excluding_a_populated_group() {
        let (s, d) = inputs(
            json!([group(&["1", "2"], 10, 12)]),
            json!({
                "1":{"counts":{"n":0,"d":0}},
                "2":{"counts":{"n":30,"d":100}}
            }),
        );
        let v = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        assert_eq!(v.points[0].x, 30.0);
        assert_eq!(v.coverage.zero_denominator.groups, 0);
    }

    #[test]
    fn zero_population_and_invalid_counts_are_excluded_but_zero_baseline_is_bucketed() {
        let (s, d) = inputs(
            json!([
                group(&["1"], 0, 5),
                group(&["2"], 5, 7),
                group(&["3"], 2, 4)
            ]),
            json!({
                "1":{"counts":{"n":20,"d":100}},"2":{"counts":{"n":0,"d":0}},
                "3":{"counts":{"n":101,"d":100}}
            }),
        );
        let v = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        assert_eq!(v.points.len(), 1);
        assert_eq!(v.points[0].y, None);
        assert_eq!(v.bins[1].votes_2026, 5);
        assert_eq!(v.bins[1].ratio, None);
        assert_eq!(v.n, 0);
        assert_eq!(v.coverage.omitted_zero_baseline, 1);
        assert_eq!(v.coverage.zero_denominator.groups, 1);
        assert_eq!(v.coverage.invalid_demographics.groups, 1);
        assert_eq!(v.coverage.eligible.votes_2026, 16);
    }

    #[test]
    fn exact_edges_upper_endpoint_and_vote_reconciliation() {
        let groups: Vec<_> = (0..=5)
            .map(|i| group(&[&i.to_string()], 10, i + 1))
            .collect();
        let precincts: serde_json::Map<String, serde_json::Value> = (0..=5)
            .map(|i| (i.to_string(), json!({"counts":{"n":i*20,"d":100}})))
            .collect();
        let (s, d) = inputs(json!(groups), json!(precincts));
        let v = analyze(&s, &d, "test", 1, "unchanged", "share").unwrap();
        assert_eq!(
            v.points.iter().map(|p| p.bucket).collect::<Vec<_>>(),
            vec![0, 1, 2, 3, 4, 4]
        );
        assert_eq!(v.bins.iter().map(|b| b.votes_2024).sum::<u64>(), 60);
        assert_eq!(v.bins.iter().map(|b| b.votes_2026).sum::<u64>(), 21);
        assert_eq!(v.coverage.included.groups, 6);
    }

    #[test]
    fn invalid_queries_and_cut_edges_are_rejected() {
        let (s, mut d) = inputs(json!([]), json!({}));
        assert!(analyze(&s, &d, "all", 1, "matched", "missing").is_err());
        assert!(analyze(&s, &d, "missing", 1, "matched", "share").is_err());
        assert!(analyze(&s, &d, "all", 2, "matched", "share").is_err());
        assert!(analyze(&s, &d, "all", 1, "unknown", "share").is_err());
        for cuts in [vec![20.0, 20.0], vec![-1.0], vec![101.0], vec![50.0, 20.0]] {
            d.metrics[0].cuts = cuts;
            assert!(analyze(&s, &d, "all", 1, "matched", "share").is_err());
        }
        d.metrics[0].cuts = vec![0.0, 20.0, 100.0];
        assert_eq!(
            analyze(&s, &d, "all", 1, "matched", "share")
                .unwrap()
                .bins
                .len(),
            2
        );
    }

    #[test]
    fn demographic_matched_includes_mixed_partisan_groups_and_unchanged_remains_strict() {
        let mut groups = vec![
            group(&["1"], 10, 12),
            group(&["2"], 10, 9),
            group(&["3"], 10, 8),
        ];
        groups[1]["unchanged"] = json!(false);
        groups[2]["bucket"] = serde_json::Value::Null;
        groups[2]["unchanged"] = json!(false);
        let (s, d) = inputs(
            json!(groups),
            json!({"1":{"counts":{"n":20,"d":100}},
            "2":{"counts":{"n":30,"d":100}},"3":{"counts":{"n":40,"d":100}}}),
        );
        let matched = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        assert_eq!(matched.points.len(), 3);
        assert_eq!(matched.coverage.eligible.groups, 3);
        assert_eq!(matched.coverage.included.votes_2024, 30);
        assert_eq!(matched.coverage.included.votes_2026, 29);
        assert_eq!(matched.points[2].id, "test:2");
        assert!(
            matched
                .method
                .contains("including mixed partisan-margin groups")
        );
        assert_eq!(
            analyze(&s, &d, "all", 1, "unchanged", "share")
                .unwrap()
                .points
                .len(),
            1
        );
    }
    fn assert_matrix_partitions(view: &View) {
        let matrix = &view.partisan_matrix;
        assert_eq!(matrix.columns.len(), crate::LABELS.len() + 1);
        assert_eq!(matrix.columns.last().unwrap(), "Mixed / unknown");
        assert_eq!(matrix.cells.len(), view.bins.len());
        for (row, bin) in matrix.cells.iter().zip(&view.bins) {
            assert_eq!(row.iter().map(|c| c.groups).sum::<u64>(), bin.groups);
            assert_eq!(
                row.iter().map(|c| c.votes_2024).sum::<u64>(),
                bin.votes_2024
            );
            assert_eq!(
                row.iter().map(|c| c.votes_2026).sum::<u64>(),
                bin.votes_2026
            );
            for cell in row {
                assert_eq!(cell.ratio, crate::ratio(cell.votes_2026, cell.votes_2024));
            }
        }
        for (index, total) in matrix.totals.iter().enumerate() {
            assert_eq!(
                matrix.cells.iter().map(|r| r[index].groups).sum::<u64>(),
                total.groups
            );
            assert_eq!(
                matrix
                    .cells
                    .iter()
                    .map(|r| r[index].votes_2024)
                    .sum::<u64>(),
                total.votes_2024
            );
            assert_eq!(
                matrix
                    .cells
                    .iter()
                    .map(|r| r[index].votes_2026)
                    .sum::<u64>(),
                total.votes_2026
            );
        }
        assert_eq!(
            matrix.totals.iter().map(|c| c.groups).sum::<u64>(),
            view.coverage.included.groups
        );
        assert_eq!(
            matrix.totals.iter().map(|c| c.votes_2024).sum::<u64>(),
            view.coverage.included.votes_2024
        );
        assert_eq!(
            matrix.totals.iter().map(|c| c.votes_2026).sum::<u64>(),
            view.coverage.included.votes_2026
        );
    }

    #[test]
    fn joint_matrix_pools_votes_and_respects_demographic_cut_boundaries() {
        let mut trump_a = group(&["a"], 100, 80);
        trump_a["bucket"] = json!(5);
        trump_a["harris"] = json!(20);
        trump_a["trump"] = json!(80);
        let mut trump_b = trump_a.clone();
        trump_b["new"] = json!(["b"]);
        trump_b["votes_2024"] = json!(900);
        trump_b["votes_2026"] = json!(450);
        let mut middle = group(&["d"], 10, 20);
        middle["bucket"] = json!(2);
        let (s, d) = inputs(
            json!([trump_a, trump_b, group(&["c"], 100, 120), middle]),
            json!({"a":{"counts":{"n":80,"d":100}},"b":{"counts":{"n":100,"d":100}},
                "c":{"counts":{"n":80,"d":100}},"d":{"counts":{"n":20,"d":100}}}),
        );
        let v = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        let trump = &v.partisan_matrix.cells[4][5];
        assert_eq!(
            (trump.groups, trump.votes_2024, trump.votes_2026),
            (2, 1000, 530)
        );
        assert_eq!(trump.ratio, Some(0.53));
        assert_eq!(v.partisan_matrix.cells[4][0].ratio, Some(1.2));
        assert_eq!(v.partisan_matrix.cells[1][2].ratio, Some(2.0));
        assert_eq!(v.partisan_matrix.cells[0][2].groups, 0);
        assert_matrix_partitions(&v);
    }

    #[test]
    fn joint_matrix_preserves_unknowns_and_existing_completeness_and_cohort_rules() {
        let mut mixed = group(&["mixed"], 20, 16);
        mixed["bucket"] = serde_json::Value::Null;
        let mut unavailable = group(&["unavailable"], 200, 180);
        unavailable["available"] = json!(false);
        let mut changed = group(&["changed"], 30, 24);
        changed["unchanged"] = json!(false);
        let (s, d) = inputs(
            json!([
                group(&["a"], 10, 8),
                mixed,
                unavailable,
                changed,
                group(&["missing"], 100, 90)
            ]),
            json!({"a":{"counts":{"n":20,"d":100}},"mixed":{"counts":{"n":20,"d":100}},
                "unavailable":{"counts":{"n":20,"d":100}},"changed":{"counts":{"n":20,"d":100}}}),
        );
        let matched = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        let unchanged = analyze(&s, &d, "all", 1, "unchanged", "share").unwrap();
        assert_eq!(matched.coverage.included.groups, 3);
        assert_eq!(unchanged.coverage.included.groups, 2);
        assert_eq!(matched.coverage.missing_demographics.groups, 1);
        assert_eq!(matched.partisan_matrix.cells[1][6].votes_2024, 20);
        assert_eq!(matched.partisan_matrix.totals[0].votes_2024, 40);
        assert_eq!(unchanged.partisan_matrix.totals[0].votes_2024, 10);
        assert_matrix_partitions(&matched);
        assert_matrix_partitions(&unchanged);
    }

    #[test]
    fn joint_matrix_retains_zero_baseline_votes_and_distinguishes_empty_from_zero_turnout() {
        let mut zero_current = group(&["zero"], 100, 0);
        zero_current["bucket"] = json!(5);
        let (s, d) = inputs(
            json!([
                group(&["new"], 0, 7),
                zero_current,
                group(&["empty"], 50, 60)
            ]),
            json!({"new":{"counts":{"n":0,"d":100}},"zero":{"counts":{"n":0,"d":100}},
                "empty":{"counts":{"n":0,"d":0}}}),
        );
        let v = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        assert_eq!(v.partisan_matrix.cells[0][0].votes_2026, 7);
        assert_eq!(v.partisan_matrix.cells[0][0].ratio, None);
        assert_eq!(v.partisan_matrix.cells[0][1].groups, 0);
        assert_eq!(v.partisan_matrix.cells[0][1].ratio, None);
        assert_eq!(v.partisan_matrix.cells[0][5].ratio, Some(0.0));
        assert_eq!(v.coverage.zero_denominator.groups, 1);
        assert_matrix_partitions(&v);
    }

    #[test]
    fn joint_matrix_all_counties_and_county_scope_use_the_same_partitions() {
        let (mut s, mut d) = inputs(
            json!([group(&["a"], 10, 15)]),
            json!({"a":{"counts":{"n":90,"d":100}}}),
        );
        let mut second = s.counties[0].clone();
        second.id = "second".into();
        s.counties.push(second);
        d.counties
            .insert("second".into(), d.counties["test"].clone());
        let all = analyze(&s, &d, "all", 1, "matched", "share").unwrap();
        let one = analyze(&s, &d, "test", 1, "matched", "share").unwrap();
        assert_eq!(all.partisan_matrix.cells[4][0].votes_2024, 20);
        assert_eq!(one.partisan_matrix.cells[4][0].votes_2024, 10);
        assert_matrix_partitions(&all);
        assert_matrix_partitions(&one);
    }
}
