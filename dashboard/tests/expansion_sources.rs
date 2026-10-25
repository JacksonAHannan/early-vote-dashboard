//! Opt-in checks of the same collectors used by automatic refresh; no raw rows persist.
use std::{collections::BTreeSet, path::Path, time::Duration};
use texas_turnout::{Daily, Reference, county, fetch, start, sum_days};
#[tokio::test]
#[ignore = "downloads live official rosters into memory; run explicitly"]
async fn expanded_counties_refresh_through_the_real_rust_collectors() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let client = reqwest::Client::builder()
        .cookie_store(true)
        .user_agent("Mozilla/5.0")
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(120))
        .build()
        .unwrap();
    for (id, year, n) in [
        ("harris", 2024, 12),
        ("harris", 2026, 5),
        ("tarrant", 2024, 5),
        ("fortbend", 2026, 5),
        ("collin", 2024, 5),
        ("elpaso", 2024, 3),
        ("tomgreen", 2026, 1),
        ("nueces", 2026, 5),
    ] {
        if std::env::var("TURNOUT_VERIFY_COUNTY").is_ok_and(|selected| selected != id) {
            continue;
        }
        let r = refs.iter().find(|r| r.id == id).unwrap();
        let expected: Vec<Daily> = serde_json::from_slice(
            &std::fs::read(root.join(format!("data/cache/{id}/{year}-series.json"))).unwrap(),
        )
        .unwrap();
        let actual = if county::has_adapter(id, year) {
            county::collect(&client, r, year, n).await.unwrap()
        } else {
            let mut seen = BTreeSet::new();
            let mut days = vec![];
            for offset in 0..n {
                days.push(
                    fetch::fetch_state(
                        &client,
                        r,
                        start(year) + chrono::Duration::days(i64::from(offset)),
                        &mut seen,
                    )
                    .await
                    .unwrap(),
                );
            }
            days
        };
        for day in 1..=n {
            assert_eq!(
                sum_days(&actual, year, day).unwrap(),
                sum_days(&expected, year, day).unwrap(),
                "{id}/{year}/day{day}"
            );
        }
        eprintln!(
            "{id} {year}: {n} real Rust collector dates match independently acquired aggregates"
        );
    }
}
