//! Opt-in current Dallas production collector; never persists voter records.
use std::{path::Path, time::Duration};
use texas_turnout::{Reference, county, start};

#[tokio::test]
#[ignore = "downloads current native Dallas CSV and optional same-date identity sources"]
async fn dallas_current_native_csv_retains_eleven_completed_dates() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.iter().find(|r| r.id == "dallas").unwrap();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(90))
        .build()
        .unwrap();
    let days = county::collect(&client, reference, 2026, 11).await.unwrap();
    assert_eq!(days.len(), 11);
    let through = start(2026) + chrono::Duration::days(10);
    let latest = days.iter().find(|d| d.date == through).unwrap();
    assert!(
        latest
            .source
            .starts_with("https://www.dallascountyvotes.org/wp-content/uploads/2026/")
    );
    assert!(latest.source.ends_with(".csv"));
    assert!(latest.counts.values().sum::<u64>() > 30_000);
    assert!(latest.counts.len() > 600);
    assert!(
        days.iter()
            .all(|d| d.date <= through && !d.cumulative && !d.complete && d.sha256.len() == 64)
    );
    if let Ok(path) = std::env::var("TURNOUT_DALLAS_CSV_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&days).unwrap()).unwrap();
    }
}
