//! Reproduce a snapshot from retained aggregates, without any source requests.
use crate::*;
use anyhow::{Context, Result, ensure};
use sha2::{Digest, Sha256};
use std::path::Path;

fn canonical(mut days: Vec<Daily>, county: &str) -> Result<Vec<Daily>> {
    for day in &mut days {
        ensure!(day.county == county, "cached county identity mismatch");
        let mut counts = Counts::new();
        for (label, count) in &day.counts {
            let label = normalize(label);
            *counts
                .entry(if label.is_empty() {
                    "UNASSIGNED".into()
                } else {
                    label
                })
                .or_default() += count;
        }
        day.counts = counts;
    }
    Ok(days)
}
pub fn from_cache(root: &Path, through: chrono::NaiveDate) -> Result<Snapshot> {
    let n = days_through(through)?;
    let bytes = std::fs::read(root.join("data/reference.json"))?;
    let references: Vec<Reference> = serde_json::from_slice(&bytes)?;
    let mut counties = vec![];
    for reference in &references {
        let mut sources = vec![];
        for year in [2024, 2026] {
            let path = root.join(format!("data/cache/{}/{year}-series.json", reference.id));
            let raw = std::fs::read(&path).or_else(|error| {
                if year == 2024 {
                    std::fs::read(root.join(format!(
                        "data/history-cache/{}/{year}-series.json",
                        reference.id
                    )))
                } else {
                    Err(error)
                }
            });
            if let Ok(raw) = raw {
                sources.extend(canonical(
                    serde_json::from_slice(&raw).context("invalid aggregate cache")?,
                    &reference.id,
                )?);
            }
        }
        let mut periods = vec![];
        let mut missing = vec![];
        for day in 1..=n {
            match (sum_days(&sources, 2024, day), sum_days(&sources, 2026, day)) {
                (Ok(old), Ok(new)) => periods.push(analyze(reference, &old, &new, day)?),
                _ => missing.push(day),
            }
        }
        let complete = periods.last().is_some_and(|p| p.day == n);
        let status = if complete {
            "current"
        } else if periods.is_empty() {
            "missing"
        } else {
            "stale"
        };
        let error = if complete {
            None
        } else {
            Some(format!(
                "No complete paired precinct reports for day(s) {}; unavailable dates are not zero",
                missing
                    .iter()
                    .map(u32::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            ))
        };
        let checked_at = sources
            .iter()
            .map(|d| d.retrieved_at.as_str())
            .max()
            .unwrap_or("")
            .to_string();
        counties.push(County {
            reference_groups: vec![],
            id: reference.id.clone(),
            name: reference.name.clone(),
            status: status.into(),
            checked_at,
            error,
            periods,
            sources,
        });
    }
    let raw = Snapshot {
        completeness_sha256: String::new(),
        reference_sha256: format!("{:x}", Sha256::digest(&bytes)),
        schema_version: 1,
        generated_at: chrono::Utc::now().to_rfc3339(),
        through: through.to_string(),
        days: n,
        geography: GEOGRAPHY.into(),
        counties,
    };
    crate::quality::qualify(root, &raw)
}

/// Fill the historical API only from retained sources, preserving prior proven reports.
pub fn history_from_cache(root: &Path, snapshot: &Snapshot) -> Result<trends::History> {
    let mut history: trends::History = std::fs::read(root.join("data/history.json"))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    for county in &snapshot.counties {
        let old = history.counties.remove(&county.id).unwrap_or_default();
        let cached: Vec<Daily> =
            std::fs::read(root.join(format!("data/history-cache/{}/2024-series.json", county.id)))
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .unwrap_or_default();
        let sources = trends::merge_sources(
            old.sources
                .into_iter()
                .chain(cached)
                .chain(county.sources.iter().cloned()),
        );
        history.counties.insert(
            county.id.clone(),
            trends::CountyHistory {
                sources,
                errors: old.errors,
            },
        );
    }
    history.generated_at = chrono::Utc::now().to_rfc3339();
    Ok(history)
}
