//! Opt-in memory-only acquisition through the real native/SOS collector paths.
use std::{collections::BTreeSet, path::PathBuf, time::Duration};
use texas_turnout::{Daily, Reference, county, fetch, start};
#[tokio::test]
#[ignore = "downloads official voter rosters into memory and writes anonymous aggregates only"]
async fn recover_dated_county_sources() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let refs: Vec<Reference> =
        serde_json::from_slice(&std::fs::read(root.join("data/reference.json")).unwrap()).unwrap();
    let names = std::env::var("TURNOUT_RECOVERY_COUNTIES")
        .unwrap_or_else(|_| "dallas montgomery waller washington sanpatricio".into());
    let selected: Vec<_> = refs
        .into_iter()
        .filter(|r| names.split_whitespace().any(|id| id == r.id))
        .collect();
    assert_eq!(
        selected.len(),
        names.split_whitespace().count(),
        "Every requested county needs a geographic reference"
    );
    let out = PathBuf::from(
        std::env::var("TURNOUT_RECOVERY_OUTPUT")
            .expect("Set an isolated aggregate output directory"),
    );
    std::fs::create_dir_all(&out).unwrap();
    let client=reqwest::Client::builder().cookie_store(true).user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36").connect_timeout(Duration::from_secs(20)).timeout(Duration::from_secs(180)).build().unwrap();
    let semaphore = std::sync::Arc::new(tokio::sync::Semaphore::new(3));
    let mut jobs = tokio::task::JoinSet::new();
    for reference in selected {
        let client = client.clone();
        let out = out.clone();
        let semaphore = semaphore.clone();
        jobs.spawn(async move {
            let _permit=semaphore.acquire().await.unwrap();
            let result=async {
                if county::has_adapter(&reference.id,2026){county::collect(&client,&reference,2026,7).await}
                else{
                    let mut identities=BTreeSet::new();let mut values=Vec::new();
                    for day in 0..7 {
                        match fetch::fetch_state(&client,&reference,start(2026)+chrono::Duration::days(day),&mut identities).await {
                            Ok(value)=>values.push(value),
                            Err(error)=>eprintln!("{} day {}: {error:#}",reference.id,day+1),
                        }
                    }
                    anyhow::ensure!(!values.is_empty(),"No usable current reports");Ok(values)
                }
            }.await;
            match result {
                Ok(values)=>{
                    for value in &values {assert_eq!(value.county,reference.id);assert!(!value.counts.is_empty());assert_eq!(value.sha256.len(),64);}
                    if reference.id=="montgomery" {
                        assert_eq!(values.iter().find(|d|d.date.to_string()=="2026-10-24").unwrap().counts.values().sum::<u64>(),16212);
                        assert_eq!(values.iter().find(|d|d.date.to_string()=="2026-10-25").unwrap().counts.values().sum::<u64>(),9176);
                    }
                    std::fs::write(out.join(format!("{}-2026-series.json",reference.id)),serde_json::to_vec_pretty(&values).unwrap()).unwrap();
                    println!("{}",serde_json::json!({"county":reference.id,"days":values.len(),"votes":values.iter().map(|d|d.counts.values().sum::<u64>()).collect::<Vec<_>>(),"quarantined":values.iter().map(|d|&d.unavailable_precincts).collect::<Vec<_>>() }));
                    Ok::<_,String>((reference.id,values))
                }
                Err(error)=>Err(format!("{}: {error:#}",reference.id)),
            }
        });
    }
    let mut failures = Vec::new();
    let mut sources: Vec<(String, Vec<Daily>)> = Vec::new();
    while let Some(result) = jobs.join_next().await {
        match result.unwrap() {
            Ok(value) => sources.push(value),
            Err(error) => failures.push(error),
        }
    }
    assert!(!sources.is_empty());
    assert!(failures.is_empty(), "{}", failures.join("; "));
}
