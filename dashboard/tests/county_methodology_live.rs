//! Opt-in official downloads; only anonymous aggregates may be retained.
use std::path::Path;
use texas_turnout::{Reference, county, start};

#[tokio::test]
#[ignore = "downloads the reviewed official Collin workbook into memory"]
async fn collin_ordinary_dated_native_reports_restore_the_sparse_state_export() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = refs.iter().find(|r| r.id == "collin").unwrap();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, 8).await.unwrap();
    let through = start(2026) + chrono::Duration::days(7);
    assert_eq!(reports.len(), 8);
    let latest = reports.iter().find(|d| d.date == through).unwrap();
    assert!(latest.counts.values().sum::<u64>() > 20_000);
    assert!(latest.note.contains("Provisional rows excluded"));
    assert!(latest.note.contains("133 provisional rows excluded"));
    assert!(
        reports
            .iter()
            .filter(|d| d.date < through)
            .all(|d| d.source.contains("goelect.txelections.civixapps.com"))
    );
    assert!(latest.unavailable_precincts.contains(&"52".to_string()));
    assert!(!latest.counts.contains_key("52"));
    assert!(reports.iter().all(|d| d.county == "collin"
        && d.date <= through
        && !d.complete
        && !d.cumulative
        && d.sha256.len() == 64));
    if let Ok(output) = std::env::var("TURNOUT_COLLIN_NATIVE_OUTPUT") {
        let output = std::path::PathBuf::from(output);
        std::fs::create_dir_all(output.parent().unwrap()).unwrap();
        std::fs::write(output, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}

#[tokio::test]
#[ignore = "downloads Panola and dated official state reports into memory"]
async fn panola_native_dates_fill_only_missing_state_reports() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = refs.iter().find(|r| r.id == "panola").unwrap();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(90))
        .build()
        .unwrap();
    let reports = county::collect(&client, reference, 2026, 8).await.unwrap();
    assert_eq!(reports.len(), 8);
    for day in 1..=8 {
        let date = start(2026) + chrono::Duration::days(day - 1);
        let source = reports.iter().find(|s| s.date == date).unwrap();
        assert!(!source.complete && !source.cumulative);
        if [2, 3].contains(&day) {
            assert!(
                source
                    .source
                    .starts_with("https://www.co.panola.tx.us/DocumentCenter/View/")
            );
            assert!(source.counts.get("14").is_some_and(|n| *n > 0));
            assert!(source.note.contains("No source code is truncated"));
        } else {
            assert!(source.source.contains("goelect.txelections.civixapps.com"));
        }
    }
    if let Ok(path) = std::env::var("TURNOUT_PANOLA_NATIVE_OUTPUT") {
        let path = std::path::PathBuf::from(path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, serde_json::to_vec_pretty(&reports).unwrap()).unwrap();
    }
}
