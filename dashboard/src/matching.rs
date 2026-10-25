//! Available geography is matched separately at every date and measure.
use crate::*;
use chrono::Datelike;
use std::collections::BTreeSet;

fn exact(sources: &[Daily], year: i32, day: u32, cumulative: bool) -> Option<&Daily> {
    let date = start(year) + chrono::Duration::days(i64::from(day) - 1);
    sources
        .iter()
        .filter(|d| d.date == date && d.cumulative == cumulative)
        .max_by_key(|d| &d.retrieved_at)
}
pub fn full(sources: &[Daily], year: i32, day: u32, cumulative: bool) -> bool {
    if let Some(d) = exact(sources, year, day, cumulative) {
        return d.complete;
    }
    if cumulative {
        exact(sources, year, day, false).is_some_and(|d| d.complete)
            && (day == 1 || full(sources, year, day - 1, true))
    } else {
        let Some(now) = exact(sources, year, day, true).filter(|d| d.complete) else {
            return false;
        };
        if day == 1 {
            return true;
        }
        if !full(sources, year, day - 1, true) {
            return false;
        }
        // A complete roster can contain a downward revision. That precinct's
        // daily difference is unknown, not an implicit zero in a complete day.
        counts(sources, year, day - 1, true).is_some_and(|previous| {
            previous
                .iter()
                .all(|(id, prior)| now.counts.get(id).copied().unwrap_or(0) >= *prior)
        })
    }
}
pub fn counts(sources: &[Daily], year: i32, day: u32, cumulative: bool) -> Option<Counts> {
    let universe = sources
        .iter()
        .filter(|s| s.date.year() == year)
        .flat_map(|s| s.counts.keys().cloned())
        .collect();
    counts_with_ids(sources, year, day, cumulative, &universe)
}

pub(crate) fn counts_with_ids(
    sources: &[Daily],
    year: i32,
    day: u32,
    cumulative: bool,
    universe: &BTreeSet<String>,
) -> Option<Counts> {
    if !(1..=12).contains(&day) {
        return None;
    }
    if let Some(d) = exact(sources, year, day, cumulative) {
        let mut counts = d.counts.clone();
        if d.complete {
            for id in universe {
                counts.entry(id.clone()).or_default();
            }
        }
        return Some(counts);
    }
    if cumulative {
        let now = exact(sources, year, day, false)?;
        let now_counts = counts_with_ids(sources, year, day, false, universe)?;
        if day == 1 {
            return counts_with_ids(sources, year, day, false, universe);
        }
        let previous = counts_with_ids(sources, year, day - 1, true, universe)?;
        let prior_full = full(sources, year, day - 1, true);
        let universe: BTreeSet<_> = previous.keys().chain(now_counts.keys()).cloned().collect();
        let mut result = Counts::new();
        for id in universe {
            if (prior_full || previous.contains_key(&id))
                && (now.complete || now_counts.contains_key(&id))
            {
                result.insert(
                    id.clone(),
                    previous.get(&id).copied().unwrap_or(0)
                        + now_counts.get(&id).copied().unwrap_or(0),
                );
            }
        }
        return Some(result);
    }
    let now = exact(sources, year, day, true)?;
    let now_counts = counts_with_ids(sources, year, day, true, universe)?;
    if day == 1 {
        return Some(now_counts);
    }
    let previous = counts_with_ids(sources, year, day - 1, true, universe)?;
    let prior_full = full(sources, year, day - 1, true);
    let universe: BTreeSet<_> = now_counts.keys().chain(previous.keys()).cloned().collect();
    Some(
        universe
            .into_iter()
            .filter_map(|id| {
                let a = previous.get(&id).copied().or(prior_full.then_some(0))?;
                let b = now_counts.get(&id).copied().or(now.complete.then_some(0))?;
                b.checked_sub(a).map(|n| (id, n))
            })
            .collect(),
    )
}

pub fn period(
    reference: &Reference,
    sources: &[Daily],
    day: u32,
    cumulative: bool,
) -> Option<Period> {
    let old_ids = reference
        .groups
        .iter()
        .flat_map(|g| g.old.iter().cloned())
        .collect();
    let new_ids = reference
        .groups
        .iter()
        .flat_map(|g| g.new.iter().cloned())
        .collect();
    let mut old = counts_with_ids(sources, 2024, day, cumulative, &old_ids)?;
    let mut new = counts_with_ids(sources, 2026, day, cumulative, &new_ids)?;
    if full(sources, 2024, day, cumulative) {
        for id in reference.groups.iter().flat_map(|g| &g.old) {
            old.entry(id.clone()).or_default();
        }
    }
    if full(sources, 2026, day, cumulative) {
        for id in reference.groups.iter().flat_map(|g| &g.new) {
            new.entry(id.clone()).or_default();
        }
    }
    let mut p = analyze(reference, &old, &new, day).ok()?;
    p.coverage = MatchedCoverage {
        total_groups: p.groups.len() as u64,
        total_precincts: reference.groups.iter().map(|g| g.new.len() as u64).sum(),
        baseline_votes_2024: if cumulative {
            sum_days(sources, 2024, day)
                .ok()
                .map(|c| c.values().sum())
                .unwrap_or_else(|| old.values().sum())
        } else {
            old.values().sum()
        },
        reported_votes_2024: old.values().sum(),
        reported_votes_2026: new.values().sum(),
        ..Default::default()
    };
    p.matched = Cohort::default();
    p.unchanged = Cohort::default();
    for b in &mut p.buckets {
        b.matched = Cohort::default();
        b.unchanged = Cohort::default();
    }
    p.county_2024 = 0;
    p.county_2026 = 0;
    for g in &mut p.groups {
        g.available = g.old.iter().all(|id| old.contains_key(id))
            && g.new.iter().all(|id| new.contains_key(id));
        if !g.available {
            g.votes_2024 = 0;
            g.votes_2026 = 0;
            continue;
        }
        p.coverage.available_groups += 1;
        p.coverage.available_precincts += g.new.len() as u64;
        p.county_2024 += g.votes_2024;
        p.county_2026 += g.votes_2026;
        if let Some(b) = g.bucket {
            p.buckets[b].matched.add(g.votes_2024, g.votes_2026);
            p.matched.add(g.votes_2024, g.votes_2026);
            if g.unchanged {
                p.buckets[b].unchanged.add(g.votes_2024, g.votes_2026);
                p.unchanged.add(g.votes_2024, g.votes_2026);
            }
        }
    }
    p.coverage.available_baseline_votes_2024 = p.county_2024;
    if p.coverage.available_groups == 0 {
        return None;
    }
    p.county_ratio = ratio(p.county_2026, p.county_2024);
    p.matched.finish();
    p.unchanged.finish();
    for b in &mut p.buckets {
        b.matched.finish();
        b.unchanged.finish();
    }
    Some(p)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn source(year: i32, day: u32, values: &[(&str, u64)], complete: bool) -> Daily {
        Daily {
            complete,
            county: "x".into(),
            date: start(year) + chrono::Duration::days(i64::from(day) - 1),
            counts: values.iter().map(|(p, v)| (p.to_string(), *v)).collect(),
            source: "test".into(),
            sha256: "a".repeat(64),
            retrieved_at: String::new(),
            note: String::new(),
            cumulative: false,
        }
    }
    #[test]
    fn cumulative_requires_each_precinct_day_but_daily_keeps_available_reports() {
        let sources = vec![
            source(2026, 1, &[("1", 10), ("2", 20)], false),
            source(2026, 2, &[("1", 5)], false),
        ];
        assert_eq!(counts(&sources, 2026, 1, false).unwrap().len(), 2);
        assert_eq!(
            counts(&sources, 2026, 2, true).unwrap(),
            Counts::from([("1".into(), 15)])
        );
        assert_eq!(
            counts(&sources, 2026, 2, false).unwrap(),
            Counts::from([("1".into(), 5)])
        );
    }
    #[test]
    fn only_a_complete_source_can_establish_absent_precinct_zero() {
        let sources = vec![
            source(2026, 1, &[("1", 10), ("2", 20)], false),
            source(2026, 2, &[("1", 5)], true),
        ];
        assert_eq!(counts(&sources, 2026, 2, true).unwrap()["2"], 20);
        assert_eq!(counts(&sources, 2026, 2, false).unwrap()["2"], 0);
    }
    #[test]
    fn missing_whole_day_does_not_invent_a_cumulative_count() {
        let s = vec![source(2026, 2, &[("1", 5)], false)];
        assert!(counts(&s, 2026, 2, true).is_none());
        assert!(counts(&s, 2026, 2, false).is_some());
    }
    #[test]
    fn cumulative_anchor_and_daily_prefix_recover_available_measurements() {
        let first = source(2026, 1, &[("1", 4), ("2", 10)], false);
        let mut cumulative = source(2026, 2, &[("1", 10), ("2", 9)], false);
        cumulative.cumulative = true;
        let third = source(2026, 3, &[("1", 7)], false);
        let sources = vec![first, cumulative, third];
        assert_eq!(
            counts(&sources, 2026, 2, false).unwrap(),
            Counts::from([("1".into(), 6)])
        );
        assert_eq!(
            counts(&sources, 2026, 3, true).unwrap(),
            Counts::from([("1".into(), 17)])
        );
    }
}
