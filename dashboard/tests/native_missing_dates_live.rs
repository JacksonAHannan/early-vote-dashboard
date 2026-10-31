//! Current native publications retain independently dated SOS alternatives.
use std::{path::Path, time::Duration};
use texas_turnout::{Reference, county, start};

#[tokio::test]
#[ignore = "downloads current San Patricio county PDFs and dated official SOS fallback"]
async fn san_patricio_missing_native_day_uses_exact_dated_sos() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let references: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let reference = references.iter().find(|r| r.id == "sanpatricio").unwrap();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(120))
        .build()
        .unwrap();
    let days = county::collect(&client, reference, 2026, 11).await.unwrap();
    for offset in 0..11 {
        let when = start(2026) + chrono::Duration::days(offset);
        let matches: Vec<_> = days.iter().filter(|d| d.date == when).collect();
        assert_eq!(
            matches.len(),
            1,
            "missing or duplicate exact dated report {when}"
        );
        let day = matches[0];
        assert!(!day.cumulative && !day.complete);
        assert_eq!(day.sha256.len(), 64);
        assert!(day.counts.values().sum::<u64>() > 0);
    }
    let recovered = &days[9];
    assert_eq!(recovered.date.to_string(), "2026-10-28");
    assert!(recovered.counts.len() >= 20);
    assert!(recovered.counts.values().sum::<u64>() >= 800);
    if let Ok(path) = std::env::var("TURNOUT_NATIVE_FALLBACK_OUTPUT") {
        std::fs::write(path, serde_json::to_vec_pretty(&days).unwrap()).unwrap();
    }
}
