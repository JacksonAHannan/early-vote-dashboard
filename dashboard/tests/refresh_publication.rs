//! Collector failures must remain visible after independent comparison qualification.
use serde_json::json;
use texas_turnout::{Reference, Snapshot, quality};
fn fixture(days: u32, error: Option<&str>) -> (Snapshot, Vec<Reference>) {
    let reference:Reference=serde_json::from_value(json!({"id":"example","name":"Example","state_id":1,"groups":[{"old":["1"],"new":["1"]}],"exact_pairs":[["1","1"]],"presidential":{"1":{"harris":2,"trump":3}},"references":{}})).unwrap();
    let sources=[2024,2026].map(|year|json!({"county":"example","date":texas_turnout::start(year),"counts":{"1":10},"source":"https://official.example/dated","sha256":"a".repeat(64),"retrieved_at":"2026-10-28T00:00:00Z","note":"fixture","cumulative":false,"complete":false}));
    let snapshot:Snapshot=serde_json::from_value(json!({"schema_version":1,"generated_at":"fixture","through":texas_turnout::start(2026)+chrono::Duration::days(i64::from(days-1)),"days":days,"geography":"fixture","counties":[{"id":"example","name":"Example","status":"current","checked_at":"2026-10-28T00:00:00Z","error":error,"periods":[],"sources":sources}]})).unwrap();
    (snapshot, vec![reference])
}
#[test]
fn actual_scrape_failure_survives_qualification_with_retained_comparison() {
    let (raw, refs) = fixture(
        1,
        Some("2026-10-19 official download HTTP 502; retained exact-date source"),
    );
    let q = quality::Report::default().snapshot(&raw, &refs).unwrap();
    assert!(q.counties[0].error.as_deref().unwrap_or("").contains("502"));
    assert_eq!(q.counties[0].status, "stale");
    assert_eq!(q.counties[0].periods[0].county_2026, 10);
}
#[test]
fn missing_latest_comparison_does_not_erase_collection_diagnosis() {
    let (raw, refs) = fixture(
        2,
        Some("2026-10-20: no in-person records in official state response"),
    );
    let q = quality::Report::default().snapshot(&raw, &refs).unwrap();
    assert!(
        q.counties[0]
            .error
            .as_deref()
            .unwrap_or("")
            .contains("no in-person records")
    );
    assert_eq!(q.counties[0].periods.len(), 1);
}
#[test]
fn successful_next_attempt_clears_old_scrape_failure() {
    let (mut raw, refs) = fixture(1, None);
    raw.counties[0].status = "stale".into();
    let q = quality::Report::default().snapshot(&raw, &refs).unwrap();
    assert_eq!(q.counties[0].status, "current");
    assert!(q.counties[0].error.is_none());
}
