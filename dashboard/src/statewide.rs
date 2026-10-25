//! Official county aggregate in-person summaries, independent of precinct cohorts.
//! Downloads never use a voter-detail endpoint. Only public aggregate reports are cached.
use anyhow::{Context, Result, bail, ensure};
use base64::Engine;
use chrono::{Datelike, Duration, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    sync::Arc,
};

const CURRENT: &str = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile";
const HISTORICAL: &str = "https://earlyvoting.texas-election.com/Elections/getEVDetails.do";
const SCOPE: &str = "Official Texas SOS aggregate in-person summaries. County ordinary-precinct series may have narrower categories and different totals. Current native daily zeros are unconfirmed and remain unavailable; native values are preserved in aggregate caches.";

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Day {
    #[serde(default)]
    pub coverage: serde_json::Value,
    pub day: u32,
    pub date_2024: NaiveDate,
    pub date_2026: NaiveDate,
    pub votes_2024: Option<u64>,
    pub votes_2026: Option<u64>,
    pub cumulative_2024: Option<u64>,
    pub cumulative_2026: Option<u64>,
    pub registered_2024: Option<u64>,
    pub registered_2026: Option<u64>,
    pub status_2024: String,
    pub status_2026: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct County {
    pub id: String,
    pub name: String,
    pub state_id: u32,
    pub days: Vec<Day>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Source {
    pub year: i32,
    pub date: NaiveDate,
    pub url: String,
    pub method: String,
    pub form: Option<BTreeMap<String, String>>,
    pub retrieved_at: String,
    pub sha256: String,
    pub transport_sha256: String,
    pub rows: usize,
    pub source_updated: Option<String>,
    pub status: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SourceError {
    pub year: i32,
    pub date: NaiveDate,
    pub url: String,
    pub error: String,
    pub retained_cache: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Data {
    pub schema_version: u32,
    pub generated_at: String,
    pub through: NaiveDate,
    pub counties: Vec<County>,
    pub sources: Vec<Source>,
    pub errors: Vec<SourceError>,
    pub scope: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Aggregate {
    state_id: u32,
    name: String,
    registered: Option<u64>,
    votes: Option<u64>,
    cumulative: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Cache {
    schema_version: u32,
    year: i32,
    date: NaiveDate,
    rows: Vec<Aggregate>,
    source: Source,
}

fn start(year: i32) -> NaiveDate {
    NaiveDate::from_ymd_opt(year, 10, if year == 2024 { 21 } else { 19 }).unwrap()
}

fn atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension(format!(
        "{}.tmp",
        path.extension().unwrap_or_default().to_string_lossy()
    ));
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(tmp, path)?;
    Ok(())
}

fn count(text: &str) -> Result<Option<u64>> {
    let text = text.trim();
    if matches!(text, "" | "-" | "—" | "N/A" | "NA") {
        return Ok(None);
    }
    let clean = text.replace(',', "");
    ensure!(
        clean.bytes().all(|byte| byte.is_ascii_digit()),
        "invalid aggregate count"
    );
    Ok(Some(clean.parse()?))
}

fn json_count(value: Option<&Value>) -> Result<Option<u64>> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(number)) => {
            Ok(Some(number.as_u64().context("invalid aggregate integer")?))
        }
        Some(Value::String(text)) => count(text),
        _ => bail!("invalid aggregate count type"),
    }
}

fn current_rows(body: &[u8], date: NaiveDate) -> Result<(Vec<Aggregate>, Vec<u8>, Option<String>)> {
    ensure!(
        !body.is_empty(),
        "official statewide summary not posted for {date}"
    );
    let envelope: Value = serde_json::from_slice(body).context("statewide envelope is not JSON")?;
    let upload = envelope["upload"]
        .as_str()
        .context("statewide envelope has no upload")?;
    let raw = base64::engine::general_purpose::STANDARD
        .decode(upload.rsplit(',').next().unwrap_or(upload))
        .context("decode aggregate JSON")?;
    let native: Value = serde_json::from_slice(&raw).context("statewide upload is not JSON")?;
    ensure!(
        native["election_id"].as_u64() == Some(53815),
        "wrong statewide election"
    );
    ensure!(
        native["early_voting_date"].as_str() == Some(&date.to_string()),
        "wrong statewide date"
    );
    let rows = native["turnout_by_county"]
        .as_array()
        .context("no county aggregate rows")?
        .iter()
        .map(|row| -> Result<_> {
            // Validate the aggregate schema before retaining the decoded response.
            let fields = row
                .as_object()
                .context("county aggregate is not an object")?;
            ensure!(
                fields.keys().all(|key| matches!(
                    key.as_str(),
                    "name"
                        | "id"
                        | "registered_voters"
                        | "in_person_votes_on_date"
                        | "total_in_person_votes_for_election"
                        | "total_mail_votes_for_election"
                        | "voter_details_report"
                )),
                "unexpected nonaggregate field"
            );
            Ok(Aggregate {
                state_id: row["id"]
                    .as_u64()
                    .context("no county state ID")?
                    .try_into()?,
                name: row["name"].as_str().context("no county name")?.to_string(),
                registered: json_count(row.get("registered_voters"))?,
                votes: json_count(row.get("in_person_votes_on_date"))?,
                cumulative: json_count(row.get("total_in_person_votes_for_election"))?,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    Ok((
        rows,
        raw,
        native["date_updated"].as_str().map(str::to_string),
    ))
}

fn text(fragment: &str) -> String {
    let mut output = String::new();
    let mut inside = false;
    for character in fragment.chars() {
        match character {
            '<' => {
                inside = true;
                output.push(' ');
            }
            '>' => {
                inside = false;
                output.push(' ');
            }
            _ if !inside => output.push(character),
            _ => {}
        }
    }
    output
        .replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn cells(row: &str) -> Result<Vec<String>> {
    let lower = row.to_ascii_lowercase();
    let mut position = 0;
    let mut values = Vec::new();
    while position < row.len() {
        let th = lower[position..].find("<th").map(|i| position + i);
        let td = lower[position..].find("<td").map(|i| position + i);
        let Some(begin) = th.into_iter().chain(td).min() else {
            break;
        };
        let tag = &lower[begin + 1..begin + 3];
        let content = begin
            + lower[begin..]
                .find('>')
                .context("malformed aggregate cell")?
            + 1;
        let end = content
            + lower[content..]
                .find(&format!("</{tag}>"))
                .context("unclosed aggregate cell")?;
        values.push(text(&row[content..end]));
        position = end + 5;
    }
    Ok(values)
}

fn historical_rows(body: &[u8], date: NaiveDate) -> Result<Vec<Aggregate>> {
    let html = std::str::from_utf8(body).context("historical aggregate is not UTF-8")?;
    let lower = html.to_ascii_lowercase();
    let mut rows = Vec::new();
    let mut position = 0;
    let mut header = false;
    let mut totals = None;
    while let Some(offset) = lower[position..].find("<tr") {
        let begin = position + offset;
        let end = begin
            + lower[begin..]
                .find("</tr>")
                .context("unclosed aggregate row")?;
        let row = &html[begin..end];
        let values = cells(row)?;
        if values.first().is_some_and(|value| value == "County") {
            ensure!(
                values.get(1).is_some_and(|v| v == "Registered Voters")
                    && values.get(2).is_some_and(
                        |v| v == &format!("# In Person On {}", date.format("%m/%d/%Y"))
                    )
                    && values
                        .get(3)
                        .is_some_and(|v| v == "Cumulative In-Person Voters"),
                "historical summary date/columns mismatch"
            );
            header = true;
        } else if let Some(id_start) = row.find("downloadReport('") {
            ensure!(
                header && values.len() >= 4,
                "historical aggregate row has no validated header"
            );
            let id_start = id_start + "downloadReport('".len();
            let id_end = id_start
                + row[id_start..]
                    .find('\'')
                    .context("malformed county report ID")?;
            rows.push(Aggregate {
                state_id: row[id_start..id_end].parse()?,
                name: values[0].clone(),
                registered: count(&values[1])?,
                votes: count(&values[2])?,
                cumulative: count(&values[3])?,
            });
        } else if values.first().is_some_and(|value| value == "TOTAL") {
            ensure!(values.len() >= 4, "historical total has too few columns");
            totals = Some((count(&values[1])?, count(&values[2])?, count(&values[3])?));
        }
        position = end + 5;
    }
    ensure!(
        header && !rows.is_empty(),
        "no historical county aggregate table"
    );
    let totals = totals.context("historical aggregate has no state total")?;
    for (expected, index) in [(totals.0, 0), (totals.1, 1), (totals.2, 2)] {
        let actual = rows
            .iter()
            .map(|row| [row.registered, row.votes, row.cumulative][index].unwrap_or(0))
            .sum::<u64>();
        ensure!(
            expected == Some(actual),
            "historical county rows do not equal published state total"
        );
    }
    Ok(rows)
}

fn validate(cache: &Cache, year: i32, date: NaiveDate) -> Result<()> {
    ensure!(
        cache.schema_version == 1 && cache.year == year && cache.date == date,
        "aggregate cache identity mismatch"
    );
    ensure!(
        date.year() == year && cache.source.year == year && cache.source.date == date,
        "aggregate source identity mismatch"
    );
    let ids: BTreeSet<_> = cache.rows.iter().map(|row| row.state_id).collect();
    ensure!(
        cache.rows.len() == 254 && ids == (1..=254).collect(),
        "aggregate must contain all 254 unique counties"
    );
    for row in &cache.rows {
        ensure!(!row.name.trim().is_empty(), "blank aggregate county name");
        if let (Some(daily), Some(cumulative)) = (row.votes, row.cumulative) {
            ensure!(
                daily <= cumulative,
                "aggregate daily exceeds cumulative count"
            );
        }
    }
    Ok(())
}

fn cache_path(root: &Path, year: i32, date: NaiveDate) -> PathBuf {
    root.join(format!("data/statewide-cache/{year}/{date}.json"))
}

fn response_path(root: &Path, cache: &Cache) -> PathBuf {
    root.join(format!(
        "data/statewide-cache/{}/{}.{}.response.{}",
        cache.year,
        cache.date,
        cache.source.sha256,
        if cache.year == 2026 { "json" } else { "html" }
    ))
}

fn persist_cache(root: &Path, cache: &Cache, raw: &[u8]) -> Result<()> {
    ensure!(
        cache.source.sha256 == format!("{:x}", Sha256::digest(raw)),
        "aggregate response hash mismatch"
    );
    // Save immutable source bytes first. A failed cache replacement leaves the prior
    // cache and its source evidence intact, including across subsequent revisions.
    let response = response_path(root, cache);
    if !response.exists() {
        atomic(&response, raw)?;
    }
    atomic(
        &cache_path(root, cache.year, cache.date),
        &serde_json::to_vec(cache)?,
    )
}

fn read_cache(root: &Path, year: i32, date: NaiveDate) -> Result<Cache> {
    let cache: Cache = serde_json::from_slice(&std::fs::read(cache_path(root, year, date))?)?;
    validate(&cache, year, date)?;
    Ok(cache)
}

fn request(year: i32, date: NaiveDate) -> (String, Option<BTreeMap<String, String>>) {
    if year == 2026 {
        (
            format!(
                "{CURRENT}?type=EVR_EARLYVOTING&electionId=53815&electionDate={}",
                date.format("%m/%d/%Y")
            ),
            None,
        )
    } else {
        (
            HISTORICAL.into(),
            Some(BTreeMap::from([
                ("idElection".into(), "49664".into()),
                ("selectedDate".into(), format!("{date} 00:00:00.0")),
                ("pollPlaceIdtown".into(), String::new()),
                ("electionDate".into(), ",".into()),
            ])),
        )
    }
}

async fn collect_one(
    client: &reqwest::Client,
    root: &Path,
    year: i32,
    date: NaiveDate,
    url: String,
    form: Option<BTreeMap<String, String>>,
) -> (Option<Cache>, Option<SourceError>) {
    let previous = read_cache(root, year, date).ok();
    if year == 2024 && previous.is_some() {
        return (previous, None);
    }
    let fetched = async {
        let transport = crate::fetch::download(client, &url, form.as_ref()).await?;
        let (rows, raw, updated) = if year == 2026 {
            current_rows(&transport, date)?
        } else {
            (historical_rows(&transport, date)?, transport.clone(), None)
        };
        let source = Source {
            year,
            date,
            url: url.clone(),
            method: if form.is_some() { "POST" } else { "GET" }.into(),
            form,
            retrieved_at: Utc::now().to_rfc3339(),
            sha256: format!("{:x}", Sha256::digest(&raw)),
            transport_sha256: format!("{:x}", Sha256::digest(&transport)),
            rows: rows.len(),
            source_updated: updated,
            status: "current".into(),
        };
        let cache = Cache {
            schema_version: 1,
            year,
            date,
            rows,
            source,
        };
        validate(&cache, year, date)?;
        persist_cache(root, &cache, &raw)?;
        Ok::<_, anyhow::Error>(cache)
    }
    .await;
    match fetched {
        Ok(cache) => (Some(cache), None),
        Err(error) => {
            let failure = SourceError {
                year,
                date,
                url,
                error: format!("{error:#}"),
                retained_cache: previous.is_some(),
            };
            let previous = previous.map(|mut cache| {
                cache.source.status = "cached_after_error".into();
                cache
            });
            (previous, Some(failure))
        }
    }
}

fn fields(
    row: Option<&Aggregate>,
    future: bool,
    current: bool,
) -> (Option<u64>, Option<u64>, Option<u64>, String) {
    if future {
        return (None, None, None, "future".into());
    }
    let Some(row) = row else {
        return (None, None, None, "unavailable".into());
    };
    if current && row.votes == Some(0) {
        // No per-county reporting flag exists. Preserve known positive cumulative independently.
        return (
            None,
            row.cumulative.filter(|value| *value > 0),
            row.registered,
            "zero_unconfirmed".into(),
        );
    }
    (
        row.votes,
        row.cumulative,
        row.registered,
        if row.votes.is_some() && row.cumulative.is_some() {
            "reported"
        } else {
            "partial"
        }
        .into(),
    )
}

fn county_name(name: &str) -> String {
    match name {
        "MCLENNAN" => "McLennan".into(),
        "MCMULLEN" => "McMullen".into(),
        "DEWITT" => "DeWitt".into(),
        _ => name
            .split_whitespace()
            .map(|word| {
                let mut chars = word.chars();
                chars
                    .next()
                    .map(|c| c.to_uppercase().to_string() + &chars.as_str().to_lowercase())
                    .unwrap_or_default()
            })
            .collect::<Vec<_>>()
            .join(" "),
    }
}

fn assemble(caches: &[Cache], through: NaiveDate, errors: Vec<SourceError>) -> Result<Data> {
    let mut identities = BTreeMap::new();
    let mut lookup = BTreeMap::new();
    for cache in caches {
        for row in &cache.rows {
            identities.insert(row.state_id, row.name.clone());
            lookup.insert((cache.year, cache.date, row.state_id), row);
        }
    }
    ensure!(
        identities.len() == 254,
        "no complete official county identity source; last statewide file preserved"
    );
    let counties = identities
        .into_iter()
        .map(|(state_id, name)| {
            let id = name
                .chars()
                .filter(|c| c.is_ascii_alphanumeric())
                .flat_map(char::to_lowercase)
                .collect();
            let days = (0..12)
                .map(|index| {
                    let date_2024 = start(2024) + Duration::days(index);
                    let date_2026 = start(2026) + Duration::days(index);
                    let old = lookup.get(&(2024, date_2024, state_id)).copied();
                    let current = lookup.get(&(2026, date_2026, state_id)).copied();
                    let (votes_2024, cumulative_2024, registered_2024, status_2024) =
                        fields(old, false, false);
                    let (votes_2026, cumulative_2026, registered_2026, status_2026) =
                        fields(current, date_2026 > through, true);
                    Day {
                        coverage: serde_json::Value::Null,
                        day: index as u32 + 1,
                        date_2024,
                        date_2026,
                        votes_2024,
                        votes_2026,
                        cumulative_2024,
                        cumulative_2026,
                        registered_2024,
                        registered_2026,
                        status_2024,
                        status_2026,
                    }
                })
                .collect();
            County {
                id,
                name: county_name(&name),
                state_id,
                days,
            }
        })
        .collect();
    Ok(Data {
        schema_version: 1,
        generated_at: Utc::now().to_rfc3339(),
        through,
        counties,
        sources: caches.iter().map(|cache| cache.source.clone()).collect(),
        errors,
        scope: SCOPE.into(),
    })
}

/// Refresh official aggregate series, retaining each failed source's last-good cache.
/// `root` is the dashboard directory. All twelve historical dates are collected;
/// current dates after `through` remain null even if a cache file exists.
pub async fn refresh(client: &reqwest::Client, root: &Path, through: NaiveDate) -> Result<Data> {
    ensure!(
        through.year() == 2026,
        "statewide refresh requires a 2026 cutoff"
    );
    let semaphore = Arc::new(tokio::sync::Semaphore::new(3));
    let mut jobs = tokio::task::JoinSet::new();
    for year in [2024, 2026] {
        for index in 0..12 {
            let date = start(year) + Duration::days(index);
            if year == 2026 && date > through {
                continue;
            }
            let (url, form) = request(year, date);
            let client = client.clone();
            let root = root.to_path_buf();
            let semaphore = semaphore.clone();
            jobs.spawn(async move {
                let _permit = semaphore.acquire_owned().await.unwrap();
                collect_one(&client, &root, year, date, url, form).await
            });
        }
    }
    let mut caches = Vec::new();
    let mut errors = Vec::new();
    while let Some(result) = jobs.join_next().await {
        let (cache, error) = result.context("aggregate refresh task failed")?;
        caches.extend(cache);
        errors.extend(error);
    }
    caches.sort_by_key(|cache| (cache.year, cache.date));
    errors.sort_by_key(|error| (error.year, error.date));
    let data = assemble(&caches, through, errors)?;
    atomic(
        &root.join("data/statewide.json"),
        &serde_json::to_vec(&data)?,
    )?;
    Ok(data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn date() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 10, 23).unwrap()
    }

    fn cache(year: i32, date: NaiveDate) -> Cache {
        Cache {
            schema_version: 1,
            year,
            date,
            rows: (1..=254)
                .map(|state_id| Aggregate {
                    state_id,
                    name: format!("COUNTY {state_id}"),
                    registered: Some(100),
                    votes: Some(5),
                    cumulative: Some(20),
                })
                .collect(),
            source: Source {
                year,
                date,
                url: String::new(),
                method: "GET".into(),
                form: None,
                retrieved_at: String::new(),
                sha256: String::new(),
                transport_sha256: String::new(),
                rows: 254,
                source_updated: None,
                status: "current".into(),
            },
        }
    }

    #[test]
    fn calendar_preserves_future_baseline_and_unpaired_county_rows() {
        let data = assemble(
            &[
                cache(2024, start(2024) + Duration::days(11)),
                cache(2026, date()),
            ],
            date(),
            vec![],
        )
        .unwrap();
        assert_eq!(data.counties.len(), 254);
        let county = &data.counties[0];
        assert_eq!(county.days.len(), 12);
        assert_eq!(
            county.days[11].date_2024,
            NaiveDate::from_ymd_opt(2024, 11, 1).unwrap()
        );
        assert_eq!(
            county.days[11].date_2026,
            NaiveDate::from_ymd_opt(2026, 10, 30).unwrap()
        );
        assert_eq!(county.days[11].cumulative_2024, Some(20));
        assert_eq!(county.days[11].votes_2026, None);
        assert_eq!(county.days[11].status_2026, "future");
        assert_eq!(county.days[4].votes_2026, Some(5));
        assert_eq!(county.days[4].votes_2024, None);
        assert_eq!(county.days[4].status_2024, "unavailable");
    }

    #[test]
    fn ambiguous_current_zero_keeps_known_cumulative_and_historical_zero() {
        let row = Aggregate {
            state_id: 1,
            name: "A".into(),
            registered: Some(20),
            votes: Some(0),
            cumulative: Some(12),
        };
        let fields = super::fields(Some(&row), false, true);
        assert_eq!(
            (fields.0, fields.1, fields.2, fields.3.as_str()),
            (None, Some(12), Some(20), "zero_unconfirmed")
        );
        assert_eq!(super::fields(Some(&row), false, false).0, Some(0));
        assert_eq!(super::fields(Some(&row), true, true).1, None);
        assert_eq!(super::fields(None, false, true).3, "unavailable");
    }

    #[test]
    fn current_summary_decodes_native_counts_and_rejects_wrong_identity() {
        let native = json!({"election_id":53815,"early_voting_date":"2026-10-23","date_updated":"2026-10-24",
            "turnout_by_county":[{"id":1,"name":"ANDERSON","registered_voters":100,
                "in_person_votes_on_date":"1,234","total_in_person_votes_for_election":2000}]});
        let bytes = serde_json::to_vec(&json!({"upload": base64::engine::general_purpose::STANDARD.encode(native.to_string())})).unwrap();
        let (rows, _, updated) = current_rows(&bytes, date()).unwrap();
        assert_eq!(rows[0].votes, Some(1234));
        assert_eq!(updated.as_deref(), Some("2026-10-24"));
        assert!(current_rows(&bytes, date() - Duration::days(1)).is_err());
        assert!(current_rows(b"", date()).is_err());
        assert_eq!(json_count(Some(&Value::Null)).unwrap(), None);
        assert!(count("-1").is_err());
    }

    #[test]
    fn historical_parser_checks_columns_native_ids_and_state_reconciliation() {
        let html = b"<table><tr><th>County</th><th>Registered Voters</th><th># In Person On 10/21/2024</th><th>Cumulative In-Person Voters</th></tr><tr><th>EL PASO</th><td>1,000</td><td>12</td><td>14</td><td><a onclick=\"downloadReport('71');\">Click Here</a></td></tr><tr><th>TOTAL</th><td>1,000</td><td>12</td><td>14</td></tr></table>";
        let rows = historical_rows(html, start(2024)).unwrap();
        assert_eq!(rows[0].state_id, 71);
        assert_eq!(rows[0].registered, Some(1000));
        assert_eq!(rows[0].votes, Some(12));
        assert_eq!(rows[0].cumulative, Some(14));
        assert!(historical_rows(html, start(2024) + Duration::days(1)).is_err());
        let broken = String::from_utf8_lossy(html).replace(
            "<th>TOTAL</th><td>1,000</td><td>12",
            "<th>TOTAL</th><td>1,000</td><td>13",
        );
        assert!(historical_rows(broken.as_bytes(), start(2024)).is_err());
    }

    #[test]
    fn incomplete_duplicate_or_mismatched_caches_cannot_replace_good_data() {
        let mut data = cache(2026, date());
        validate(&data, 2026, date()).unwrap();
        data.rows[1].state_id = 1;
        assert!(validate(&data, 2026, date()).is_err());
        data.rows[1].state_id = 2;
        data.rows.pop();
        assert!(validate(&data, 2026, date()).is_err());
        assert!(assemble(&[], date(), vec![]).is_err());
    }

    #[tokio::test]
    async fn failed_source_retains_its_last_good_aggregate_and_preserves_disk_cache() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let root = std::env::temp_dir().join(format!(
            "statewide-cache-test-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        let original = serde_json::to_vec(&cache(2026, date())).unwrap();
        let path = cache_path(&root, 2026, date());
        atomic(&path, &original).unwrap();
        let server = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", server.local_addr().unwrap());
        let task = tokio::spawn(async move {
            let (mut stream, _) = server.accept().await.unwrap();
            let mut request = [0; 2048];
            let received = stream.read(&mut request).await.unwrap();
            assert!(received > 0);
            stream
                .write_all(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .await
                .unwrap();
        });
        let (retained, error) =
            collect_one(&reqwest::Client::new(), &root, 2026, date(), url, None).await;
        assert_eq!(retained.unwrap().source.status, "cached_after_error");
        assert!(error.unwrap().retained_cache);
        assert_eq!(std::fs::read(&path).unwrap(), original);
        task.await.unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn aggregate_revisions_keep_both_content_addressed_sources() {
        let root = std::env::temp_dir().join(format!(
            "statewide-source-test-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        let mut first = cache(2026, date());
        first.source.sha256 = format!("{:x}", Sha256::digest(b"first aggregate"));
        persist_cache(&root, &first, b"first aggregate").unwrap();
        let mut second = first.clone();
        second.source.sha256 = format!("{:x}", Sha256::digest(b"revised aggregate"));
        second.rows[0].votes = Some(6);
        persist_cache(&root, &second, b"revised aggregate").unwrap();
        assert_eq!(
            std::fs::read(response_path(&root, &first)).unwrap(),
            b"first aggregate"
        );
        assert_eq!(
            std::fs::read(response_path(&root, &second)).unwrap(),
            b"revised aggregate"
        );
        assert_eq!(
            read_cache(&root, 2026, date()).unwrap().source.sha256,
            second.source.sha256
        );
        assert!(persist_cache(&root, &second, b"bad hash").is_err());
        assert_eq!(
            read_cache(&root, 2026, date()).unwrap().source.sha256,
            second.source.sha256
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
