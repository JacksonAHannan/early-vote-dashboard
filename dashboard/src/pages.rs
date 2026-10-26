//! Static GitHub Pages publication. All comparison math stays in the live Rust analyzers.
//! The browser adapter resolves query selections to immutable, anonymous JSON artifacts.
use crate::{
    Reference, Snapshot, county_buckets, demographics, interstate, quality, regression, statewide,
    trends,
};
use anyhow::{Context, Result, ensure};
use flate2::{Compression, write::GzEncoder};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Write,
    path::Path,
};

#[derive(Debug, Serialize)]
pub struct Summary {
    pub artifacts: usize,
    pub compressed_bytes: u64,
    pub generated_at: String,
    pub revision: String,
}
struct Publisher<'a> {
    out: &'a Path,
    routes: BTreeMap<String, String>,
    states: BTreeMap<String, Value>,
    precincts: BTreeMap<String, String>,
    artifacts: usize,
    bytes: u64,
    seen: BTreeSet<String>,
}
impl Publisher<'_> {
    fn store(&mut self, value: &impl Serialize) -> Result<String> {
        let bytes = serde_json::to_vec(value)?;
        let hash = format!("{:x}", Sha256::digest(&bytes));
        let name = format!("api-data/{hash}.json.gz");
        let path = self.out.join(&name);
        if !path.exists() {
            let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
            encoder.write_all(&bytes)?;
            let compressed = encoder.finish()?;
            std::fs::write(&path, compressed)?;
        }
        if self.seen.insert(name.clone()) {
            self.bytes += std::fs::metadata(path)?.len();
            self.artifacts += 1;
        }
        Ok(name)
    }
    fn route(
        &mut self,
        route: &str,
        params: &[(&str, &str)],
        value: &impl Serialize,
    ) -> Result<()> {
        let file = self.store(value)?;
        self.routes.insert(key(route, params), file);
        Ok(())
    }
}
fn key(route: &str, params: &[(&str, &str)]) -> String {
    let mut p = params.to_vec();
    p.sort_unstable();
    if p.is_empty() {
        return route.to_owned();
    }
    format!(
        "{route}?{}",
        p.iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("&")
    )
}
fn read<T: serde::de::DeserializeOwned>(root: &Path, name: &str) -> Result<T> {
    Ok(serde_json::from_slice(
        &std::fs::read(root.join(name))
            .with_context(|| format!("Missing public aggregate {name}"))?,
    )?)
}

fn publish_texas_maps<'a>(
    root: &Path,
    counties: impl IntoIterator<Item = &'a str>,
    publisher: &mut Publisher<'_>,
) -> Result<()> {
    for county in counties {
        let path = format!("data/maps/{county}.geojson");
        let value: Value = read(root, &path)
            .with_context(|| format!("Required Texas precinct map unavailable for {county}"))?;
        publisher.route(&format!("/api/map/{county}"), &[], &value)?;
    }
    Ok(())
}

/// Shared with the live endpoint: preserve its maximum date-specific matched precinct scope.
pub fn qualified_statewide(root: &Path, snapshot: &Snapshot) -> Result<statewide::Data> {
    qualified_statewide_method(root, snapshot, "total")
}

pub fn qualified_statewide_method(
    root: &Path,
    snapshot: &Snapshot,
    method: &str,
) -> Result<statewide::Data> {
    let saved: statewide::Data = read(root, "data/statewide.json")?;
    let raw = statewide::from_cache(root, &saved)?;
    let report = quality::Report::load(root).unwrap_or_default();
    let mut data = report.statewide(statewide::select_method(raw.clone(), "in_person")?);
    if method != "in_person" {
        return statewide::with_county_in_person(raw, &data, method);
    }
    let refs: Vec<Reference> = read(root, "data/reference.json")?;
    let history: trends::History = read(root, "data/history.json").unwrap_or_default();
    for county in &mut data.counties {
        let Some(reference) = refs.iter().find(|r| r.id == county.id) else {
            continue;
        };
        let raw_sources = trends::merge_sources(
            history
                .counties
                .get(&county.id)
                .into_iter()
                .flat_map(|h| h.sources.iter().cloned())
                .chain(
                    snapshot
                        .counties
                        .iter()
                        .find(|c| c.id == county.id)
                        .into_iter()
                        .flat_map(|c| c.sources.iter().cloned()),
                ),
        );
        let sources = report.sources(&county.id, &raw_sources);
        for d in &mut county.days {
            let mut coverage = json!({"daily_scope":"county","cumulative_scope":"county"});
            if d.date_2026 <= data.through {
                for cumulative in [false, true] {
                    if let Some(p) = crate::matching::period(reference, &sources, d.day, cumulative)
                    {
                        let key = if cumulative { "cumulative" } else { "daily" };
                        if cumulative {
                            d.cumulative_2024 = Some(p.county_2024);
                            d.cumulative_2026 = Some(p.county_2026);
                        } else {
                            d.votes_2024 = Some(p.county_2024);
                            d.votes_2026 = Some(p.county_2026);
                        }
                        coverage[key] = serde_json::to_value(p.coverage)?;
                        coverage[format!("{key}_scope")] = json!("matched_precincts");
                        d.status_2024 = "matched".into();
                        d.status_2026 = "matched".into();
                    }
                }
            }
            d.coverage = coverage;
        }
    }
    Ok(data)
}

pub fn build(root: &Path, out: &Path) -> Result<Summary> {
    ensure!(
        out != root && !root.starts_with(out),
        "Output must be separate from source inputs"
    );
    std::fs::create_dir_all(out.join("api-data"))?;
    let mut p = Publisher {
        out,
        routes: BTreeMap::new(),
        states: BTreeMap::new(),
        precincts: BTreeMap::new(),
        artifacts: 0,
        bytes: 0,
        seen: BTreeSet::new(),
    };
    let raw: Snapshot = read(root, "data/latest.json")?;
    let snapshot = quality::qualify(root, &raw)?;
    ensure!(snapshot.days > 0, "No observed Texas data");
    // Every county exposed by the precinct UI must retain its geometry on Pages.
    // Fail before producing the expensive analyses when a bootstrap omits maps.
    publish_texas_maps(
        root,
        snapshot.counties.iter().map(|county| county.id.as_str()),
        &mut p,
    )?;
    let texas_map: Value = read(root, "geography/texas-counties.geojson")?;
    p.route("/api/map/texas", &[], &texas_map)?;
    let mut data = serde_json::to_value(&snapshot)?;
    data["regressions"] = serde_json::to_value(regression::summaries(&snapshot))?;
    p.route("/api/data", &[], &data)?;
    p.route(
        "/api/status",
        &[],
        &json!({"updating":false,"generated_at":snapshot.generated_at}),
    )?;
    for (route, file) in [
        ("demographics", "demographics"),
        ("reference", "reference"),
        ("completeness", "completeness"),
    ] {
        let value: Value = read(root, &format!("data/{file}.json"))?;
        p.route(&format!("/api/{route}"), &[], &value)?;
    }
    let census: demographics::Data = read(root, "data/demographics.json")?;
    let places = crate::places::load(root)?;
    let place_source: Value = read(root, "places/texas.json")?;
    p.route("/api/places", &[], &place_source)?;
    let primary: demographics::Data =
        serde_json::from_slice(&std::fs::read(demographics::primary_path(root))?)?;
    p.route("/api/primary", &[], &serde_json::to_value(&primary)?)?;
    let statewide = qualified_statewide(root, &snapshot)?;
    ensure!(
        statewide
            .counties
            .iter()
            .any(|c| c.days.iter().any(|d| d.date_2026 <= statewide.through
                && d.cumulative_2024.is_some()
                && d.cumulative_2026.is_some())),
        "Combined county turnout is unavailable; refresh the mail-capable statewide aggregates before publishing"
    );
    p.route("/api/statewide", &[], &statewide)?;
    let county_reference: county_buckets::Reference = read(root, "data/county-reference.json")?;
    let mut place_county_reference = county_reference.clone();
    crate::places::county_reference(&mut place_county_reference, &places)?;
    let county_ids: Vec<&str> = std::iter::once("all")
        .chain(snapshot.counties.iter().map(|c| c.id.as_str()))
        .collect();
    let mut history: trends::History = read(root, "data/history.json")?;
    quality::Report::load(root)
        .unwrap_or_default()
        .history(&mut history);
    let references: Vec<Reference> = read(root, "data/reference.json")?;
    for cohort in ["matched", "unchanged"] {
        for (view, classification) in [
            ("partisan", None),
            ("demographic", Some(&census)),
            ("primary", Some(&primary)),
            ("place", Some(&places)),
        ] {
            let metrics: Vec<&str> = classification
                .map(|d| d.metrics.iter().map(|m| m.id.as_str()).collect())
                .unwrap_or_else(|| vec!["partisan"]);
            for metric in metrics {
                eprintln!("Pages: Texas {view}/{metric}/{cohort}");
                for county in &county_ids {
                    let mut v = trends::analyze(
                        &snapshot,
                        &history,
                        classification,
                        county,
                        cohort,
                        metric,
                    )?;
                    quality::pair_trends(&mut v);
                    let mut v = serde_json::to_value(v)?;
                    v["generated_at"] = json!(snapshot.generated_at);
                    v["history_generated_at"] = json!(history.generated_at);
                    p.route(
                        "/api/trends",
                        &[
                            ("view", view),
                            ("metric", metric),
                            ("cohort", cohort),
                            ("county", county),
                        ],
                        &v,
                    )?;
                }
                for day in 1..=snapshot.days {
                    p.route(
                        "/api/matrix-view",
                        &[
                            ("view", view),
                            ("metric", metric),
                            ("cohort", cohort),
                            ("day", &day.to_string()),
                        ],
                        &trends::matrix_view(
                            &snapshot,
                            &history,
                            &references,
                            classification,
                            day,
                            cohort,
                            metric,
                        )?,
                    )?;
                }
                if let Some(classification) = classification {
                    for day in 1..=snapshot.days {
                        let mut views = serde_json::Map::new();
                        for county in &county_ids {
                            views.insert(
                                (*county).to_owned(),
                                serde_json::to_value(demographics::analyze(
                                    &snapshot,
                                    classification,
                                    county,
                                    day,
                                    cohort,
                                    metric,
                                )?)?,
                            );
                        }
                        p.route(
                            "/api/demographic-view",
                            &[
                                ("view", view),
                                ("metric", metric),
                                ("cohort", cohort),
                                ("day", &day.to_string()),
                            ],
                            &json!({"generated_at":snapshot.generated_at,"views":views}),
                        )?;
                    }
                }
            }
        }
    }
    for voting_method in ["total", "in_person", "mail"] {
        let statewide = qualified_statewide_method(root, &snapshot, voting_method)?;
        p.route("/api/statewide", &[("method", voting_method)], &statewide)?;
        for day in 1..=snapshot.days {
            for (view, metrics) in [
                ("partisan", vec!["presidential_margin"]),
                ("place", vec![crate::places::METRIC]),
                (
                    "demographic",
                    county_reference
                        .metrics
                        .iter()
                        .filter(|m| m.unit == "percent")
                        .map(|m| m.id.as_str())
                        .collect(),
                ),
            ] {
                for metric in metrics {
                    p.route(
                        "/api/county-buckets",
                        &[
                            ("view", view),
                            ("metric", metric),
                            ("day", &day.to_string()),
                            ("method", voting_method),
                        ],
                        &county_buckets::analyze(
                            &statewide,
                            if view == "place" {
                                &place_county_reference
                            } else {
                                &county_reference
                            },
                            view,
                            metric,
                            day,
                        )?,
                    )?;
                }
            }
        }
    }
    p.route("/api/states", &[], &interstate::catalog(root))?;
    for (state, _, _) in interstate::STATES {
        export_state(root, state, &mut p)?;
    }
    copy_static(root, out)?;
    let manifest = json!({"schema_version":1,"generated_at":snapshot.generated_at,"routes":p.routes,"states":p.states,"precincts":p.precincts});
    let manifest_bytes = serde_json::to_vec(&manifest)?;
    let revision = format!("{:x}", Sha256::digest(&manifest_bytes));
    std::fs::write(out.join("api-manifest.json"), manifest_bytes)?;
    std::fs::write(out.join(".nojekyll"), b"")?;
    let summary = Summary {
        artifacts: p.artifacts,
        compressed_bytes: p.bytes,
        generated_at: snapshot.generated_at,
        revision,
    };
    std::fs::write(
        out.join("publication.json"),
        serde_json::to_vec_pretty(&summary)?,
    )?;
    Ok(summary)
}

fn export_state(root: &Path, state: &str, p: &mut Publisher<'_>) -> Result<()> {
    let data = interstate::load(root, state)?;
    p.route(
        &format!("/api/states/{state}/map"),
        &[],
        &interstate::map(root, state)?,
    )?;
    let reference: Value = read(root, &format!("data/states/{state}-reference.json"))?;
    let dimensions: std::collections::BTreeSet<_> = data
        .observations
        .iter()
        .flat_map(|o| o.breakdowns.keys().cloned())
        .collect();
    let mut classes = vec![("partisan".to_owned(), "non_white_vap".to_owned())];
    classes.extend(
        reference["metrics"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|m| m["id"].as_str())
            .map(|m| ("demographic".to_owned(), m.to_owned())),
    );
    classes.extend(
        dimensions
            .iter()
            .map(|d| (d.to_owned(), "non_white_vap".to_owned())),
    );
    let mut state_descriptor = serde_json::Map::new();
    let mut precinct_dates = std::collections::BTreeSet::new();
    for method in ["in_person", "mail", "total"] {
        for (classification, metric) in &classes {
            eprintln!("Pages: {state} {method}/{classification}/{metric}");
            let query = interstate::Query {
                date: None,
                method: Some(method.into()),
                classification: Some(classification.clone()),
                metric: Some(metric.clone()),
                county: None,
            };
            let base = interstate::view(root, state, &query)?;
            let dates: Vec<String> = base["series"]
                .as_array()
                .context("Missing state series")?
                .iter()
                .filter_map(|r| r["date_2026"].as_str().map(str::to_owned))
                .collect();
            let mut responses = BTreeMap::new();
            for date in &dates {
                precinct_dates.insert(date.clone());
                let mut value = base.clone();
                interstate::select_date(&mut value, date.parse()?, None)?;
                let selected = value["counties"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|row| {
                        (
                            row["id"].as_str().unwrap().to_owned(),
                            row["selected"].clone(),
                        )
                    })
                    .collect::<BTreeMap<_, _>>();
                responses.insert(date.clone(), json!({"date":value["date"],"points":value["points"],"fit":value["fit"],"selected":selected}));
            }
            let file = p.store(&json!({"base":base,"selections":responses}))?;
            state_descriptor.insert(
                format!("{method}/{classification}/{metric}"),
                json!({"file":file,"dates":dates,"default":base["date"]}),
            );
        }
    }
    p.states
        .insert(state.to_owned(), Value::Object(state_descriptor));
    export_precincts(root, state, &data, &precinct_dates, p)?;
    Ok(())
}
fn export_precincts(
    root: &Path,
    state: &str,
    data: &interstate::Dataset,
    dates: &std::collections::BTreeSet<String>,
    p: &mut Publisher<'_>,
) -> Result<()> {
    let dir = root.join(format!("../sources/multistate/{state}"));
    let shared_path = dir.join("precinct-daily.json");
    let shared: Vec<interstate::Observation> = if shared_path.exists() {
        let file: Value = serde_json::from_slice(&std::fs::read(shared_path)?)?;
        serde_json::from_value(file["observations"].clone()).unwrap_or_default()
    } else {
        data.observations
            .iter()
            .filter(|o| o.precinct.is_some())
            .cloned()
            .collect()
    };
    let mut grouped = BTreeMap::<String, Vec<interstate::Observation>>::new();
    for row in shared {
        grouped.entry(row.county.clone()).or_default().push(row);
    }
    for county in &data.counties {
        let Some(id) = county["id"].as_str() else {
            continue;
        };
        let shard = dir.join(format!("precincts/{id}.json"));
        let observations = if shard.exists() {
            let file: Value = serde_json::from_slice(&std::fs::read(shard)?)?;
            serde_json::from_value(file["observations"].clone())?
        } else {
            grouped.remove(id).unwrap_or_default()
        };
        let mut responses = BTreeMap::new();
        for date in dates {
            for method in ["in_person", "mail", "total"] {
                for measure in ["daily", "cumulative"] {
                    let query = interstate::PrecinctQuery {
                        county: id.into(),
                        date: Some(date.parse()?),
                        method: Some(method.into()),
                        measure: Some(measure.into()),
                    };
                    responses.insert(
                        format!("{date}/{method}/{measure}"),
                        interstate::precincts_from(data, &observations, &query)?,
                    );
                }
            }
        }
        if !responses.is_empty() {
            let file = p.store(&responses)?;
            p.precincts.insert(format!("{state}/{id}"), file);
        }
    }
    Ok(())
}
fn copy_static(root: &Path, out: &Path) -> Result<()> {
    fn copy_dir(from: &Path, to: &Path) -> Result<()> {
        std::fs::create_dir_all(to)?;
        for item in std::fs::read_dir(from)? {
            let item = item?;
            if item.file_type()?.is_dir() {
                copy_dir(&item.path(), &to.join(item.file_name()))?;
            } else {
                std::fs::copy(item.path(), to.join(item.file_name()))?;
            }
        }
        Ok(())
    }
    copy_dir(&root.join("static"), out)?;
    // The live server aliases the Leaflet files; preserve those aliases on Pages.
    std::fs::copy(
        root.join("static/vendor/leaflet/leaflet.js"),
        out.join("vendor/leaflet.js"),
    )?;
    std::fs::copy(
        root.join("static/vendor/leaflet/leaflet.css"),
        out.join("vendor/leaflet.css"),
    )?;
    if root.join("static/vendor/leaflet/images").exists() {
        copy_dir(
            &root.join("static/vendor/leaflet/images"),
            &out.join("vendor/images"),
        )?;
    }
    let mut html = std::fs::read_to_string(out.join("index.html"))?;
    html = html
        .replace("href=\"/", "href=\"./")
        .replace("src=\"/", "src=\"./");
    html = html.replace(
        "<script src=\"./vendor/leaflet.js\"",
        "<script src=\"./pages-api.js\"></script><script src=\"./vendor/leaflet.js\"",
    );
    std::fs::write(out.join("index.html"), html)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn gzip_roundtrip_and_reused_artifacts_have_stable_accounting() {
        use std::io::Read;
        let dir = std::env::temp_dir().join(format!(
            "turnout-pages-unit-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap()
        ));
        std::fs::create_dir_all(dir.join("api-data")).unwrap();
        let value = json!({"votes":0,"missing":null});
        let mut publisher = Publisher {
            out: &dir,
            routes: BTreeMap::new(),
            states: BTreeMap::new(),
            precincts: BTreeMap::new(),
            artifacts: 0,
            bytes: 0,
            seen: BTreeSet::new(),
        };
        let file = publisher.store(&value).unwrap();
        publisher.store(&value).unwrap();
        assert_eq!(publisher.artifacts, 1);
        let bytes = publisher.bytes;
        let mut decoded = String::new();
        flate2::read::GzDecoder::new(std::fs::File::open(dir.join(&file)).unwrap())
            .read_to_string(&mut decoded)
            .unwrap();
        assert_eq!(serde_json::from_str::<Value>(&decoded).unwrap(), value);
        publisher.seen.clear();
        publisher.bytes = 0;
        publisher.artifacts = 0;
        publisher.store(&value).unwrap();
        assert_eq!(publisher.bytes, bytes);
        assert_eq!(publisher.artifacts, 1);
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn every_supported_texas_county_requires_its_map() {
        use std::io::Read;
        let dir = std::env::temp_dir().join(format!(
            "turnout-pages-map-unit-{}-{}",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap()
        ));
        std::fs::create_dir_all(dir.join("data/maps")).unwrap();
        std::fs::create_dir_all(dir.join("api-data")).unwrap();
        let map = json!({"type":"FeatureCollection","features":[],"county":"tarrant"});
        std::fs::write(
            dir.join("data/maps/tarrant.geojson"),
            serde_json::to_vec(&map).unwrap(),
        )
        .unwrap();
        let mut publisher = Publisher {
            out: &dir,
            routes: BTreeMap::new(),
            states: BTreeMap::new(),
            precincts: BTreeMap::new(),
            artifacts: 0,
            bytes: 0,
            seen: BTreeSet::new(),
        };
        // Exercise the public export boundary: absent geometry aborts before
        // unrelated analytical inputs are needed or a manifest is published.
        let snapshot = json!({"schema_version":1,"generated_at":"test","through":"2026-10-19","days":1,"geography":"test","counties":[{"id":"travis","name":"Travis","status":"unavailable","checked_at":"","error":null,"periods":[],"sources":[]}]});
        let references = json!([{"id":"travis","name":"Travis","state_id":227,"groups":[],"exact_pairs":[],"presidential":{},"references":{}}]);
        std::fs::write(
            dir.join("data/latest.json"),
            serde_json::to_vec(&snapshot).unwrap(),
        )
        .unwrap();
        std::fs::write(
            dir.join("data/reference.json"),
            serde_json::to_vec(&references).unwrap(),
        )
        .unwrap();
        let error = build(&dir, &dir.join("site")).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("Required Texas precinct map unavailable for travis")
        );
        assert!(!dir.join("site/api-manifest.json").exists());
        let error = publish_texas_maps(&dir, ["tarrant", "travis"], &mut publisher).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("Required Texas precinct map unavailable for travis")
        );
        assert!(!publisher.routes.contains_key("/api/map/travis"));
        assert!(!dir.join("api-manifest.json").exists());
        std::fs::write(
            dir.join("data/maps/travis.geojson"),
            br#"{"type":"FeatureCollection","features":[],"county":"travis"}"#,
        )
        .unwrap();
        publish_texas_maps(&dir, ["tarrant", "travis"], &mut publisher).unwrap();
        assert_eq!(publisher.routes.len(), 2);
        assert!(publisher.routes.contains_key("/api/map/travis"));
        let mut decoded = String::new();
        flate2::read::GzDecoder::new(
            std::fs::File::open(dir.join(&publisher.routes["/api/map/tarrant"])).unwrap(),
        )
        .read_to_string(&mut decoded)
        .unwrap();
        assert_eq!(serde_json::from_str::<Value>(&decoded).unwrap(), map);
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn canonical_queries_ignore_parameter_order() {
        assert_eq!(
            key("/api/trends", &[("view", "partisan"), ("county", "all")]),
            "/api/trends?county=all&view=partisan"
        );
    }
    #[test]
    fn selected_date_recomputes_points_without_changing_full_calendar() {
        let mut value = json!({"classification":"demographic","metric":"x","series":[{"date_2026":"2026-10-20"},{"date_2026":"2026-10-21"}],"counties":[{"id":"a","name":"A","harris_share":60,"demographics":{"x":70},"series":[{"date_2026":"2026-10-20","cumulative_2024":10,"cumulative_2026":12},{"date_2026":"2026-10-21","cumulative_2024":null,"cumulative_2026":null}]}]});
        interstate::select_date(&mut value, "2026-10-20".parse().unwrap(), None).unwrap();
        assert_eq!(value["points"][0]["y"], 120.0);
        interstate::select_date(&mut value, "2026-10-21".parse().unwrap(), None).unwrap();
        assert_eq!(value["points"], json!([]));
        assert_eq!(value["counties"][0]["series"].as_array().unwrap().len(), 2);
    }
}
