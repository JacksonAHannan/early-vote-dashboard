//! Actual replacement-PDF verification; no raw voter identities are persisted.
use std::path::Path;
use texas_turnout::{Reference, county, start};

#[tokio::test]
#[ignore = "downloads the current official Nueces in-person PDF"]
async fn current_pdf_retains_valid_dates_and_quarantines_short_identity_cell() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references
        .iter()
        .find(|reference| reference.id == "nueces")
        .unwrap();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, 9).await.unwrap();
    assert_eq!(reports.len(), 9);
    let latest = reports
        .iter()
        .find(|day| day.date == start(2026) + chrono::Duration::days(8))
        .unwrap();
    assert!(latest.counts.values().sum::<u64>() >= 5_000);
    assert!(
        latest
            .source
            .starts_with("https://www.nuecesco.com/home/showpublisheddocument/")
    );
    let affected = reports
        .iter()
        .find(|day| day.date == start(2026) + chrono::Duration::days(7))
        .unwrap();
    assert_eq!(affected.unavailable_precincts, vec!["17"]);
    assert!(!affected.counts.contains_key("17"));
    assert!(
        reports
            .iter()
            .all(|day| !day.complete && !day.cumulative && day.sha256.len() == 64)
    );
    if let Ok(path) = std::env::var("TURNOUT_NUECES_REFRESH_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}
