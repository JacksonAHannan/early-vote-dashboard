use anyhow::{Context, Result, ensure};
use axum::{
    Json, Router,
    extract::{Path as AxumPath, Query, State},
    http::{StatusCode, header},
    response::{Html, IntoResponse},
    routing::{get, post},
};
use chrono::{NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use texas_turnout::*;
use tokio::sync::{Mutex, RwLock};

#[derive(Clone)]
struct App {
    snapshot: Arc<RwLock<Snapshot>>,
    updating: Arc<Mutex<()>>,
    root: PathBuf,
    client: reqwest::Client,
    through: Option<NaiveDate>,
}
fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn empty() -> Snapshot {
    Snapshot {
        completeness_sha256: String::new(),
        reference_sha256: String::new(),
        schema_version: 1,
        generated_at: String::new(),
        through: String::new(),
        days: 0,
        geography: GEOGRAPHY.into(),
        counties: vec![],
    }
}
fn atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(tmp, path)?;
    Ok(())
}
async fn refresh(app: &App) -> Result<()> {
    let _guard = app.updating.try_lock().context("refresh already running")?;
    refresh_locked(app).await
}
async fn refresh_locked(app: &App) -> Result<()> {
    let through = app.through.unwrap_or_else(latest_completed);
    // A downloaded source is not necessarily a completed publication.
    let controls = tokio::process::Command::new("python3")
        .arg(app.root.join("scripts/audit_completeness.py"))
        .args(["--through", &through.to_string()])
        .output()
        .await;
    match controls {
        Ok(result) if result.status.success() => {
            eprintln!("{}", String::from_utf8_lossy(&result.stdout).trim())
        }
        Ok(result) => eprintln!(
            "Completion audit failed: {}",
            String::from_utf8_lossy(&result.stderr)
        ),
        Err(error) => eprintln!("Completion audit unavailable: {error}"),
    }
    let (precinct, statewide, states) = tokio::join!(
        refresh_precincts(app),
        statewide::refresh(&app.client, &app.root, through),
        interstate::refresh(&app.root, app.through)
    );
    if let Err(error) = states {
        eprintln!("Additional state refresh failed: {error:#}");
    }
    if let Err(error) = statewide {
        eprintln!("Statewide totals refresh failed: {error:#}");
    }
    if let Ok(bytes) = std::fs::read(app.root.join("data/reference.json"))
        && let Ok(references) = serde_json::from_slice::<Vec<Reference>>(&bytes)
    {
        let snapshot = app.snapshot.read().await.clone();
        if let Err(error) =
            trends::refresh_history(&app.client, &app.root, &references, &snapshot).await
        {
            eprintln!("Historical timeline refresh failed: {error:#}");
        }
    }
    precinct
}
async fn refresh_precincts(app: &App) -> Result<()> {
    let through = app.through.unwrap_or_else(latest_completed);
    let n = days_through(through)?;
    let reference_bytes = std::fs::read(app.root.join("data/reference.json"))?;
    let reference_sha256 = format!("{:x}", Sha256::digest(&reference_bytes));
    let references: Vec<Reference> = serde_json::from_slice(&reference_bytes)?;
    let previous = app.snapshot.read().await.clone();
    let mut jobs = tokio::task::JoinSet::new();
    let semaphore = Arc::new(tokio::sync::Semaphore::new(3));
    for reference in references {
        let app = app.clone();
        let semaphore = semaphore.clone();
        let prior = previous
            .counties
            .iter()
            .find(|c| c.id == reference.id)
            .cloned();
        jobs.spawn(async move {
            let _permit = semaphore.acquire_owned().await.unwrap();
            let mut daily = Vec::new();
            let mut failure = None;
            for year in [2024, 2026] {
                let cache = app
                    .root
                    .join(format!("data/cache/{}/{year}-series.json", reference.id));
                let cached: Option<Vec<Daily>> = std::fs::read(&cache)
                    .ok()
                    .and_then(|b| serde_json::from_slice(&b).ok());
                // Reuse the verified full-calendar baseline when the regular cache
                // stops before a newly completed day. An explicitly cleared cache
                // still takes the existing --recheck-history download path.
                let cached = if year == 2024
                    && cached
                        .as_ref()
                        .is_some_and(|v| sum_days(v, year, n).is_err())
                {
                    std::fs::read(app.root.join(format!(
                        "data/history-cache/{}/2024-series.json",
                        reference.id
                    )))
                    .ok()
                    .and_then(|b| serde_json::from_slice::<Vec<Daily>>(&b).ok())
                    .filter(|v| sum_days(v, year, n).is_ok())
                    .or(cached)
                } else {
                    cached
                };
                let enough = cached
                    .as_ref()
                    .is_some_and(|days| sum_days(days, year, n).is_ok());
                let series = if year == 2024 && enough {
                    Ok(cached.clone().unwrap())
                } else if county::has_adapter(&reference.id, year) {
                    county::collect(&app.client, &reference, year, n).await
                } else {
                    let mut values = Vec::new();
                    let mut identities = std::collections::BTreeSet::new();
                    for day in 0..n {
                        let date = start(year) + chrono::Duration::days(i64::from(day));
                        match fetch::fetch_state(&app.client, &reference, date, &mut identities)
                            .await
                        {
                            Ok(value) => values.push(value),
                            Err(error) => {
                                failure = Some(format!(
                                    "{year} {date}: {error:#}; other reported dates retained"
                                ))
                            }
                        }
                    }
                    Ok(values)
                };
                let mut values = cached.unwrap_or_default();
                match series {
                    Ok(fresh) => values = trends::merge_sources(values.into_iter().chain(fresh)),
                    Err(error) => {
                        failure = Some(format!(
                            "{year}: {error:#}; earlier reported dates retained"
                        ))
                    }
                }
                if !values.is_empty() {
                    if let Err(error) = atomic(&cache, &serde_json::to_vec_pretty(&values).unwrap())
                    {
                        failure = Some(error.to_string());
                    }
                    daily.extend(values);
                }
            }
            if let Some(prior) = prior {
                daily = trends::merge_sources(prior.sources.into_iter().chain(daily));
            }
            let now = Utc::now().to_rfc3339();
            if let Some(error) = &failure {
                eprintln!("{}: {error}", reference.name);
            }
            eprintln!(
                "{}: {} reported source observations retained",
                reference.name,
                daily.len()
            );
            County {
                reference_groups: vec![],
                id: reference.id,
                name: reference.name,
                status: "current".into(),
                checked_at: now,
                error: failure,
                periods: vec![],
                sources: daily,
            }
        });
    }
    let mut counties = Vec::new();
    while let Some(result) = jobs.join_next().await {
        counties.push(result?);
    }
    let order = [
        "travis",
        "dallas",
        "montgomery",
        "bell",
        "hays",
        "ellis",
        "mclennan",
        "hockley",
        "madison",
    ];
    counties.sort_by_key(|c| {
        (
            order.iter().position(|id| *id == c.id).unwrap_or(99),
            c.name.clone(),
        )
    });
    let snapshot = Snapshot {
        completeness_sha256: String::new(),
        reference_sha256,
        schema_version: 1,
        generated_at: Utc::now().to_rfc3339(),
        through: through.to_string(),
        days: n,
        geography: GEOGRAPHY.into(),
        counties,
    };
    let snapshot = quality::qualify(&app.root, &snapshot)?;
    let bytes = serde_json::to_vec_pretty(&snapshot)?;
    atomic(
        &app.root.join(format!(
            "data/snapshots/{}.json",
            Utc::now().format("%Y%m%dT%H%M%S%fZ")
        )),
        &bytes,
    )?;
    atomic(&app.root.join("data/latest.json"), &bytes)?;
    *app.snapshot.write().await = snapshot;
    let script = app.root.join("scripts/render_images.py");
    let output = tokio::process::Command::new("uv")
        .args([
            "run",
            "--quiet",
            "--with",
            "matplotlib==3.11.2",
            "--with",
            "pillow==13.0.0",
            "python",
        ])
        .arg(script)
        .arg("--snapshot")
        .arg(app.root.join("data/latest.json"))
        .output()
        .await;
    match output {
        Ok(result) if result.status.success() => {
            eprintln!("{}", String::from_utf8_lossy(&result.stdout).trim())
        }
        Ok(result) => eprintln!(
            "Image export failed: {}",
            String::from_utf8_lossy(&result.stderr)
        ),
        Err(error) => eprintln!("Image export failed: {error}"),
    }
    Ok(())
}
#[derive(Serialize)]
struct DashboardData {
    #[serde(flatten)]
    snapshot: Snapshot,
    regressions: Vec<regression::Regression>,
}
async fn data(State(app): State<App>) -> Json<DashboardData> {
    let snapshot = app.snapshot.read().await.clone();
    let regressions = regression::summaries(&snapshot);
    Json(DashboardData {
        snapshot,
        regressions,
    })
}
#[derive(Deserialize)]
struct TrendsQuery {
    county: Option<String>,
    cohort: Option<String>,
    view: Option<String>,
    metric: Option<String>,
}
async fn trend_view(State(app): State<App>, Query(query): Query<TrendsQuery>) -> impl IntoResponse {
    let result = (|| -> Result<serde_json::Value> {
        let snapshot = app.snapshot.try_read().context("snapshot busy; retry")?;
        let mut history: trends::History = std::fs::read(app.root.join("data/history.json"))
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_default();
        quality::Report::load(&app.root)
            .unwrap_or_default()
            .history(&mut history);
        let classification: Option<demographics::Data> =
            match query.view.as_deref().unwrap_or("partisan") {
                "partisan" => None,
                "demographic" => Some(serde_json::from_slice(&std::fs::read(
                    app.root.join("data/demographics.json"),
                )?)?),
                "primary" => Some(serde_json::from_slice(&std::fs::read(
                    demographics::primary_path(&app.root),
                )?)?),
                _ => anyhow::bail!("Unknown classification view"),
            };
        let mut view = trends::analyze(
            &snapshot,
            &history,
            classification.as_ref(),
            query.county.as_deref().unwrap_or("all"),
            query.cohort.as_deref().unwrap_or("matched"),
            query.metric.as_deref().unwrap_or("partisan"),
        )?;
        quality::pair_trends(&mut view);
        let mut value = serde_json::to_value(view)?;
        value["generated_at"] = serde_json::json!(snapshot.generated_at);
        value["history_generated_at"] = serde_json::json!(history.generated_at);
        Ok(value)
    })();
    match result {
        Ok(value) => (StatusCode::OK, Json(value)),
        Err(error) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
    }
}
async fn aggregate_file(app: App, file: &str) -> impl IntoResponse {
    match std::fs::read(app.root.join("data").join(file)) {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/json")],
            bytes,
        ),
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            [(header::CONTENT_TYPE, "application/json")],
            br#"{"error":"Aggregate data unavailable"}"#.to_vec(),
        ),
    }
}
async fn primary_data(State(app): State<App>) -> impl IntoResponse {
    match std::fs::read(demographics::primary_path(&app.root)) {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/json")],
            bytes,
        ),
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            [(header::CONTENT_TYPE, "application/json")],
            br#"{"error":"Primary data unavailable"}"#.to_vec(),
        ),
    }
}
async fn reference_data(State(app): State<App>) -> impl IntoResponse {
    aggregate_file(app, "reference.json").await
}
#[derive(Default, Deserialize)]
struct VotingMethodQuery {
    method: Option<String>,
}
async fn statewide_data(
    State(app): State<App>,
    Query(query): Query<VotingMethodQuery>,
) -> impl IntoResponse {
    match qualified_statewide(&app, query.method.as_deref().unwrap_or("total")) {
        Ok(data) => (StatusCode::OK, Json(serde_json::to_value(data).unwrap())),
        Err(error) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
    }
}
fn qualified_statewide(app: &App, method: &str) -> Result<statewide::Data> {
    let snapshot = app.snapshot.try_read().context("snapshot busy; retry")?;
    pages::qualified_statewide_method(&app.root, &snapshot, method)
}
async fn completion_data(State(app): State<App>) -> impl IntoResponse {
    aggregate_file(app, "completeness.json").await
}
#[derive(Deserialize)]
struct CountyBucketQuery {
    day: u32,
    view: Option<String>,
    metric: Option<String>,
    method: Option<String>,
}
async fn county_bucket_view(
    State(app): State<App>,
    Query(query): Query<CountyBucketQuery>,
) -> impl IntoResponse {
    let result = (|| -> Result<serde_json::Value> {
        let statewide = qualified_statewide(&app, query.method.as_deref().unwrap_or("total"))?;
        let reference: county_buckets::Reference =
            serde_json::from_slice(&std::fs::read(app.root.join("data/county-reference.json"))?)?;
        Ok(serde_json::to_value(county_buckets::analyze(
            &statewide,
            &reference,
            query.view.as_deref().unwrap_or("partisan"),
            query.metric.as_deref().unwrap_or(
                if query.view.as_deref().unwrap_or("partisan") == "partisan" {
                    "presidential_margin"
                } else {
                    "hispanic_vap"
                },
            ),
            query.day,
        )?)?)
    })();
    match result {
        Ok(value) => (StatusCode::OK, Json(value)),
        Err(error) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
    }
}
async fn demographic_data(State(app): State<App>) -> impl IntoResponse {
    match std::fs::read(app.root.join("data/demographics.json")) {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/json")],
            bytes,
        ),
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            [(header::CONTENT_TYPE, "application/json")],
            br#"{"error":"Census data unavailable"}"#.to_vec(),
        ),
    }
}
#[derive(Deserialize)]
struct DemographicQuery {
    day: u32,
    cohort: Option<String>,
    metric: String,
    view: Option<String>,
}
async fn demographic_view(
    State(app): State<App>,
    Query(query): Query<DemographicQuery>,
) -> impl IntoResponse {
    let result = (|| -> Result<serde_json::Value> {
        let file = match query.view.as_deref().unwrap_or("demographic") {
            "demographic" => "demographics.json",
            "primary" => "primary.json",
            _ => anyhow::bail!("Unknown classification view"),
        };
        let path = if file == "primary.json" {
            demographics::primary_path(&app.root)
        } else {
            app.root.join("data").join(file)
        };
        let bytes = std::fs::read(path)?;
        let census: demographics::Data = serde_json::from_slice(&bytes)?;
        let cohort = query.cohort.as_deref().unwrap_or("matched");
        let snapshot = app.snapshot.try_read().context("snapshot busy; retry")?;
        let mut views = serde_json::Map::new();
        for county in std::iter::once("all").chain(snapshot.counties.iter().map(|c| c.id.as_str()))
        {
            views.insert(
                county.into(),
                serde_json::to_value(demographics::analyze(
                    &snapshot,
                    &census,
                    county,
                    query.day,
                    cohort,
                    &query.metric,
                )?)?,
            );
        }
        Ok(serde_json::json!({"generated_at":snapshot.generated_at,"views":views}))
    })();
    match result {
        Ok(value) => (StatusCode::OK, Json(value)),
        Err(error) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
    }
}
async fn county_map(
    State(app): State<App>,
    AxumPath(county): AxumPath<String>,
) -> impl IntoResponse {
    let valid = app
        .snapshot
        .read()
        .await
        .counties
        .iter()
        .any(|c| c.id == county);
    if !valid {
        return (
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "application/json")],
            br#"{"error":"Unknown county"}"#.to_vec(),
        );
    }
    match std::fs::read(app.root.join(format!("data/maps/{county}.geojson"))) {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "application/geo+json")],
            bytes,
        ),
        Err(_) => (
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "application/json")],
            br#"{"error":"County map unavailable"}"#.to_vec(),
        ),
    }
}
async fn update(State(app): State<App>) -> impl IntoResponse {
    let Ok(guard) = app.updating.clone().try_lock_owned() else {
        return (StatusCode::CONFLICT, "Refresh already running");
    };
    tokio::spawn(async move {
        if let Err(e) = refresh_locked(&app).await {
            eprintln!("Refresh failed: {e:#}");
        }
        drop(guard);
    });
    (StatusCode::ACCEPTED, "Refresh started")
}
async fn health(State(app): State<App>) -> Json<serde_json::Value> {
    Json(
        serde_json::json!({"updating":app.updating.try_lock().is_err(),"generated_at":app.snapshot.read().await.generated_at}),
    )
}
async fn state_catalog(State(app): State<App>) -> Json<serde_json::Value> {
    Json(interstate::catalog(&app.root))
}
async fn state_view(
    State(app): State<App>,
    AxumPath(state): AxumPath<String>,
    Query(query): Query<interstate::Query>,
) -> impl IntoResponse {
    let result =
        tokio::task::spawn_blocking(move || interstate::view(&app.root, &state, &query)).await;
    match result {
        Ok(Ok(data)) => (StatusCode::OK, Json(data)),
        Ok(Err(error)) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error":"State view unavailable"})),
        ),
    }
}
async fn state_geometry(
    State(app): State<App>,
    AxumPath(state): AxumPath<String>,
) -> impl IntoResponse {
    match interstate::map(&app.root, &state) {
        Ok(data) => (StatusCode::OK, Json(data)),
        Err(error) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
    }
}
async fn state_precincts(
    State(app): State<App>,
    AxumPath(state): AxumPath<String>,
    Query(query): Query<interstate::PrecinctQuery>,
) -> impl IntoResponse {
    match tokio::task::spawn_blocking(move || interstate::precincts(&app.root, &state, &query))
        .await
    {
        Ok(Ok(data)) => (StatusCode::OK, Json(data)),
        Ok(Err(error)) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        ),
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error":"Precinct observations unavailable"})),
        ),
    }
}
#[derive(Deserialize)]
struct Export {
    day: u32,
    cohort: Option<String>,
    county: Option<String>,
}
async fn export(State(app): State<App>, Query(query): Query<Export>) -> impl IntoResponse {
    let snapshot = app.snapshot.read().await;
    let mut writer = csv::Writer::from_writer(Vec::new());
    writer
        .write_record([
            "county",
            "through_2026",
            "through_2024",
            "cohort",
            "margin_band",
            "groups",
            "votes_2024",
            "votes_2026",
            "ratio",
            "county_status",
        ])
        .unwrap();
    let cohort = query.cohort.as_deref().unwrap_or("matched");
    if !["matched", "unchanged"].contains(&cohort) {
        return (
            StatusCode::BAD_REQUEST,
            [(header::CONTENT_TYPE, "text/plain")],
            "Unknown cohort".to_string(),
        )
            .into_response();
    }
    for county in &snapshot.counties {
        if query
            .county
            .as_deref()
            .is_some_and(|c| c != "all" && c != county.id)
        {
            continue;
        }
        if let Some(period) = county.periods.iter().find(|p| p.day == query.day) {
            for bucket in &period.buckets {
                let c = if cohort == "unchanged" {
                    &bucket.unchanged
                } else {
                    &bucket.matched
                };
                writer
                    .write_record([
                        county.name.clone(),
                        period.through_2026.clone(),
                        period.through_2024.clone(),
                        cohort.into(),
                        bucket.label.clone(),
                        c.groups.to_string(),
                        c.votes_2024.to_string(),
                        c.votes_2026.to_string(),
                        c.ratio.map(|v| v.to_string()).unwrap_or_default(),
                        county.status.clone(),
                    ])
                    .unwrap();
            }
        }
    }
    let bytes = writer.into_inner().unwrap();
    (
        [
            (header::CONTENT_TYPE, "text/csv; charset=utf-8"),
            (
                header::CONTENT_DISPOSITION,
                "attachment; filename=texas-turnout.csv",
            ),
        ],
        bytes,
    )
        .into_response()
}
#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--help") {
        println!(
            "texas-turnout [serve|refresh|rebuild|statewide|pages] [--through YYYY-MM-DD] [--offline] [--port 8741] [--recheck-history]\nrebuild uses retained aggregates only. statewide refreshes county aggregates, or rebuilds them with --offline. Default cutoff: latest completed America/Chicago day, capped October 30. Refresh every TURNOUT_REFRESH_SECONDS (default 3600)."
        );
        return Ok(());
    }
    let value = |flag: &str| {
        args.iter()
            .position(|a| a == flag)
            .map(|i| args.get(i + 1).context("missing option value"))
            .transpose()
    };
    let through = value("--through")?
        .map(|s| NaiveDate::parse_from_str(s, "%Y-%m-%d"))
        .transpose()?;
    if let Some(date) = through {
        days_through(date)?;
        ensure!(
            date <= latest_completed(),
            "cutoff must be a completed early-voting day"
        );
    }
    let root = root();
    if args.get(1).is_some_and(|s| s == "pages") {
        let output = value("--output")?.context("pages requires --output DIRECTORY")?;
        let report = pages::build(&root, Path::new(output))?;
        println!("{}", serde_json::to_string_pretty(&report)?);
        return Ok(());
    }
    if args.get(1).is_some_and(|s| s == "rebuild") {
        let snapshot = rebuild::from_cache(&root, through.unwrap_or_else(latest_completed))?;
        let bytes = serde_json::to_vec_pretty(&snapshot)?;
        let history = rebuild::history_from_cache(&root, &snapshot)?;
        atomic(
            &root.join("data/history.json"),
            &serde_json::to_vec_pretty(&history)?,
        )?;
        atomic(&root.join("data/latest.json"), &bytes)?;
        atomic(
            &root.join(format!(
                "data/snapshots/{}-cached.json",
                Utc::now().format("%Y%m%dT%H%M%S%fZ")
            )),
            &bytes,
        )?;
        println!(
            "Rebuilt {} precinct counties from retained aggregates",
            snapshot.counties.len()
        );
        return Ok(());
    }
    if args.iter().any(|a| a == "--recheck-history") {
        for county in std::fs::read_dir(root.join("data/cache"))
            .into_iter()
            .flatten()
            .flatten()
        {
            for file in std::fs::read_dir(county.path())?.flatten() {
                if file.file_name().to_string_lossy().starts_with("2024-") {
                    std::fs::remove_file(file.path())?;
                }
            }
        }
    }
    let snapshot = std::fs::read(root.join("data/latest.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_else(empty);
    let snapshot = if snapshot.days > 0 {
        quality::qualify(&root, &snapshot)?
    } else {
        snapshot
    };
    let client=reqwest::Client::builder().cookie_store(true).user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36").connect_timeout(Duration::from_secs(20)).timeout(Duration::from_secs(120)).build()?;
    if args.get(1).is_some_and(|s| s == "statewide") {
        let cutoff = through.unwrap_or_else(latest_completed);
        let report = if args.iter().any(|s| s == "--offline") {
            statewide::rebuild(&root, cutoff)?
        } else {
            statewide::refresh(&client, &root, cutoff).await?
        };
        println!(
            "{} county aggregates · {} · through {}",
            report.counties.len(),
            statewide::method_label(&report.voting_method),
            report.through
        );
        return Ok(());
    }
    let app = App {
        snapshot: Arc::new(RwLock::new(snapshot)),
        updating: Arc::new(Mutex::new(())),
        root,
        client,
        through,
    };
    if args.get(1).is_some_and(|s| s == "refresh") {
        return refresh(&app).await;
    }
    if !args.iter().any(|s| s == "--offline") {
        let updater = app.clone();
        let seconds = std::env::var("TURNOUT_REFRESH_SECONDS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(3600)
            .max(60);
        tokio::spawn(async move {
            loop {
                if let Err(e) = refresh(&updater).await {
                    eprintln!("Refresh failed: {e:#}");
                }
                tokio::time::sleep(Duration::from_secs(seconds)).await;
            }
        });
    }
    let router = Router::new()
        .route(
            "/",
            get(|| async { Html(include_str!("../static/index.html")) }),
        )
        .route(
            "/regression-cohort.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/regression-cohort.js"),
                )
            }),
        )
        .route(
            "/regression-scale.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/regression-scale.js"),
                )
            }),
        )
        .route(
            "/app.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/app.js"),
                )
            }),
        )
        .route(
            "/style.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css")],
                    include_str!("../static/style.css"),
                )
            }),
        )
        .route(
            "/vendor/leaflet.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/vendor/leaflet/leaflet.js"),
                )
            }),
        )
        .route(
            "/vendor/leaflet.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css")],
                    include_str!("../static/vendor/leaflet/leaflet.css"),
                )
            }),
        )
        .route(
            "/atlas.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/atlas.js"),
                )
            }),
        )
        .route(
            "/tracking.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/tracking.js"),
                )
            }),
        )
        .route(
            "/visuals.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/visuals.js"),
                )
            }),
        )
        .route("/api/trends", get(trend_view))
        .route("/api/states", get(state_catalog))
        .route("/api/states/{state}", get(state_view))
        .route("/api/states/{state}/map", get(state_geometry))
        .route("/api/states/{state}/precincts", get(state_precincts))
        .route(
            "/states.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/states.js"),
                )
            }),
        )
        .route(
            "/states.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css")],
                    include_str!("../static/states.css"),
                )
            }),
        )
        .route(
            "/county-view.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript")],
                    include_str!("../static/county-view.js"),
                )
            }),
        )
        .route("/api/county-buckets", get(county_bucket_view))
        .route("/api/primary", get(primary_data))
        .route("/api/statewide", get(statewide_data))
        .route("/api/completeness", get(completion_data))
        .route("/api/reference", get(reference_data))
        .route("/api/demographics", get(demographic_data))
        .route("/api/demographic-view", get(demographic_view))
        .route("/api/map/{county}", get(county_map))
        .route("/api/data", get(data))
        .route("/api/status", get(health))
        .route("/api/refresh", post(update))
        .route("/api/export.csv", get(export))
        .with_state(app);
    let port = value("--port")?
        .map(|s| s.parse::<u16>())
        .transpose()?
        .unwrap_or(8741);
    let listener = tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port)).await?;
    println!("http://127.0.0.1:{port}");
    axum::serve(listener, router).await?;
    Ok(())
}
