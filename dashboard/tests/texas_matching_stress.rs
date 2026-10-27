//! Adversarial fixtures for the point where anonymous source data becomes chart cohorts.
use std::collections::BTreeMap;
use texas_turnout::{
    Counts, County, Daily, Group, GroupResult, Party, Reference, Snapshot, matching, trends,
};

fn source(year: i32, day: u32, counts: &[(&str, u64)]) -> Daily {
    Daily {
        allow_daily_difference: None,
        zero_evidence: Vec::new(),
        unavailable_precincts: Vec::new(),
        county: "fixture".into(),
        date: texas_turnout::start(year) + chrono::Duration::days(i64::from(day - 1)),
        counts: counts.iter().map(|(id, n)| ((*id).into(), *n)).collect(),
        cumulative: true,
        complete: true,
        source: "anonymous deterministic fixture".into(),
        sha256: "fixture".into(),
        retrieved_at: "2026-10-25T00:00:00Z".into(),
        note: String::new(),
    }
}

fn reference() -> Reference {
    Reference {
        id: "fixture".into(),
        name: "Fixture".into(),
        state_id: 1,
        groups: vec![
            Group {
                old: vec!["a".into()],
                new: vec!["a".into()],
            },
            Group {
                old: vec!["b".into()],
                new: vec!["b".into()],
            },
        ],
        exact_pairs: vec![["a".into(), "a".into()], ["b".into(), "b".into()]],
        presidential: BTreeMap::from([
            (
                "a".into(),
                Party {
                    harris: 60,
                    trump: 40,
                },
            ),
            (
                "b".into(),
                Party {
                    harris: 60,
                    trump: 40,
                },
            ),
        ]),
        references: serde_json::Value::Null,
    }
}

fn snapshot(reference: &Reference, sources: Vec<Daily>) -> Snapshot {
    let template = texas_turnout::analyze(reference, &Counts::new(), &Counts::new(), 2).unwrap();
    Snapshot {
        schema_version: 1,
        completeness_sha256: String::new(),
        reference_sha256: String::new(),
        generated_at: String::new(),
        through: "2026-10-20".into(),
        days: 2,
        geography: String::new(),
        counties: vec![County {
            id: "fixture".into(),
            name: "Fixture".into(),
            status: "current".into(),
            checked_at: String::new(),
            error: None,
            periods: vec![],
            reference_groups: template.groups,
            sources,
        }],
    }
}

#[test]
fn complete_cumulative_revision_is_not_a_daily_zero() {
    let sources = vec![
        source(2024, 1, &[("a", 10), ("b", 10)]),
        source(2024, 2, &[("a", 20), ("b", 20)]),
        source(2026, 1, &[("a", 5), ("b", 5)]),
        source(2026, 2, &[("a", 4), ("b", 7)]),
    ];
    assert_eq!(
        matching::counts(&sources, 2026, 2, false),
        Some(Counts::from([("b".into(), 2)]))
    );
    let view = trends::analyze(
        &snapshot(&reference(), sources),
        &trends::History::default(),
        None,
        "all",
        "matched",
        "partisan",
    )
    .unwrap();
    let day = &view.totals.days[1];
    // Only b has a valid same-day delta; a's downward correction is unavailable.
    assert_eq!(
        (day.daily_2024, day.daily_2026, day.daily_groups),
        (Some(10), Some(2), 1)
    );
    // Both valid cumulative observations remain in the cumulative chart.
    assert_eq!(
        (
            day.cumulative_2024,
            day.cumulative_2026,
            day.cumulative_groups
        ),
        (Some(40), Some(11), 2)
    );
}

#[test]
fn correction_preserves_other_inferred_zero_precincts() {
    let mut reference = reference();
    reference.groups.push(Group {
        old: vec!["c".into()],
        new: vec!["c".into()],
    });
    reference.presidential.insert(
        "c".into(),
        Party {
            harris: 60,
            trump: 40,
        },
    );
    let sources = vec![
        source(2024, 1, &[("a", 10), ("b", 10), ("c", 10)]),
        source(2024, 2, &[("a", 20), ("b", 20), ("c", 20)]),
        source(2026, 1, &[("a", 5), ("b", 5)]),
        source(2026, 2, &[("a", 4), ("b", 7)]),
    ];
    let view = trends::analyze(
        &snapshot(&reference, sources),
        &trends::History::default(),
        None,
        "all",
        "matched",
        "partisan",
    )
    .unwrap();
    // c is a proved zero in both complete current rosters, despite never being explicit.
    let day = &view.totals.days[1];
    assert_eq!(
        (day.daily_2024, day.daily_2026, day.daily_groups),
        (Some(20), Some(2), 2)
    );
}

#[test]
fn incomplete_presidential_group_has_no_inferred_winner() {
    let mut reference = reference();
    reference.groups = vec![Group {
        old: vec!["a".into(), "missing".into()],
        new: vec!["a".into()],
    }];
    let period = texas_turnout::analyze(
        &reference,
        &Counts::from([("a".into(), 2), ("missing".into(), 1000)]),
        &Counts::from([("a".into(), 1100)]),
        2,
    )
    .unwrap();
    let group: &GroupResult = &period.groups[0];
    assert_eq!(group.bucket, None);
    assert_eq!(
        (group.harris, group.trump),
        (0, 0),
        "An incomplete presidential sum cannot identify a winner"
    );
    assert_eq!((group.votes_2024, group.votes_2026), (1002, 1100));
}

#[test]
fn complete_empty_precincts_still_establish_daily_zero() {
    let sources = vec![
        source(2024, 1, &[("a", 10)]),
        source(2024, 2, &[("a", 20)]),
        source(2026, 1, &[("a", 5)]),
        source(2026, 2, &[("a", 7)]),
    ];
    let view = trends::analyze(
        &snapshot(&reference(), sources),
        &trends::History::default(),
        None,
        "all",
        "matched",
        "partisan",
    )
    .unwrap();
    assert_eq!(
        (
            view.totals.days[1].daily_2024,
            view.totals.days[1].daily_2026,
            view.totals.days[1].daily_groups
        ),
        (Some(10), Some(2), 2)
    );
}

#[test]
fn seeded_revision_stress_keeps_maximum_same_day_common_geography() {
    let mut state = 0x5eed_u64;
    let mut draw = || {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        state >> 32
    };
    for _ in 0..1000 {
        let mut reference = reference();
        let mut sources = Vec::new();
        let mut expected = (0u64, 0u64, 0usize);
        let mut old_totals = Counts::new();
        let mut new_totals = Counts::new();
        let mut values = [Counts::new(), Counts::new(), Counts::new(), Counts::new()];
        reference.groups.clear();
        reference.presidential.clear();
        reference.exact_pairs.clear();
        for i in 0..8 {
            let id = i.to_string();
            reference.groups.push(Group {
                old: vec![id.clone()],
                new: vec![id.clone()],
            });
            reference.presidential.insert(
                id.clone(),
                Party {
                    harris: 60,
                    trump: 40,
                },
            );
            // Include known-zero precincts that are omitted from both complete rosters.
            let numbers: [u64; 4] = if draw() % 5 == 0 {
                [0, 0, 0, 0]
            } else {
                [draw() % 100, draw() % 150, draw() % 100, draw() % 150]
            };
            for (map, n) in values.iter_mut().zip(numbers) {
                if n != 0 {
                    map.insert(id.clone(), n);
                }
            }
            old_totals.insert(id.clone(), numbers[1]);
            new_totals.insert(id, numbers[3]);
            if let (Some(old), Some(new)) = (
                numbers[1].checked_sub(numbers[0]),
                numbers[3].checked_sub(numbers[2]),
            ) {
                expected.0 += old;
                expected.1 += new;
                expected.2 += 1;
            }
        }
        for (i, values) in values.iter().enumerate() {
            let mut value = source(if i < 2 { 2024 } else { 2026 }, (i % 2 + 1) as u32, &[]);
            value.counts = values.clone();
            sources.push(value);
        }
        let view = trends::analyze(
            &snapshot(&reference, sources.clone()),
            &trends::History::default(),
            None,
            "all",
            "matched",
            "partisan",
        )
        .unwrap();
        let day = &view.totals.days[1];
        assert_eq!(day.daily_groups, expected.2);
        assert_eq!(day.daily_2024, (expected.2 > 0).then_some(expected.0));
        assert_eq!(day.daily_2026, (expected.2 > 0).then_some(expected.1));
        let period = matching::period(&reference, &sources, 2, false);
        assert_eq!(period.is_some(), expected.2 > 0);
        if let Some(period) = period {
            assert_eq!(
                (period.county_2024, period.county_2026),
                (expected.0, expected.1)
            );
        }
        assert_eq!(
            (
                day.cumulative_2024,
                day.cumulative_2026,
                day.cumulative_groups
            ),
            (
                Some(old_totals.values().sum()),
                Some(new_totals.values().sum()),
                8
            )
        );
    }
}

#[test]
fn seeded_partial_daily_rosters_match_each_date_and_crosswalk_independently() {
    let mut state = 0xa11ce_u64;
    let mut draw = || {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        state >> 32
    };
    for _ in 0..300 {
        let mut reference = reference();
        reference.groups.clear();
        reference.presidential.clear();
        reference.exact_pairs.clear();
        for group in 0..4 {
            let old: Vec<_> = (0..2).map(|p| format!("o{group}-{p}")).collect();
            let new: Vec<_> = (0..3).map(|p| format!("n{group}-{p}")).collect();
            for id in &old {
                reference.presidential.insert(
                    id.clone(),
                    Party {
                        harris: 60,
                        trump: 40,
                    },
                );
            }
            reference.groups.push(Group { old, new });
        }
        let mut sources = Vec::new();
        let mut truth: Vec<Vec<(Counts, Counts)>> = Vec::new();
        for year in [2024, 2026] {
            let ids: Vec<_> = reference
                .groups
                .iter()
                .flat_map(|g| if year == 2024 { &g.old } else { &g.new })
                .cloned()
                .collect();
            let mut yearly = Vec::new();
            let mut running = Counts::new();
            for day in 1..=5 {
                let mut value = source(year, day, &[]);
                value.cumulative = false;
                value.complete = draw() % 3 == 0;
                let mut known = Counts::new();
                for id in &ids {
                    if draw() % 3 != 0 {
                        let n = draw() % 40;
                        value.counts.insert(id.clone(), n);
                        known.insert(id.clone(), n);
                    } else if value.complete {
                        known.insert(id.clone(), 0);
                    }
                }
                if day == 1 {
                    running = known.clone();
                } else {
                    running.retain(|id, total| {
                        if let Some(n) = known.get(id) {
                            *total += n;
                            true
                        } else {
                            false
                        }
                    });
                }
                yearly.push((known, running.clone()));
                sources.push(value);
            }
            truth.push(yearly);
        }
        let mut snapshot = snapshot(&reference, sources.clone());
        snapshot.days = 5;
        let view = trends::analyze(
            &snapshot,
            &trends::History::default(),
            None,
            "all",
            "matched",
            "partisan",
        )
        .unwrap();
        for (day, row) in view.totals.days.iter().take(5).enumerate() {
            for cumulative in [false, true] {
                let old = if cumulative {
                    &truth[0][day].1
                } else {
                    &truth[0][day].0
                };
                let new = if cumulative {
                    &truth[1][day].1
                } else {
                    &truth[1][day].0
                };
                let mut expected = (0u64, 0u64, 0usize);
                for group in &reference.groups {
                    if group.old.iter().all(|id| old.contains_key(id))
                        && group.new.iter().all(|id| new.contains_key(id))
                    {
                        expected.0 += group.old.iter().map(|id| old[id]).sum::<u64>();
                        expected.1 += group.new.iter().map(|id| new[id]).sum::<u64>();
                        expected.2 += 1;
                    }
                }
                let actual = if cumulative {
                    (
                        row.cumulative_2024,
                        row.cumulative_2026,
                        row.cumulative_groups,
                    )
                } else {
                    (row.daily_2024, row.daily_2026, row.daily_groups)
                };
                assert_eq!(
                    actual,
                    (
                        (expected.2 > 0).then_some(expected.0),
                        (expected.2 > 0).then_some(expected.1),
                        expected.2
                    )
                );
                let period = matching::period(&reference, &sources, (day + 1) as u32, cumulative);
                assert_eq!(period.is_some(), expected.2 > 0);
                if let Some(period) = period {
                    assert_eq!(
                        (period.county_2024, period.county_2026),
                        (expected.0, expected.1)
                    );
                }
            }
        }
        assert!(
            view.totals
                .days
                .iter()
                .skip(5)
                .all(|d| d.daily_2026.is_none() && d.cumulative_2026.is_none())
        );
    }
}

#[test]
fn historical_precinct_gap_only_excludes_its_affected_cumulative_measure() {
    let mut sources = Vec::new();
    for (year, rows) in [
        (
            2024,
            vec![
                vec![("a", 10), ("b", 20)],
                vec![("a", 5)],
                vec![("a", 3), ("b", 7)],
            ],
        ),
        (
            2026,
            vec![
                vec![("a", 20), ("b", 40)],
                vec![("a", 10), ("b", 4)],
                vec![("a", 6), ("b", 14)],
            ],
        ),
    ] {
        for (day, values) in rows.iter().enumerate() {
            let mut value = source(year, (day + 1) as u32, values);
            value.cumulative = false;
            value.complete = !(year == 2024 && day == 1);
            sources.push(value);
        }
    }
    let mut snapshot = snapshot(&reference(), sources.clone());
    snapshot.days = 3;
    let view = trends::analyze(
        &snapshot,
        &trends::History::default(),
        None,
        "all",
        "matched",
        "partisan",
    )
    .unwrap();
    let missing = &view.totals.days[1];
    assert_eq!(
        (missing.daily_2024, missing.daily_2026, missing.daily_groups),
        (Some(5), Some(10), 1)
    );
    assert_eq!(
        (
            missing.cumulative_2024,
            missing.cumulative_2026,
            missing.cumulative_groups
        ),
        (Some(15), Some(30), 1)
    );
    // A later explicit daily observation restores b's daily comparison; it cannot
    // retroactively establish the missing historical cumulative contribution.
    let next = &view.totals.days[2];
    assert_eq!(
        (next.daily_2024, next.daily_2026, next.daily_groups),
        (Some(10), Some(20), 2)
    );
    assert_eq!(
        (
            next.cumulative_2024,
            next.cumulative_2026,
            next.cumulative_groups
        ),
        (Some(18), Some(36), 1)
    );
    let period = matching::period(&reference(), &sources, 3, true).unwrap();
    assert_eq!(
        (
            period.county_2024,
            period.county_2026,
            period.coverage.available_groups
        ),
        (18, 36, 1)
    );
    assert!(!period.groups[1].available);
}
