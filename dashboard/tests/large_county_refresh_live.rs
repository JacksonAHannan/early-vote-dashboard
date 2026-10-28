//! Opt-in production refresh adapter verification; raw voter rows remain in memory.
use std::path::Path;
use texas_turnout::{Reference, county, start};

#[tokio::test]
#[ignore = "downloads current official Cameron workbook and dated SOS reports"]
async fn cameron_current_landing_discovers_latest_completed_native_day() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.iter().find(|r| r.id == "cameron").unwrap();
    assert!(county::has_adapter("cameron", 2026));
    assert!(!county::has_adapter("cameron", 2024));
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, 9).await.unwrap();
    let through = start(2026) + chrono::Duration::days(8);
    let latest = reports.iter().find(|d| d.date == through).unwrap();
    assert!(
        latest
            .source
            .starts_with("https://www.cameroncountytx.gov/elections/wp-content/uploads/2026/")
    );
    assert!(latest.counts.values().sum::<u64>() >= 5_000);
    assert_eq!(latest.counts.len(), 102);
    assert_eq!(reports.len(), 9);
    assert!(
        reports
            .iter()
            .all(|d| !d.complete && !d.cumulative && d.sha256.len() == 64)
    );
    if let Ok(path) = std::env::var("TURNOUT_CAMERON_REFRESH_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}

#[tokio::test]
#[ignore = "downloads current official Denton workbook and dated SOS reports"]
async fn denton_current_landing_replaces_latest_foreign_label_only_state_export() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.iter().find(|r| r.id == "denton").unwrap();
    assert!(county::has_adapter("denton", 2026));
    assert!(!county::has_adapter("denton", 2024));
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, 9).await.unwrap();
    let through = start(2026) + chrono::Duration::days(8);
    let latest = reports.iter().find(|d| d.date == through).unwrap();
    assert!(
        latest
            .source
            .starts_with("https://www.votedenton.gov/wp-content/uploads/2026/")
    );
    assert!(latest.counts.values().sum::<u64>() >= 15_000);
    let native: std::collections::BTreeSet<_> =
        reference.groups.iter().flat_map(|g| &g.new).collect();
    assert!(latest.counts.keys().filter(|p| native.contains(p)).count() >= 180);
    assert!(!latest.counts.contains_key("17"));
    assert_eq!(reports.len(), 9);
    assert!(
        reports
            .iter()
            .all(|d| !d.complete && !d.cumulative && d.sha256.len() == 64)
    );
    if let Ok(path) = std::env::var("TURNOUT_DENTON_REFRESH_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}
