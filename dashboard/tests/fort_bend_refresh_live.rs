//! Opt-in native publication-discovery check. No raw voter data is written.
use std::{path::Path, time::Duration};
use texas_turnout::{Reference, days_through, fort_bend, latest_completed};

#[tokio::test]
#[ignore = "reads the current official Fort Bend landing, workbook, and independent control into memory"]
async fn current_native_publication_is_discovered_and_checked_by_date() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.iter().find(|r| r.id == "fortbend").unwrap();
    let through = latest_completed();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = fort_bend::collect(&client, reference, 2026, days_through(through).unwrap())
        .await
        .expect("current advertised native publication should remain usable");
    assert!(!reports.is_empty());
    for report in &reports {
        assert!(report.date <= through);
        assert!(!report.cumulative && !report.complete);
        assert!(report.counts.values().sum::<u64>() > 0);
        assert!(
            report
                .source
                .starts_with("https://www.fortbendcountytx.gov/")
        );
        assert!(
            report
                .note
                .contains("county-wide completion is not established")
        );
        eprintln!(
            "{}: {} reported native precincts, {} votes; source {} SHA256 {}",
            report.date,
            report.counts.len(),
            report.counts.values().sum::<u64>(),
            report.source,
            report.sha256
        );
    }
    if let Ok(path) = std::env::var("TURNOUT_FORT_BEND_REFRESH_OUTPUT") {
        let path = std::path::PathBuf::from(path);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}
