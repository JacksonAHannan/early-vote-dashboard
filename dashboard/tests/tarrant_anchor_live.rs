//! Explicit live acceptance of cumulative-only Tarrant anchor plus original daily sources.
use std::{path::PathBuf, time::Duration};
use texas_turnout::{Reference, county};
#[tokio::test]
#[ignore = "downloads official voter rosters in memory; writes anonymous aggregate sources only"]
async fn tarrant_exact_cutoff_anchor_retains_original_daily_sources() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = refs.into_iter().find(|r| r.id == "tarrant").unwrap();
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(120))
        .user_agent("Mozilla/5.0 TexasTurnout source audit")
        .build()
        .unwrap();
    let sources = county::collect(&client, &reference, 2026, 8).await.unwrap();
    let daily: Vec<_> = sources.iter().filter(|d| !d.cumulative).collect();
    assert_eq!(daily.len(), 8);
    assert!(
        daily
            .iter()
            .all(|d| d.date <= chrono::NaiveDate::from_ymd_opt(2026, 10, 26).unwrap())
    );
    assert!(
        daily
            .iter()
            .all(|d| d.source.contains("goelect.txelections.civixapps.com"))
    );
    let anchors: Vec<_> = sources.iter().filter(|d| d.cumulative).collect();
    assert_eq!(anchors.len(), 1);
    let anchor = anchors[0];
    assert_eq!(anchor.date.to_string(), "2026-10-26");
    assert_eq!(anchor.allow_daily_difference, Some(false));
    assert!(!anchor.complete);
    assert_eq!(
        anchor
            .counts
            .iter()
            .filter(|(p, _)| p.chars().all(|c| c.is_ascii_digit()))
            .count(),
        461
    );
    assert!(!anchor.unavailable_precincts.is_empty());
    assert!(anchor.unavailable_precincts.contains(&"1060".to_string()));
    assert!(!anchor.counts.contains_key("1060"));
    assert!(anchor.note.contains("actual cutoff day"));
    let output = PathBuf::from(
        std::env::var("TURNOUT_TARRANT_ANCHOR_OUTPUT")
            .expect("set isolated anonymous aggregate output"),
    );
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    std::fs::write(output, serde_json::to_vec_pretty(&sources).unwrap()).unwrap();
}
