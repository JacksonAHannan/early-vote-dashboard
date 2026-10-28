//! Opt-in production transport/parser check. Downloads remain memory-only.
use std::{collections::BTreeSet, path::Path, time::Duration};
use texas_turnout::{Reference, fetch, latest_completed};

#[tokio::test]
#[ignore = "reads completed-day official SOS exports into anonymous memory"]
async fn completed_day_sos_transport_distinguishes_available_from_unposted() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let date = latest_completed();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(45))
        .build()
        .unwrap();
    let mut available = 0;
    for id in ["fortbend", "harris", "bell", "bexar"] {
        let reference = references.iter().find(|r| r.id == id).unwrap();
        let mut seen = BTreeSet::new();
        match fetch::fetch_state(&client, reference, date, &mut seen).await {
            Ok(report) => {
                assert_eq!(report.date, date);
                assert_eq!(report.county, id);
                assert!(!report.cumulative && !report.complete);
                assert!(report.counts.values().sum::<u64>() > 0);
                assert_eq!(report.sha256.len(), 64);
                available += 1;
            }
            Err(error) => {
                // Empty and mail-only responses never become zero turnout. A
                // transient download failure must also not modify identity state.
                assert!(seen.is_empty());
                assert!(!error.to_string().is_empty());
            }
        }
    }
    assert!(
        available > 0,
        "no sampled latest-completed-day state source was available"
    );
}
