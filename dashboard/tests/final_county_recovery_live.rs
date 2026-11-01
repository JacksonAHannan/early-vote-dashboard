//! Actual atomic mixed-source series; no voter records are persisted.
use std::{path::Path, time::Duration};
use texas_turnout::{Reference, county, days_through, latest_completed};

#[tokio::test]
#[ignore = "downloads official Dimmit fixed-width and dated SOS sources into memory"]
async fn dimmit_preserves_sos_dates_and_adds_proved_native_final_date() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = refs.iter().find(|r| r.id == "dimmit").unwrap();
    assert!(county::has_adapter("dimmit", 2026));
    assert!(!county::has_adapter("dimmit", 2024));
    let through = latest_completed();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, days_through(through).unwrap())
        .await
        .unwrap();
    assert_eq!(reports.len(), 12);
    assert!(
        reports
            .iter()
            .all(|s| !s.complete && !s.cumulative && s.sha256.len() == 64)
    );
    let final_day = reports.iter().find(|s| s.date == through).unwrap();
    assert!(final_day.source.starts_with("https://dimmitcounty.org/"));
    assert!(final_day.note.contains("EV/EV"));
    assert!(final_day.counts.values().sum::<u64>() >= 200);
    assert!(reports.iter().filter(|s| s.date < through).all(|s| {
        s.source
            .starts_with("https://goelect.txelections.civixapps.com/")
    }));
    if let Ok(path) = std::env::var("TURNOUT_DIMMIT_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}
