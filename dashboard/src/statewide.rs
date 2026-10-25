//! Official county aggregate mail and in-person summaries, independent of precinct cohorts.
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
const SCOPE: &str = "Official Texas SOS and independently corroborated county aggregates. Mail means the source's reported returned-mail voters, not ballots issued or requested. Combined turnout adds reported mail and early in-person votes for the same county and date in both cycles. Native cumulative totals include mail received before early in-person voting opened. Daily mail is the nonnegative change from the preceding calendar day's cumulative report; missing prior reports and downward revisions remain unavailable. County ordinary-precinct series may have narrower categories and different totals. Current native mail zeros are unconfirmed. Current native zero daily in-person reports cannot certify that date's cumulative total: the feed can repeat the prior day's total. Unconfirmed values remain unavailable unless independently corroborated; other dates and methods remain usable.";

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct MethodValues {
    pub votes_2024: Option<u64>,
    pub votes_2026: Option<u64>,
    pub cumulative_2024: Option<u64>,
    pub cumulative_2026: Option<u64>,
}

fn legacy_method() -> String {
    "in_person".into()
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Day {
    #[serde(default)]
    pub by_method: BTreeMap<String, MethodValues>,
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
    #[serde(default = "legacy_method")]
    pub voting_method: String,
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
    #[serde(default)]
    mail_cumulative: Option<u64>,
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
                mail_cumulative: json_count(row.get("total_mail_votes_for_election"))?,
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
            if values.len() >= 7 {
                ensure!(
                    values[5] == "Cumulative By Mail Voters"
                        && values[6] == "Cumulative In-Person And Mail Voters",
                    "historical mail summary columns mismatch"
                );
            }
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
            let mail_cumulative = values.get(5).map(|v| count(v)).transpose()?.flatten();
            if let (Some(in_person), Some(mail), Some(total)) = (
                count(&values[3])?,
                mail_cumulative,
                values.get(6).map(|v| count(v)).transpose()?.flatten(),
            ) {
                ensure!(
                    in_person.checked_add(mail) == Some(total),
                    "historical combined total mismatch"
                );
            }
            rows.push(Aggregate {
                state_id: row[id_start..id_end].parse()?,
                name: values[0].clone(),
                registered: count(&values[1])?,
                votes: count(&values[2])?,
                cumulative: count(&values[3])?,
                mail_cumulative,
            });
        } else if values.first().is_some_and(|value| value == "TOTAL") {
            ensure!(values.len() >= 4, "historical total has too few columns");
            totals = Some((
                count(&values[1])?,
                count(&values[2])?,
                count(&values[3])?,
                values.get(5).map(|v| count(v)).transpose()?.flatten(),
            ));
        }
        position = end + 5;
    }
    ensure!(
        header && !rows.is_empty(),
        "no historical county aggregate table"
    );
    let totals = totals.context("historical aggregate has no state total")?;
    if let Some(expected) = totals.3 {
        ensure!(
            rows.iter().all(|r| r.mail_cumulative.is_some()),
            "historical mail row missing"
        );
        ensure!(
            rows.iter().map(|r| r.mail_cumulative.unwrap()).sum::<u64>() == expected,
            "historical mail county rows do not equal published state total"
        );
    }

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
        matches!(cache.schema_version, 1 | 2) && cache.year == year && cache.date == date,
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

fn upgraded_cache(root: &Path, mut cache: Cache) -> Result<Cache> {
    if cache.schema_version == 2 {
        return Ok(cache);
    }
    let raw = std::fs::read(response_path(root, &cache))?;
    ensure!(
        cache.source.sha256 == format!("{:x}", Sha256::digest(&raw)),
        "aggregate source hash mismatch during mail migration"
    );
    cache.rows = if cache.year == 2024 {
        historical_rows(&raw, cache.date)?
    } else {
        let envelope = serde_json::to_vec(
            &serde_json::json!({"upload":base64::engine::general_purpose::STANDARD.encode(&raw)}),
        )?;
        current_rows(&envelope, cache.date)?.0
    };
    cache.schema_version = 2;
    validate(&cache, cache.year, cache.date)?;
    persist_cache(root, &cache, &raw)?;
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
    let previous = read_cache(root, year, date)
        .ok()
        .map(|cache| upgraded_cache(root, cache.clone()).unwrap_or(cache));
    if year == 2024
        && previous.as_ref().is_some_and(|c| {
            c.schema_version == 2 && c.rows.iter().all(|r| r.mail_cumulative.is_some())
        })
    {
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
            schema_version: 2,
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
        // The feed can copy yesterday's positive cumulative into an unreported
        // date. Neither value establishes a completed report for this date.
        return (None, None, row.registered, "zero_unconfirmed".into());
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

pub fn method_label(method: &str) -> &str {
    match method {
        "mail" => "Mail",
        "total" => "Mail + in person",
        _ => "In person",
    }
}

/// Select one method without borrowing an incomplete component from another geography.
pub fn select_method(mut data: Data, method: &str) -> Result<Data> {
    ensure!(
        ["in_person", "mail", "total"].contains(&method),
        "Unknown voting method"
    );
    let original = data.voting_method.clone();
    for county in &mut data.counties {
        for day in &mut county.days {
            if let Some(values) = day.by_method.get(method) {
                day.votes_2024 = values.votes_2024;
                day.votes_2026 = values.votes_2026;
                day.cumulative_2024 = values.cumulative_2024;
                day.cumulative_2026 = values.cumulative_2026;
            } else if original != method {
                day.votes_2024 = None;
                day.votes_2026 = None;
                day.cumulative_2024 = None;
                day.cumulative_2026 = None;
            }
            for year in [2024, 2026] {
                let (daily, cumulative, status) = if year == 2024 {
                    (day.votes_2024, day.cumulative_2024, &mut day.status_2024)
                } else {
                    (day.votes_2026, day.cumulative_2026, &mut day.status_2026)
                };
                if method != "in_person" {
                    *status = if year == 2026 && day.date_2026 > data.through {
                        "future"
                    } else if daily.is_some() && cumulative.is_some() {
                        "reported"
                    } else if daily.is_some() || cumulative.is_some() {
                        "partial"
                    } else {
                        "unavailable"
                    }
                    .into();
                }
            }
            day.coverage = serde_json::json!({"daily_scope":"county","cumulative_scope":"county","voting_method":method});
        }
    }
    data.voting_method = method.into();
    Ok(data)
}

/// Full-county in-person controls may corroborate zeros. Never mix precinct scope
/// into county mail totals: callers supply the county-only qualified data here.
pub fn with_county_in_person(mut raw: Data, county: &Data, method: &str) -> Result<Data> {
    for source in &county.sources {
        if !raw.sources.iter().any(|s| {
            s.year == source.year
                && s.date == source.date
                && s.url == source.url
                && s.sha256 == source.sha256
        }) {
            raw.sources.push(source.clone());
        }
    }
    for row in &mut raw.counties {
        let Some(person) = county.counties.iter().find(|c| c.id == row.id) else {
            continue;
        };
        for day in &mut row.days {
            let Some(p) = person.days.iter().find(|p| p.day == day.day) else {
                continue;
            };
            let mail = day.by_method.get("mail").cloned().unwrap_or_default();
            day.by_method.insert(
                "in_person".into(),
                MethodValues {
                    votes_2024: p.votes_2024,
                    votes_2026: p.votes_2026,
                    cumulative_2024: p.cumulative_2024,
                    cumulative_2026: p.cumulative_2026,
                },
            );
            day.by_method.insert(
                "total".into(),
                MethodValues {
                    votes_2024: add(p.votes_2024, mail.votes_2024),
                    votes_2026: add(p.votes_2026, mail.votes_2026),
                    cumulative_2024: add(p.cumulative_2024, mail.cumulative_2024),
                    cumulative_2026: add(p.cumulative_2026, mail.cumulative_2026),
                },
            );
        }
    }
    select_method(raw, method)
}

fn mail_values(
    row: Option<&Aggregate>,
    prior: Option<&Aggregate>,
    future: bool,
    current: bool,
) -> (Option<u64>, Option<u64>) {
    if future {
        return (None, None);
    }
    let reported = |r: &Aggregate| r.mail_cumulative.filter(|n| !current || *n > 0);
    let cumulative = row.and_then(reported);
    let daily = cumulative
        .zip(prior.and_then(reported))
        .and_then(|(now, before)| now.checked_sub(before));
    (daily, cumulative)
}

fn add(a: Option<u64>, b: Option<u64>) -> Option<u64> {
    a.zip(b).and_then(|(a, b)| a.checked_add(b))
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
                    let (mail_daily_2024, mail_cumulative_2024) = mail_values(
                        old,
                        lookup
                            .get(&(2024, date_2024 - Duration::days(1), state_id))
                            .copied(),
                        false,
                        false,
                    );
                    let (mail_daily_2026, mail_cumulative_2026) = mail_values(
                        current,
                        lookup
                            .get(&(2026, date_2026 - Duration::days(1), state_id))
                            .copied(),
                        date_2026 > through,
                        true,
                    );
                    let by_method = BTreeMap::from([
                        (
                            "in_person".into(),
                            MethodValues {
                                votes_2024,
                                votes_2026,
                                cumulative_2024,
                                cumulative_2026,
                            },
                        ),
                        (
                            "mail".into(),
                            MethodValues {
                                votes_2024: mail_daily_2024,
                                votes_2026: mail_daily_2026,
                                cumulative_2024: mail_cumulative_2024,
                                cumulative_2026: mail_cumulative_2026,
                            },
                        ),
                        (
                            "total".into(),
                            MethodValues {
                                votes_2024: add(votes_2024, mail_daily_2024),
                                votes_2026: add(votes_2026, mail_daily_2026),
                                cumulative_2024: add(cumulative_2024, mail_cumulative_2024),
                                cumulative_2026: add(cumulative_2026, mail_cumulative_2026),
                            },
                        ),
                    ]);
                    Day {
                        by_method,
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
    select_method(
        Data {
            voting_method: "in_person".into(),
            schema_version: 2,
            generated_at: Utc::now().to_rfc3339(),
            through,
            counties,
            sources: caches.iter().map(|cache| cache.source.clone()).collect(),
            errors,
            scope: SCOPE.into(),
        },
        "total",
    )
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
        // The prior calendar day is needed for opening-day mail receipts.
        for index in -1..12 {
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

fn cached(root: &Path, through: NaiveDate, migrate: bool) -> Result<Data> {
    let mut caches = Vec::new();
    let mut errors = Vec::new();
    for year in [2024, 2026] {
        for index in -1..12 {
            let date = start(year) + Duration::days(index);
            if year == 2026 && date > through {
                continue;
            }
            match read_cache(root, year, date) {
                Ok(cache) => caches.push(if migrate {
                    upgraded_cache(root, cache.clone()).unwrap_or(cache)
                } else {
                    cache
                }),
                Err(error) => errors.push(SourceError {
                    year,
                    date,
                    url: request(year, date).0,
                    error: format!("Retained aggregate unavailable: {error:#}"),
                    retained_cache: false,
                }),
            }
        }
    }
    assemble(&caches, through, errors)
}

/// Reapply current qualification to retained native counts without writing files.
/// Derived statewide snapshots may have been produced by an older application.
pub fn from_cache(root: &Path, saved: &Data) -> Result<Data> {
    let mut data = cached(root, saved.through, false)?;
    data.generated_at = saved.generated_at.clone();
    for error in &saved.errors {
        if !data
            .errors
            .iter()
            .any(|e| e.year == error.year && e.date == error.date)
        {
            data.errors.push(error.clone());
        }
    }
    Ok(data)
}

/// Rebuild using retained native aggregates without making a source request.
pub fn rebuild(root: &Path, through: NaiveDate) -> Result<Data> {
    let data = cached(root, through, true)?;
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
                    mail_cumulative: Some(3),
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
        let data = select_method(
            assemble(
                &[
                    cache(2024, start(2024) + Duration::days(11)),
                    cache(2026, date()),
                ],
                date(),
                vec![],
            )
            .unwrap(),
            "in_person",
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
    fn ambiguous_current_zero_does_not_certify_a_stale_cumulative_report() {
        let row = Aggregate {
            state_id: 1,
            name: "A".into(),
            registered: Some(20),
            votes: Some(0),
            cumulative: Some(12),
            mail_cumulative: None,
        };
        let fields = super::fields(Some(&row), false, true);
        assert_eq!(
            (fields.0, fields.1, fields.2, fields.3.as_str()),
            (None, None, Some(20), "zero_unconfirmed")
        );
        assert_eq!(super::fields(Some(&row), false, false).0, Some(0));
        assert_eq!(super::fields(Some(&row), true, true).1, None);
        assert_eq!(super::fields(None, false, true).3, "unavailable");
    }

    #[test]
    fn unconfirmed_mail_zero_is_local_to_its_date_and_method() {
        let mut caches = Vec::new();
        for year in [2024, 2026] {
            for offset in [-1, 0, 1] {
                let mut c = cache(year, start(year) + Duration::days(offset));
                c.rows[0].mail_cumulative = Some(if offset < 1 { 0 } else { 3 });
                caches.push(c);
            }
        }
        let data = assemble(&caches, start(2026) + Duration::days(1), vec![]).unwrap();
        let mail = select_method(data.clone(), "mail").unwrap();
        assert_eq!(mail.counties[0].days[0].cumulative_2024, Some(0));
        assert_eq!(mail.counties[0].days[0].votes_2024, Some(0));
        assert_eq!(mail.counties[0].days[0].cumulative_2026, None);
        assert_eq!(mail.counties[0].days[0].votes_2026, None);
        assert_eq!(mail.counties[0].days[1].cumulative_2026, Some(3));
        assert_eq!(mail.counties[0].days[1].votes_2026, None);
        assert_eq!(data.counties[0].days[0].cumulative_2026, None);
        assert_eq!(data.counties[0].days[1].cumulative_2026, Some(23));
        assert_eq!(data.counties[1].days[0].cumulative_2026, Some(23));
        let person = select_method(data, "in_person").unwrap();
        assert_eq!(person.counties[0].days[0].cumulative_2026, Some(20));
    }

    #[test]
    fn independent_dated_control_can_restore_a_native_zero_report() {
        let old = cache(2024, start(2024));
        let mut current = cache(2026, start(2026));
        current.rows[0].votes = Some(0);
        current.rows[0].cumulative = Some(12);
        let raw = assemble(&[old, current], start(2026), vec![]).unwrap();
        let controls = crate::quality::Report {
            controls: vec![crate::quality::Control {
                county: "county1".into(),
                year: 2026,
                date: start(2026),
                daily: Some(0),
                cumulative: Some(12),
                source: "independent county report".into(),
                sha256: "a".repeat(64),
                retrieved_at: String::new(),
                scope: "in_person".into(),
                completed: true,
                note: String::new(),
                precinct_total: None,
                precinct_source: None,
                precinct_sha256: None,
            }],
            ..Default::default()
        };
        let person = controls.statewide(select_method(raw.clone(), "in_person").unwrap());
        assert_eq!(person.counties[0].days[0].votes_2026, Some(0));
        assert_eq!(person.counties[0].days[0].cumulative_2026, Some(12));
        let combined = with_county_in_person(raw, &person, "total").unwrap();
        assert_eq!(combined.counties[0].days[0].cumulative_2026, Some(15));
    }

    #[test]
    fn retained_old_derivations_are_requalified_without_a_download_or_write() {
        let root = std::env::temp_dir().join(format!(
            "turnout-retained-qualification-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        let mut caches = Vec::new();
        for year in [2024, 2026] {
            for offset in [-1, 0] {
                let mut c = cache(year, start(year) + Duration::days(offset));
                c.schema_version = 2;
                c.rows[0].mail_cumulative = Some(0);
                if year == 2026 {
                    c.rows[0].votes = Some(0);
                    c.rows[0].cumulative = Some(12);
                }
                let raw = format!("anonymous retained fixture {year} {offset}").into_bytes();
                c.source.sha256 = format!("{:x}", Sha256::digest(&raw));
                persist_cache(&root, &c, &raw).unwrap();
                caches.push(c);
            }
        }
        let mut saved = assemble(&caches, start(2026), vec![]).unwrap();
        saved.generated_at = "unchanged source generation".into();
        // Simulate the values serialized by the previous application.
        let d = &mut saved.counties[0].days[0];
        d.by_method.get_mut("mail").unwrap().cumulative_2026 = Some(0);
        d.by_method.get_mut("in_person").unwrap().cumulative_2026 = Some(12);
        d.by_method.get_mut("total").unwrap().cumulative_2026 = Some(12);
        d.cumulative_2026 = Some(12);
        let path = root.join("data/statewide.json");
        let bytes = serde_json::to_vec(&saved).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        let qualified = from_cache(&root, &saved).unwrap();
        assert_eq!(qualified.generated_at, saved.generated_at);
        assert_eq!(qualified.counties[0].days[0].cumulative_2026, None);
        assert_eq!(qualified.counties[1].days[0].cumulative_2026, Some(23));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        for c in &caches {
            assert_eq!(
                read_cache(&root, c.year, c.date).unwrap().source.sha256,
                c.source.sha256
            );
            assert!(response_path(&root, c).exists());
        }
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn combined_defaults_include_preopening_mail_and_use_calendar_day_receipts() {
        let mut caches = Vec::new();
        for (year, before, now) in [(2024, 23831, 25602), (2026, 20654, 22444)] {
            let mut prior = cache(year, start(year) - Duration::days(1));
            prior.rows[0].mail_cumulative = Some(before);
            let mut current = cache(year, start(year));
            current.rows[0].mail_cumulative = Some(now);
            current.rows[0].votes = Some(if year == 2024 { 126473 } else { 104606 });
            current.rows[0].cumulative = current.rows[0].votes;
            caches.extend([prior, current]);
        }
        let combined = assemble(&caches, start(2026), vec![]).unwrap();
        assert_eq!(combined.voting_method, "total");
        let day = &combined.counties[0].days[0];
        assert_eq!(day.cumulative_2024, Some(152075));
        assert_eq!(day.cumulative_2026, Some(127050));
        assert_eq!(day.votes_2024, Some(126473 + 1771));
        assert_eq!(day.votes_2026, Some(104606 + 1790));
        let mail = select_method(combined.clone(), "mail").unwrap();
        assert_eq!(mail.counties[0].days[0].votes_2026, Some(1790));
        let person = select_method(combined, "in_person").unwrap();
        assert_eq!(person.counties[0].days[0].cumulative_2026, Some(104606));
        assert_eq!(mail.counties[0].days[1].cumulative_2026, None);
    }

    #[test]
    fn missing_or_revised_mail_does_not_become_zero_or_remove_known_cumulative() {
        let mut previous = cache(2026, start(2026));
        let mut current = cache(2026, start(2026) + Duration::days(1));
        previous.rows[0].mail_cumulative = Some(20);
        current.rows[0].mail_cumulative = Some(18);
        current.rows[1].mail_cumulative = None;
        let result = assemble(
            &[previous, current],
            start(2026) + Duration::days(1),
            vec![],
        )
        .unwrap();
        assert_eq!(result.counties[0].days[1].votes_2026, None);
        assert_eq!(result.counties[0].days[1].cumulative_2026, Some(38));
        assert_eq!(result.counties[1].days[1].cumulative_2026, None);
        assert_eq!(result.counties[0].days[0].votes_2026, None);
        assert_eq!(result.counties[0].days[0].cumulative_2026, Some(40));
        let legacy: Data = serde_json::from_value(json!({"schema_version":1,"generated_at":"old","through":"2026-10-19","counties":[{"id":"a","name":"A","state_id":1,"days":[{"day":1,"date_2024":"2024-10-21","date_2026":"2026-10-19","votes_2024":3,"votes_2026":4,"cumulative_2024":3,"cumulative_2026":4,"registered_2024":10,"registered_2026":10,"status_2024":"reported","status_2026":"reported"}]}],"sources":[],"errors":[],"scope":"legacy in person"})).unwrap();
        assert_eq!(
            select_method(legacy.clone(), "total").unwrap().counties[0].days[0].cumulative_2026,
            None
        );
        assert_eq!(
            select_method(legacy, "in_person").unwrap().counties[0].days[0].cumulative_2026,
            Some(4)
        );
    }

    #[test]
    fn historical_mail_columns_and_published_combined_totals_reconcile() {
        let html = b"<table><tr><th>County</th><th>Registered Voters</th><th># In Person On 10/21/2024</th><th>Cumulative In-Person Voters</th><th>Percent</th><th>Cumulative By Mail Voters</th><th>Cumulative In-Person And Mail Voters</th></tr><tr><th>EL PASO</th><td>1000</td><td>12</td><td>14</td><td>1.4%</td><td>6</td><td>20</td><td><a onclick=\"downloadReport('71');\">Download</a></td></tr><tr><th>TOTAL</th><td>1000</td><td>12</td><td>14</td><td>1.4%</td><td>6</td><td>20</td></tr></table>";
        assert_eq!(
            historical_rows(html, start(2024)).unwrap()[0].mail_cumulative,
            Some(6)
        );
        let wrong = String::from_utf8_lossy(html).replacen("<td>20</td>", "<td>21</td>", 1);
        assert!(historical_rows(wrong.as_bytes(), start(2024)).is_err());
        let wrong =
            String::from_utf8_lossy(html).replace("Cumulative By Mail Voters", "Ballots Issued");
        assert!(historical_rows(wrong.as_bytes(), start(2024)).is_err());
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
