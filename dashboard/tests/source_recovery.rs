//! Opt-in checks of the official sources implicated in the October 24 outage.
use std::{collections::BTreeSet, time::Duration};
use texas_turnout::{Reference, county, fetch, start, sum_days};

#[tokio::test]
#[ignore = "downloads live official rosters into memory; never run as an offline unit test"]
async fn reported_counties_recover_available_precinct_sources() {
    let references: Vec<Reference> = serde_json::from_slice(
        &std::fs::read(concat!(env!("CARGO_MANIFEST_DIR"), "/data/reference.json")).unwrap(),
    )
    .unwrap();
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")
        .connect_timeout(Duration::from_secs(20)).timeout(Duration::from_secs(120)).build().unwrap();
    for reference in references
        .iter()
        .filter(|r| ["travis", "bell", "madison"].contains(&r.id.as_str()))
    {
        let values = if county::has_adapter(&reference.id, 2026) {
            county::collect(&client, reference, 2026, 4).await.unwrap()
        } else {
            let mut identities = BTreeSet::new();
            let mut values = Vec::new();
            for day in 0..4 {
                values.push(
                    fetch::fetch_state(
                        &client,
                        reference,
                        start(2026) + chrono::Duration::days(day),
                        &mut identities,
                    )
                    .await
                    .unwrap(),
                );
            }
            values
        };
        assert_eq!(values.len(), 4);
        let counts = sum_days(&values, 2026, 4).unwrap();
        assert!(counts.values().sum::<u64>() > 0);
        if reference.id == "travis" {
            assert!(
                values
                    .iter()
                    .all(|v| v.source.contains("G26-Voter-Rosters-1.zip"))
            );
        }
        println!(
            "{}",
            serde_json::json!({"county": reference.id, "through": "2026-10-22", "status":"passed", "votes":counts.values().sum::<u64>(),"source":values[0].source,"sha256":values[0].sha256})
        );
    }
}
