//! Explicit, dated precinct zero evidence never certifies the rest of a county.
use serde_json::{Value, json};
use std::path::PathBuf;
use texas_turnout::{Daily, Reference, matching, quality};
struct Fixture(PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn daily(day: u32, values: Value) -> Daily {
    serde_json::from_value(json!({"county":"travis","date":format!("2026-10-{:02}",18+day),"counts":values,"source":"https://county.example/dated-roster","sha256":"a".repeat(64),"retrieved_at":"2026-10-27T00:00:00Z","note":"Ordinary in-person roster","complete":false,"cumulative":false})).unwrap()
}
fn proof() -> Value {
    json!({"county":"travis","year":2026,"through":"2026-10-20","precincts":["3"],"scope":"in_person_cumulative","source":"https://county.example/precinct-table","sha256":"b".repeat(64),"retrieved_at":"2026-10-27T00:00:00Z","note":"Explicit zero in completed cumulative ordinary in-person table; matching daily county control."})
}
fn reference() -> Reference {
    serde_json::from_value(json!({"id":"travis","name":"Travis","state_id":227,"groups":[{"old":["1"],"new":["1"]},{"old":["2","3"],"new":["2","3"]},{"old":["4"],"new":["4"]}],"exact_pairs":[],"presidential":{},"references":{}})).unwrap()
}
fn fixture(proofs: Vec<Value>) -> Fixture {
    let dir = std::env::temp_dir().join(format!(
        "turnout-precinct-zero-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(dir.join("data")).unwrap();
    std::fs::create_dir_all(dir.join("recovery")).unwrap();
    std::fs::write(
        dir.join("data/completeness.json"),
        json!({"schema_version":1,"generated_at":"fixture","controls":[]}).to_string(),
    )
    .unwrap();
    std::fs::write(
        dir.join("data/reference.json"),
        serde_json::to_vec(&vec![reference()]).unwrap(),
    )
    .unwrap();
    std::fs::write(dir.join("recovery/texas-20261027.json"),json!({"schema_version":1,"method":"Reviewed explicit zero fixtures","observations":[],"zero_proofs":proofs}).to_string()).unwrap();
    Fixture(dir)
}
#[test]
fn explicit_zero_recovers_only_the_proven_precinct_and_its_common_group() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let raw = daily(1, json!({"1":5,"2":3}));
    let source = report.sources("travis", std::slice::from_ref(&raw));
    assert_eq!(source[0].counts.get("3"), Some(&0));
    assert!(!source[0].counts.contains_key("4"));
    assert!(!source[0].complete);
    assert_eq!(raw.counts.len(), 2);
    let mut old = daily(1, json!({"1":10,"2":4,"3":0,"4":1}));
    old.date = texas_turnout::start(2024);
    let p = matching::period(&reference(), &[old, source[0].clone()], 1, true).unwrap();
    assert_eq!(p.coverage.available_precincts, 3);
    assert_eq!((p.county_2024, p.county_2026), (14, 8));
}
#[test]
fn dated_evidence_does_not_fill_future_days_or_fabricate_missing_rosters() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let source = report.sources(
        "travis",
        &[daily(1, json!({"1":1})), daily(3, json!({"1":2}))],
    );
    assert_eq!(source.len(), 2);
    assert_eq!(source[0].counts.get("3"), Some(&0));
    assert!(!source[1].counts.contains_key("3"));
}
#[test]
fn any_positive_or_quarantined_cell_within_the_proof_window_blocks_that_precinct() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    for quarantine in [false, true] {
        let first = daily(1, json!({"1":1}));
        let mut second = daily(
            2,
            if quarantine {
                json!({"1":2})
            } else {
                json!({"1":2,"3":1})
            },
        );
        if quarantine {
            second.unavailable_precincts = vec!["003".into()];
        }
        let values = report.sources("travis", &[first, second]);
        assert!(!values[0].counts.contains_key("3"));
        assert_eq!(
            values[1].counts.get("3"),
            if quarantine { None } else { Some(&1) }
        );
    }
}
#[test]
fn positive_after_the_cumulative_cutoff_does_not_invalidate_earlier_zero() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let values = report.sources(
        "travis",
        &[daily(1, json!({"1":1})), daily(3, json!({"3":2}))],
    );
    assert_eq!(values[0].counts.get("3"), Some(&0));
    assert_eq!(values[1].counts.get("3"), Some(&2));
}
#[test]
fn repeated_qualification_is_idempotent_and_new_conflicts_remove_derived_zeros() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let values = report.sources("travis", &[daily(1, json!({"1":1}))]);
    assert_eq!(
        serde_json::to_value(&values).unwrap(),
        serde_json::to_value(report.sources("travis", &values)).unwrap()
    );
    let mut changed = values;
    changed.push(daily(2, json!({"3":1})));
    let revised = report.sources("travis", &changed);
    assert!(!revised[0].counts.contains_key("3"));
}
#[test]
fn zero_proof_metadata_is_published_separately_from_original_source_hash() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let values = report.sources("travis", &[daily(1, json!({"1":1}))]);
    let value = serde_json::to_value(&values[0]).unwrap();
    assert_eq!(value["sha256"], "a".repeat(64));
    assert_eq!(value["zero_evidence"][0]["sha256"], "b".repeat(64));
    assert_eq!(value["zero_evidence"][0]["precincts"], json!(["3"]));
}
#[test]
fn unsupported_scope_non_native_ids_bad_hash_and_invalid_windows_fail_closed() {
    for (key, value) in [
        ("scope", json!("mail")),
        ("precincts", json!(["999"])),
        ("sha256", json!("not-a-hash")),
        ("through", json!("2026-10-18")),
        ("precincts", json!(["3", "003"])),
    ] {
        let mut p = proof();
        p[key] = value;
        let f = fixture(vec![p]);
        assert!(
            quality::Report::load(&f.0).is_err(),
            "invalid {key} accepted"
        );
    }
}

#[test]
fn removing_the_reviewed_edition_removes_its_derived_zeros() {
    let f = fixture(vec![proof()]);
    let report = quality::Report::load(&f.0).unwrap();
    let values = report.sources("travis", &[daily(1, json!({"1":1}))]);
    std::fs::remove_file(f.0.join("recovery/texas-20261027.json")).unwrap();
    let without = quality::Report::load(&f.0)
        .unwrap()
        .sources("travis", &values);
    assert!(!without[0].counts.contains_key("3"));
    assert!(without[0].zero_evidence.is_empty());
}

#[test]
fn a_cumulative_only_anchor_never_creates_same_day_votes_from_another_source() {
    let first = daily(1, json!({"1":5}));
    let mut anchor = daily(2, json!({"1":20}));
    anchor.cumulative = true;
    anchor.allow_daily_difference = Some(false);
    let mut values = vec![first, anchor];
    assert_eq!(matching::counts(&values, 2026, 2, true).unwrap()["1"], 20);
    assert!(matching::counts(&values, 2026, 2, false).is_none());
    assert!(!matching::full(&values, 2026, 2, false));
    values.push(daily(2, json!({"1":3})));
    assert_eq!(matching::counts(&values, 2026, 2, false).unwrap()["1"], 3);
}
