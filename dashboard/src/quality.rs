//! Publication completeness is distinct from a successful source download.
//! Only independently corroborated, same-scope observations enter comparisons.
use crate::{Daily, Reference, Snapshot, analyze, days_through};
use anyhow::{Context, Result, ensure};
use chrono::{Datelike, NaiveDate};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Control {
    pub county: String,
    pub year: i32,
    pub date: NaiveDate,
    pub daily: Option<u64>,
    pub cumulative: Option<u64>,
    pub source: String,
    pub sha256: String,
    pub retrieved_at: String,
    pub scope: String,
    pub completed: bool,
    pub note: String,
    #[serde(default)]
    pub precinct_total: Option<u64>,
    #[serde(default)]
    pub precinct_source: Option<String>,
    #[serde(default)]
    pub precinct_sha256: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Report {
    pub schema_version: u32,
    pub generated_at: String,
    pub controls: Vec<Control>,
    #[serde(skip)]
    pub recovery: Option<Recovery>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Recovery {
    pub schema_version: u32,
    pub method: String,
    pub observations: Vec<RecoveredObservation>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub zero_proofs: Vec<PrecinctZeroProof>,
}
/// Dated, explicit zero cells, kept separate from the original roster's hash.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ZeroEvidence {
    pub through: NaiveDate,
    pub precincts: Vec<String>,
    pub scope: String,
    pub source: String,
    pub sha256: String,
    pub retrieved_at: String,
    pub note: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct PrecinctZeroProof {
    pub county: String,
    pub year: i32,
    #[serde(flatten)]
    pub evidence: ZeroEvidence,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct RecoveredObservation {
    pub supersedes_sha256: Vec<String>,
    pub source: Daily,
}
impl Recovery {
    fn load(root: &Path) -> Result<Option<Self>> {
        let mut editions = Vec::new();
        for file in ["texas-20261025.json", "texas-20261027.json"] {
            let path = root.join("recovery").join(file);
            if path.exists() {
                let edition: Self = serde_json::from_slice(&std::fs::read(path)?)?;
                ensure!(
                    edition.schema_version == 1 && !edition.method.is_empty(),
                    "Invalid source recovery edition"
                );
                editions.push(edition);
            }
        }
        let Some(mut value) = editions.into_iter().reduce(|mut previous, next| {
            previous.method.push_str("; ");
            previous.method.push_str(&next.method);
            previous.observations.extend(next.observations);
            previous.zero_proofs.extend(next.zero_proofs);
            previous
        }) else {
            return Ok(None);
        };
        let mut keys = std::collections::BTreeSet::new();
        for item in &value.observations {
            let d = &item.source;
            ensure!(
                keys.insert((&d.county, d.date, d.cumulative)),
                "Duplicate recovered observation"
            );
            ensure!(
                matches!(d.date.year(), 2024 | 2026)
                    && !d.county.is_empty()
                    && !d.source.is_empty()
                    && d.sha256.len() == 64
                    && !d.counts.is_empty(),
                "Invalid recovered source provenance"
            );
            ensure!(
                item.supersedes_sha256.iter().all(|s| s.len() == 64),
                "Invalid superseded source hash"
            );
        }
        if !value.zero_proofs.is_empty() {
            let references: Vec<Reference> =
                serde_json::from_slice(&std::fs::read(root.join("data/reference.json"))?)?;
            for proof in &mut value.zero_proofs {
                let evidence = &mut proof.evidence;
                ensure!(
                    matches!(proof.year, 2024 | 2026)
                        && evidence.through.year() == proof.year
                        && evidence.through >= crate::start(proof.year),
                    "Invalid zero-evidence date window"
                );
                ensure!(
                    match evidence.scope.as_str() {
                        "all_methods_final_ballots_cast" =>
                            proof.year == 2024
                                && evidence.through == NaiveDate::from_ymd_opt(2024, 11, 5).unwrap(),
                        "in_person_cumulative" =>
                            proof.year == 2026
                                && evidence.through
                                    <= crate::start(2026) + chrono::Duration::days(11),
                        _ => false,
                    },
                    "Unsupported zero-evidence scope or cutoff"
                );
                ensure!(
                    evidence.source.starts_with("https://")
                        && evidence.sha256.len() == 64
                        && evidence.sha256.bytes().all(|b| b.is_ascii_hexdigit())
                        && !evidence.retrieved_at.is_empty()
                        && !evidence.note.is_empty(),
                    "Invalid zero-evidence provenance"
                );
                let reference = references
                    .iter()
                    .find(|r| r.id == proof.county)
                    .context("Zero evidence has no county reference")?;
                let ids: std::collections::BTreeSet<_> = reference
                    .groups
                    .iter()
                    .flat_map(|g| if proof.year == 2024 { &g.old } else { &g.new })
                    .collect();
                let unique: std::collections::BTreeSet<_> = evidence.precincts.iter().collect();
                ensure!(
                    !unique.is_empty()
                        && unique.len() == evidence.precincts.len()
                        && unique
                            .iter()
                            .all(|p| ids.contains(*p) && crate::normalize(p) == ***p),
                    "Zero evidence must identify distinct exact native precincts"
                );
                evidence.precincts.sort();
            }
        }
        Ok(Some(value))
    }
    fn apply(&self, county: &str, sources: &[Daily]) -> Vec<Daily> {
        let mut output = strip_zero_evidence(sources);

        for item in self
            .observations
            .iter()
            .filter(|v| v.source.county == county)
        {
            let replacement = &item.source;
            if let Some(current) = output.iter_mut().find(|d| {
                d.county == county
                    && d.date == replacement.date
                    && d.cumulative == replacement.cumulative
            }) {
                // A later, unreviewed publisher revision is never silently replaced.
                if item.supersedes_sha256.contains(&current.sha256) {
                    *current = replacement.clone();
                }
            } else {
                output.push(replacement.clone());
            }
        }
        for proof in self.zero_proofs.iter().filter(|p| p.county == county) {
            let evidence = &proof.evidence;
            let valid: Vec<_> = evidence
                .precincts
                .iter()
                .filter(|id| {
                    !output.iter().any(|d| {
                        d.date.year() == proof.year
                            && d.date >= crate::start(proof.year)
                            && d.date <= evidence.through
                            && (d.counts.get(*id).is_some_and(|n| *n > 0)
                                || d.unavailable_precincts
                                    .iter()
                                    .any(|p| crate::normalize(p) == **id))
                    })
                })
                .cloned()
                .collect();
            for day in output.iter_mut().filter(|d| {
                d.date.year() == proof.year
                    && d.date >= crate::start(proof.year)
                    && d.date <= evidence.through
            }) {
                let mut added = Vec::new();
                for id in &valid {
                    if let std::collections::btree_map::Entry::Vacant(cell) =
                        day.counts.entry(id.clone())
                    {
                        cell.insert(0);
                        added.push(id.clone());
                    }
                }
                if !added.is_empty() {
                    let mut support = evidence.clone();
                    support.precincts = added;
                    day.zero_evidence.push(support);
                }
            }
        }
        output.sort_by_key(|d| (d.date, d.cumulative));
        output
    }
}

// Never let a previously derived zero survive without its currently valid proof.
fn strip_zero_evidence(sources: &[Daily]) -> Vec<Daily> {
    let mut output = sources.to_vec();
    for day in &mut output {
        for evidence in std::mem::take(&mut day.zero_evidence) {
            for id in evidence.precincts {
                if day.counts.get(&id) == Some(&0) {
                    day.counts.remove(&id);
                }
            }
        }
    }
    output
}

// A documented integer reconciliation precision, never a percentage allowance.
// Zero controls require exact equality; even tiny totals cannot turn absence into zero.
fn agrees(actual: u64, expected: u64) -> bool {
    actual == expected || expected > 1 && actual.abs_diff(expected) <= 1
}

// This immutable Harris 2024 archive omits residence precincts with positive
// same-day official SOS observations, even on a date whose county totals agree.
// Keep its explicit observations, but never certify its omissions as zeros.
// Source hashes and the live recheck are in sources/texas-stress/source-findings.md.
const HARRIS_2024_UNCONFIRMED_ZEROS: &str =
    "b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49";

impl Report {
    pub fn load(root: &Path) -> Result<Self> {
        let bytes = std::fs::read(root.join("data/completeness.json"))
            .context("Independent completion controls unavailable")?;
        let mut report: Self = serde_json::from_slice(&bytes)?;
        report.recovery = Recovery::load(root)?;
        ensure!(
            report.schema_version == 1,
            "Unsupported completion controls"
        );
        let mut seen = std::collections::BTreeSet::new();
        for c in &report.controls {
            ensure!(c.year == c.date.year(), "Control year/date mismatch");
            ensure!(
                seen.insert((&c.county, c.year, c.date)),
                "Duplicate completion control"
            );
            ensure!(
                !c.source.is_empty() && c.sha256.len() == 64,
                "Control provenance missing"
            );
        }
        Ok(report)
    }

    fn control(&self, county: &str, date: NaiveDate) -> Option<&Control> {
        self.controls
            .iter()
            .find(|c| c.county == county && c.date == date && c.completed && c.scope == "in_person")
    }

    /// Keep every usable dated observation. Completion controls establish zeros,
    /// not whole-county admission. Historical age alone cannot establish zeros.
    pub fn sources(&self, county: &str, sources: &[Daily]) -> Vec<Daily> {
        let sources = self
            .recovery
            .as_ref()
            .map(|r| r.apply(county, sources))
            .unwrap_or_else(|| strip_zero_evidence(sources));
        sources
            .into_iter()
            .filter(|d| matches!(d.date.year(), 2024 | 2026))
            .map(|mut d| {
                d.unavailable_precincts = d.unavailable_precincts.iter().map(|p| {
                    let p = crate::normalize(p);
                    if p.is_empty() { "UNASSIGNED".into() } else { p }
                }).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
                d.counts.retain(|p, _| !d.unavailable_precincts.contains(&crate::normalize(p)));
                let expected = self
                    .control(&d.county, d.date)
                    .and_then(|c| if d.cumulative { c.cumulative } else { c.daily });
                if d.date.year()==2026 && let Some(n)=expected && !agrees(d.counts.values().sum(),n) && !d.note.to_lowercase().contains("county control") {
                    d.note.push_str(&format!(" County control reports {n} votes; this source reports {}. Matched precinct counts use reported observations and remain subject to revision.",d.counts.values().sum::<u64>()));
                }
                d.complete = expected.is_some_and(|n| d.counts.values().sum::<u64>() == n)
                    && d.unavailable_precincts.is_empty()
                    && d.counts.get("UNASSIGNED").copied().unwrap_or(0) == 0
                    && d.sha256 != HARRIS_2024_UNCONFIRMED_ZEROS;
                d
            })
            .collect()
    }

    pub fn snapshot(&self, raw: &Snapshot, references: &[Reference]) -> Result<Snapshot> {
        let mut snapshot = raw.clone();
        snapshot.completeness_sha256 = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&(self, &self.recovery))?)
        );
        let refs: BTreeMap<_, _> = references.iter().map(|r| (r.id.as_str(), r)).collect();
        for c in &mut snapshot.counties {
            let r = refs.get(c.id.as_str()).context("No geographic reference")?;
            c.sources = self.sources(&c.id, &c.sources);
            c.reference_groups =
                analyze(r, &crate::Counts::new(), &crate::Counts::new(), 1)?.groups;
            for g in &mut c.reference_groups {
                g.available = false;
            }
            c.periods = (1..=snapshot.days)
                .filter_map(|day| crate::matching::period(r, &c.sources, day, true))
                .collect();
            let latest = c.periods.iter().find(|p| p.day == snapshot.days);
            c.status = if latest.is_some() {
                "current"
            } else if c.periods.is_empty() {
                "missing"
            } else {
                "partial"
            }
            .into();
            c.error = if latest.is_none() {
                Some("No matched cumulative precinct subset at this cutoff; other dates remain available".into())
            } else {
                None
            };
        }
        Ok(snapshot)
    }

    pub fn history(&self, history: &mut crate::trends::History) {
        for (county, data) in &mut history.counties {
            data.sources = self.sources(county, &data.sources);
        }
    }

    pub fn statewide(&self, mut data: crate::statewide::Data) -> crate::statewide::Data {
        // These controls certify early in-person reports only.
        if data.voting_method != "in_person" {
            return data;
        }
        for county in &mut data.counties {
            for d in &mut county.days {
                for year in [2024, 2026] {
                    let date = if year == 2024 {
                        d.date_2024
                    } else {
                        d.date_2026
                    };
                    let future = year == 2026 && date > data.through;
                    let c = (!future).then(|| self.control(&county.id, date)).flatten();
                    let prior = if year == 2024 {
                        (d.votes_2024, d.cumulative_2024, d.status_2024.as_str())
                    } else {
                        (d.votes_2026, d.cumulative_2026, d.status_2026.as_str())
                    };
                    let (daily, cumulative, status) = match c {
                        Some(c) => (
                            c.daily.or(prior.0),
                            c.cumulative.or(prior.1),
                            "county_report",
                        ),
                        None if future => (None, None, "future"),
                        None => (prior.0, prior.1, prior.2),
                    };
                    let status = status.to_string();
                    if year == 2024 {
                        d.votes_2024 = daily;
                        d.cumulative_2024 = cumulative;
                        d.status_2024 = status;
                    } else {
                        d.votes_2026 = daily;
                        d.cumulative_2026 = cumulative;
                        d.status_2026 = status;
                    }
                }
                if d.date_2026 <= data.through {
                    if d.votes_2024.is_none() || d.votes_2026.is_none() {
                        d.votes_2024 = None;
                        d.votes_2026 = None;
                    }
                    if d.cumulative_2024.is_none() || d.cumulative_2026.is_none() {
                        d.cumulative_2024 = None;
                        d.cumulative_2026 = None;
                    }
                }
            }
        }
        let mut proven_sources: BTreeMap<_, _> = data
            .sources
            .iter()
            .cloned()
            .map(|s| ((s.year, s.date, s.url.clone(), s.sha256.clone()), s))
            .collect();
        for c in &self.controls {
            if !c.completed || c.scope != "in_person" || c.year == 2026 && c.date > data.through {
                continue;
            }
            proven_sources
                .entry((c.year, c.date, c.source.clone(), c.sha256.clone()))
                .or_insert_with(|| {
                    data.sources
                        .iter()
                        .find(|s| {
                            s.year == c.year
                                && s.date == c.date
                                && s.url == c.source
                                && s.sha256 == c.sha256
                        })
                        .cloned()
                        .unwrap_or_else(|| crate::statewide::Source {
                            year: c.year,
                            date: c.date,
                            url: c.source.clone(),
                            method: "GET".into(),
                            form: None,
                            retrieved_at: c.retrieved_at.clone(),
                            sha256: c.sha256.clone(),
                            transport_sha256: c.sha256.clone(),
                            rows: 1,
                            source_updated: None,
                            status: "independently_verified".into(),
                        })
                });
        }
        data.sources = proven_sources.into_values().collect();
        data.scope = "Available in-person reports matched separately at each date and measure. Native county controls replace underfilled SOS aggregates; matched residence-precinct subsets use the same geography in both years. County aggregate-only reports remain available where precinct matching is unsupported.".into();
        data
    }
}

pub fn pair_trends(view: &mut crate::trends::View) {
    for bucket in view
        .buckets
        .iter_mut()
        .chain(std::iter::once(&mut view.totals))
    {
        for day in &mut bucket.days {
            if day.day <= view.observed_days {
                if day.daily_2024.is_none() || day.daily_2026.is_none() {
                    day.daily_2024 = None;
                    day.daily_2026 = None;
                }
                if day.cumulative_2024.is_none() || day.cumulative_2026.is_none() {
                    day.cumulative_2024 = None;
                    day.cumulative_2026 = None;
                }
            }
        }
    }
}

/// Missing or malformed controls fail closed; source caches remain intact.
pub fn qualify(root: &Path, raw: &Snapshot) -> Result<Snapshot> {
    let report = Report::load(root).unwrap_or_default();
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json"))?)?;
    ensure!(
        raw.days == days_through(raw.through.parse()?)?,
        "Snapshot cutoff mismatch"
    );
    report.snapshot(raw, &references)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::start;
    #[test]
    fn matching_control_cannot_recertify_quarantined_precincts() {
        let d = Daily {
            allow_daily_difference: None,
            zero_evidence: Vec::new(),
            unavailable_precincts: vec!["001".into()],
            complete: true,
            county: "x".into(),
            date: start(2026),
            counts: crate::Counts::from([("1".into(), 9), ("2".into(), 10)]),
            source: "official".into(),
            sha256: "a".repeat(64),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: false,
        };
        let report = Report {
            controls: vec![Control {
                county: "x".into(),
                year: 2026,
                date: start(2026),
                daily: Some(10),
                cumulative: Some(10),
                source: "independent total".into(),
                sha256: "b".repeat(64),
                retrieved_at: String::new(),
                scope: "in_person".into(),
                completed: true,
                note: String::new(),
                precinct_total: None,
                precinct_source: None,
                precinct_sha256: None,
            }],
            ..Default::default()
        };
        let accepted = report.sources("x", &[d]);
        assert_eq!(accepted[0].counts, crate::Counts::from([("2".into(), 10)]));
        assert_eq!(accepted[0].unavailable_precincts, vec!["1"]);
        assert!(!accepted[0].complete);
        assert!(!crate::matching::full(&accepted, 2026, 1, false));
    }

    #[test]
    fn incomplete_county_controls_do_not_remove_reported_precincts() {
        let d = Daily {
            allow_daily_difference: None,
            zero_evidence: Vec::new(),
            unavailable_precincts: Vec::new(),
            complete: false,
            county: "x".into(),
            date: start(2026),
            counts: crate::Counts::from([("1".into(), 10)]),
            source: "official".into(),
            sha256: "a".repeat(64),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: false,
        };
        let accepted = Report::default().sources("x", std::slice::from_ref(&d));
        assert_eq!(accepted.len(), 1);
        assert!(!accepted[0].complete);
        let mut old = d;
        old.date = start(2024);
        assert!(!Report::default().sources("x", &[old])[0].complete);
    }
    #[test]
    fn ambiguous_zero_is_not_confirmed_by_reconciliation_tolerance() {
        assert!(!agrees(1, 0));
        assert!(!agrees(0, 1));
        assert!(agrees(479408, 479409));
    }

    #[test]
    fn historical_age_does_not_prove_an_absent_precinct_had_zero_votes() {
        let mut d = Daily {
            allow_daily_difference: None,
            zero_evidence: Vec::new(),
            unavailable_precincts: Vec::new(),
            complete: true,
            county: "x".into(),
            date: start(2024),
            counts: crate::Counts::from([("1".into(), 10)]),
            source: "official".into(),
            sha256: "a".repeat(64),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: false,
        };
        assert!(!Report::default().sources("x", &[d.clone()])[0].complete);
        let mut report = Report {
            controls: vec![Control {
                county: "x".into(),
                year: 2024,
                date: start(2024),
                daily: Some(11),
                cumulative: Some(11),
                source: "independent total".into(),
                sha256: "b".repeat(64),
                retrieved_at: String::new(),
                scope: "in_person".into(),
                completed: true,
                note: String::new(),
                precinct_total: None,
                precinct_source: None,
                precinct_sha256: None,
            }],
            ..Default::default()
        };
        // A missing voter is not rounding precision when certifying a zero precinct.
        assert!(!report.sources("x", &[d.clone()])[0].complete);
        report.controls[0].daily = Some(10);
        assert!(report.sources("x", &[d.clone()])[0].complete);
        d.sha256 = HARRIS_2024_UNCONFIRMED_ZEROS.into();
        assert!(!report.sources("x", &[d.clone()])[0].complete);
        d.sha256 = "a".repeat(64);
        // An unassigned voter could belong to any precinct absent from the roster.
        d.counts.insert("UNASSIGNED".into(), 1);
        report.controls[0].daily = Some(11);
        assert!(!report.sources("x", &[d])[0].complete);
    }
}
