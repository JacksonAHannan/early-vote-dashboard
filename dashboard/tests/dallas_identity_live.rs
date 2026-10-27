//! Opt-in acceptance of real Dallas blank-precinct recovery; no voter rows saved.
use std::{path::PathBuf, time::Duration};
use texas_turnout::{Daily, Reference, county};

#[tokio::test]
#[ignore = "downloads official current Dallas workbook/SOS reports in memory; writes aggregate Daily JSON only"]
async fn dallas_exact_identity_live_source_preserves_native_daily_totals() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.into_iter().find(|r| r.id == "dallas").unwrap();
    let client = reqwest::Client::builder()
        .cookie_store(true)
        .user_agent("Mozilla/5.0 TexasTurnout source audit")
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(180))
        .build()
        .unwrap();
    let days: Vec<Daily> = county::collect(&client, &reference, 2026, 8).await.unwrap();
    assert_eq!(days.len(), 8);
    assert_eq!(
        days.iter()
            .map(|d| d.counts.values().sum::<u64>())
            .collect::<Vec<_>>(),
        vec![77854, 65084, 56092, 49469, 54345, 36613, 19183, 44140]
    );
    for day in days.iter().take(7) {
        assert!(!day.counts.contains_key("UNASSIGNED"), "{}", day.date);
        assert!(day.note.contains("Exact-identity precinct recovery"));
        assert!(day.note.contains("same-date identity source"));
        assert!(
            !day.complete,
            "independent qualifier alone decides completeness"
        );
    }
    assert_eq!(days[4].unavailable_precincts, vec!["2130"]);
    assert_eq!(days[5].unavailable_precincts, vec!["4640"]);
    assert_eq!(days[7].unavailable_precincts, vec!["1040"]);
    assert_eq!(days[7].counts.get("UNASSIGNED"), Some(&6));
    let output = PathBuf::from(
        std::env::var("TURNOUT_DALLAS_IDENTITY_OUTPUT")
            .expect("set isolated anonymous aggregate output path"),
    );
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    std::fs::write(output, serde_json::to_vec_pretty(&days).unwrap()).unwrap();
}
