//! Correct known source selection gaps without weakening absence-as-unknown rules.
use serde_json::json;
use std::sync::atomic::{AtomicU64, Ordering};
use std::{collections::BTreeMap, path::PathBuf};
use texas_turnout::{Counts, Daily, Group, Reference, matching, quality};
const BAD: &str = "b070ed9b8064425482f7fc9cee62ac801d2c3fd913a4376ae60fb4b8eaac7d49";
struct Fixture(PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn source(county: &str, year: i32, values: &[(&str, u64)]) -> Daily {
    Daily {
        allow_daily_difference: None,
        zero_evidence: Vec::new(),
        unavailable_precincts: Vec::new(),
        county: county.into(),
        date: texas_turnout::start(year),
        counts: values.iter().map(|(p, n)| ((*p).into(), *n)).collect(),
        source: "https://official.example/dated-in-person".into(),
        sha256: "a".repeat(64),
        retrieved_at: "2026-10-25T00:00:00Z".into(),
        note: "In-person anonymous source fixture".into(),
        cumulative: false,
        complete: false,
    }
}
fn fixture(recovered: &Daily, supersedes: Vec<&str>, expected: u64) -> Fixture {
    static FIXTURE_ID: AtomicU64 = AtomicU64::new(0);
    let root = std::env::temp_dir().join(format!(
        "turnout-source-recovery-{}-{}-{}",
        std::process::id(),
        FIXTURE_ID.fetch_add(1, Ordering::Relaxed),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(root.join("data")).unwrap();
    std::fs::create_dir_all(root.join("recovery")).unwrap();
    std::fs::write(root.join("data/completeness.json"),json!({"schema_version":1,"generated_at":"fixture","controls":[{"county":recovered.county,"year":recovered.date.format("%Y").to_string().parse::<i32>().unwrap(),"date":recovered.date,"daily":expected,"cumulative":expected,"source":"independent control","sha256":"b".repeat(64),"retrieved_at":"fixture","scope":"in_person","completed":true,"note":"fixture"}]}).to_string()).unwrap();
    std::fs::write(root.join("recovery/texas-20261025.json"),json!({"schema_version":1,"method":"Fixture audited source recovery","observations":[{"source":recovered,"supersedes_sha256":supersedes}]}).to_string()).unwrap();
    Fixture(root)
}
fn reference(county: &str) -> Reference {
    Reference {
        id: county.into(),
        name: county.into(),
        state_id: 101,
        groups: ["1", "889", "empty"]
            .map(|p| Group {
                old: vec![p.into()],
                new: vec![p.into()],
            })
            .into(),
        exact_pairs: vec![],
        presidential: BTreeMap::new(),
        references: json!({}),
    }
}
#[test]
fn known_conflicting_archive_is_replaced_by_the_whole_reconciled_report() {
    let recovered = source("harris", 2024, &[("1", 8), ("889", 2)]);
    let f = fixture(&recovered, vec![BAD], 10);
    let report = quality::Report::load(&f.0).unwrap();
    let mut native = source("harris", 2024, &[("1", 8)]);
    native.sha256 = BAD.into();
    let before = native.clone();
    let qualified = report.sources("harris", std::slice::from_ref(&native));
    assert_eq!(
        qualified[0].counts.get("889"),
        Some(&2),
        "A published positive precinct must be recovered, not omitted or set to zero"
    );
    assert!(qualified[0].complete);
    assert_eq!(native.counts, before.counts);
    assert_eq!(qualified[0].sha256, recovered.sha256);
    let current = source("harris", 2026, &[("1", 10), ("889", 3), ("empty", 1)]);
    let p = matching::period(
        &reference("harris"),
        &[qualified[0].clone(), current],
        1,
        true,
    )
    .unwrap();
    assert_eq!(p.coverage.available_precincts, 3);
    assert_eq!((p.county_2024, p.county_2026), (10, 14));
}
#[test]
fn later_unrecognized_revisions_are_preserved_without_unsupported_zero_inference() {
    let recovered = source("harris", 2024, &[("1", 8), ("889", 2)]);
    let f = fixture(&recovered, vec![BAD], 10);
    let report = quality::Report::load(&f.0).unwrap();
    let revised = source("harris", 2024, &[("1", 8), ("889", 3)]);
    let qualified = report.sources("harris", std::slice::from_ref(&revised));
    assert_eq!(qualified[0].counts, revised.counts);
    assert!(!qualified[0].complete);
}
#[test]
fn fills_missing_daily_sources_beside_separate_native_cumulative_anchors() {
    let recovered = source("ellis", 2026, &[("1", 8), ("889", 2)]);
    let f = fixture(&recovered, vec![], 11);
    let report = quality::Report::load(&f.0).unwrap();
    let mut native = source("ellis", 2026, &[("1", 20), ("889", 5)]);
    native.date += chrono::Duration::days(3);
    native.cumulative = true;
    let qualified = report.sources("ellis", std::slice::from_ref(&native));
    assert_eq!(qualified.len(), 2);
    let first = qualified.iter().find(|d| d.date == recovered.date).unwrap();
    assert_eq!(first.counts, recovered.counts);
    assert!(
        !first.complete,
        "One missing vote cannot certify absent precinct zeros"
    );
    assert_eq!(
        qualified.iter().find(|d| d.cumulative).unwrap().counts,
        native.counts
    );
    let revised = source("ellis", 2026, &[("1", 9), ("889", 2)]);
    let later = report.sources("ellis", &[native, revised.clone()]);
    assert_eq!(later.len(), 2);
    assert_eq!(
        later.iter().find(|d| !d.cumulative).unwrap().counts,
        revised.counts
    );
}
#[test]
fn recovery_never_creates_an_observation_for_an_unrelated_county() {
    let recovered = source("ellis", 2026, &[("1", 8)]);
    let f = fixture(&recovered, vec![], 8);
    let report = quality::Report::load(&f.0).unwrap();
    assert!(report.sources("other", &[]).is_empty());
    let known = source("other", 2024, &[("1", 7)]);
    assert_eq!(
        report.sources("other", &[known])[0].counts,
        Counts::from([("1".into(), 7)])
    );
}

#[test]
fn recovery_edition_is_anonymous_dated_and_reconciles_reviewed_controls() {
    let value: quality::Recovery =
        serde_json::from_str(include_str!("../recovery/texas-20261025.json")).unwrap();
    assert_eq!(value.schema_version, 1);
    assert_eq!(value.observations.len(), 20);
    let mut keys = std::collections::BTreeSet::new();
    for observation in &value.observations {
        let d = &observation.source;
        assert!(keys.insert((&d.county, d.date, d.cumulative)));
        assert!(!d.cumulative);
        assert!(d.source.starts_with("https://"));
        assert_eq!(d.sha256.len(), 64);
        assert!(d.sha256.bytes().all(|c| c.is_ascii_hexdigit()));
        assert!(!d.retrieved_at.is_empty());
        assert!(
            d.counts
                .keys()
                .all(|p| p == "UNASSIGNED" || p.bytes().all(|c| c.is_ascii_digit()))
        );
        assert!(
            !d.complete,
            "Only current independent controls may establish completion"
        );
    }
    let harris: Vec<_> = value
        .observations
        .iter()
        .filter(|r| r.source.county == "harris")
        .collect();
    assert_eq!(harris.len(), 12);
    // Independently retained completed county in-person controls, in date order.
    let controls = [
        126473, 115836, 111153, 104172, 112980, 72787, 43535, 96917, 92310, 85105, 86702, 128456,
    ];
    for (item, expected) in harris.iter().zip(controls) {
        assert_eq!(item.supersedes_sha256, [BAD]);
        assert_eq!(item.source.counts.values().sum::<u64>(), expected);
        assert_eq!(
            item.source.counts.get("UNASSIGNED").copied().unwrap_or(0),
            0
        );
    }
    for (county, expected) in [("houston", 586), ("leon", 717)] {
        let item = value
            .observations
            .iter()
            .find(|r| r.source.county == county)
            .unwrap();
        assert!(item.supersedes_sha256.is_empty());
        assert_eq!(item.source.counts.values().sum::<u64>(), expected);
    }
}

#[tokio::test]
#[ignore = "downloads official sources into memory; run explicitly for source recovery verification"]
async fn real_collectors_recover_reviewed_dated_sources_without_saving_voter_records() {
    use std::{collections::BTreeSet, time::Duration};
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 TexasTurnout source audit")
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(120))
        .build()
        .unwrap();
    for county in ["houston", "leon"] {
        let r = references.iter().find(|r| r.id == county).unwrap();
        let mut identities = BTreeSet::new();
        for n in 0..5 {
            let day = texas_turnout::start(2024) + chrono::Duration::days(n);
            let d = texas_turnout::fetch::fetch_state(&client, r, day, &mut identities)
                .await
                .unwrap();
            assert!(!d.counts.is_empty());
            assert_eq!(d.date, day);
        }
        println!("{county}: five validated dated historical reports, no cross-date repeats");
    }
    let r = references.iter().find(|r| r.id == "ellis").unwrap();
    let values = texas_turnout::county::collect(&client, r, 2026, 6)
        .await
        .unwrap();
    for n in 0..6 {
        assert!(values.iter().any(|d| d.date
            == texas_turnout::start(2026) + chrono::Duration::days(n)
            && !d.cumulative));
    }
    println!(
        "Ellis: six dated state reports plus {} native cumulative observations",
        values.iter().filter(|d| d.cumulative).count()
    );
}
