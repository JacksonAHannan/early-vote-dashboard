//! County formats take precedence where they expose ordinary in-person scope.
use crate::{fetch::download, *};
use anyhow::{Context, Result, bail, ensure};
use calamine::{Data, Reader, open_workbook_auto_from_rs};
use chrono::Datelike;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io::{Cursor, Read},
};

type Voters = BTreeMap<String, (NaiveDate, String)>;
fn cell(value: &Data) -> String {
    match value {
        Data::Float(n) if n.fract() == 0.0 => format!("{n:.0}"),
        _ => value.to_string().trim().to_string(),
    }
}
fn workbook(bytes: Vec<u8>) -> Result<Vec<Vec<String>>> {
    let mut book = open_workbook_auto_from_rs(Cursor::new(bytes))?;
    let range = book.worksheet_range_at(0).context("no worksheet")??;
    Ok(range
        .rows()
        .map(|row| row.iter().map(cell).collect())
        .collect())
}
fn zip_members(bytes: Vec<u8>) -> Result<Vec<(String, Vec<u8>)>> {
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes))?;
    let mut result = Vec::new();
    for i in 0..archive.len() {
        let mut f = archive.by_index(i)?;
        if f.is_dir() {
            continue;
        }
        let name = f.name().to_string();
        let mut bytes = Vec::new();
        f.read_to_end(&mut bytes)?;
        result.push((name, bytes));
    }
    Ok(result)
}
fn header(rows: &[Vec<String>], required: &[&str]) -> Result<(usize, BTreeMap<String, usize>)> {
    for (i, row) in rows.iter().take(15).enumerate() {
        let fields: BTreeMap<_, _> = row
            .iter()
            .enumerate()
            .map(|(i, v)| (v.to_uppercase().replace('_', " ").trim().to_string(), i))
            .collect();
        if required.iter().all(|r| fields.contains_key(*r)) {
            return Ok((i, fields));
        }
    }
    bail!("county workbook headers changed")
}
fn field<'a>(row: &'a [String], headers: &BTreeMap<String, usize>, name: &str) -> &'a str {
    headers
        .get(name)
        .and_then(|i| row.get(*i))
        .map(String::as_str)
        .unwrap_or("")
}
fn date(value: &str) -> Result<NaiveDate> {
    if let Ok(serial) = value.parse::<f64>() {
        return Ok(NaiveDate::from_ymd_opt(1899, 12, 30).unwrap()
            + chrono::Duration::days(serial.floor() as i64));
    }
    for format in [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m.%d.%y",
        "%m.%d.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    ] {
        if let Ok(d) = NaiveDate::parse_from_str(value, format) {
            return Ok(d);
        }
    }
    bail!("unrecognized county vote date")
}
fn insert(
    voters: &mut Voters,
    id: &str,
    day: NaiveDate,
    precinct: &str,
    allow_later_repeat: bool,
) -> Result<()> {
    ensure!(!id.is_empty(), "blank identifier in ordinary county roster");
    let p = normalize(precinct);
    let p = if p.is_empty() { "UNASSIGNED".into() } else { p };
    if let Some((seen_day, seen_p)) = voters.get(id) {
        ensure!(
            seen_p == &p && (*seen_day == day || allow_later_repeat),
            "conflicting duplicate in county roster"
        );
        if day < *seen_day {
            voters.insert(id.to_string(), (day, p));
        }
    } else {
        voters.insert(id.to_string(), (day, p));
    }
    Ok(())
}
fn days_from(
    voters: Voters,
    reference: &Reference,
    year: i32,
    n: u32,
    source: &str,
    sha: &str,
    note: &str,
) -> Result<Vec<Daily>> {
    let mut days: BTreeMap<NaiveDate, Counts> = BTreeMap::new();
    for (day, p) in voters.values() {
        *days.entry(*day).or_default().entry(p.clone()).or_default() += 1;
    }
    let mut output = Vec::new();
    for i in 0..n {
        let day = start(year) + chrono::Duration::days(i64::from(i));
        let counts = days
            .remove(&day)
            .with_context(|| format!("county ordinary roster missing {day}"))?;
        output.push(Daily {
            complete: false,
            county: reference.id.clone(),
            date: day,
            counts,
            source: source.into(),
            sha256: sha.into(),
            retrieved_at: Utc::now().to_rfc3339(),
            note: note.into(),
            cumulative: false,
        });
    }
    Ok(output)
}
pub async fn collect(
    client: &reqwest::Client,
    r: &Reference,
    year: i32,
    n: u32,
) -> Result<Vec<Daily>> {
    match r.id.as_str() {
        "travis" => travis(client, r, year, n).await,
        "dallas" => dallas(client, r, year, n).await,
        "harris" => harris(client, r, year, n).await,
        "nueces" if year == 2026 => nueces(client, r, n).await,
        "fortbend" if crate::fort_bend::supports(year) => {
            crate::fort_bend::collect(client, r, year, n).await
        }
        "montgomery" => montgomery(client, r, year, n).await,
        "hays" if year == 2026 => hays(client, r, n).await,
        "ellis" if year == 2026 => ellis(client, r, n).await,
        _ => bail!("no county adapter"),
    }
}
pub fn has_adapter(id: &str, year: i32) -> bool {
    if id == "fortbend" && crate::fort_bend::supports(year) {
        return true;
    }
    ["travis", "dallas", "montgomery", "harris"].contains(&id)
        || (year == 2026 && ["hays", "ellis", "nueces"].contains(&id))
}
fn travis_roster_link(html: &str, page: &str, year: i32) -> Result<String> {
    let prefix = format!("g{}-voter-rosters", year % 100);
    let selected = link(html, &prefix, page)?;
    let url = reqwest::Url::parse(&selected)?;
    let filename = url
        .path_segments()
        .and_then(|mut parts| parts.next_back())
        .unwrap_or("")
        .to_lowercase();
    ensure!(
        url.scheme() == "https"
            && matches!(
                url.host_str(),
                Some("votetravis.gov" | "www.votetravis.gov")
            )
            && url.path().starts_with("/wp-content/uploads/")
            && filename.starts_with(&prefix)
            && filename.ends_with(".zip"),
        "Travis election page links an unexpected roster archive"
    );
    Ok(selected)
}

async fn travis(client: &reqwest::Client, r: &Reference, year: i32, n: u32) -> Result<Vec<Daily>> {
    let url = if year == 2026 {
        let page = "https://votetravis.gov/current-election-information/current-election/";
        let html = String::from_utf8(download(client, page, None).await?)?;
        travis_roster_link(&html, page, year)?
    } else {
        format!(
            "https://votetravis.gov/wp-content/uploads/G{}-Voter-Rosters.zip",
            year % 100
        )
    };
    let raw = download(client, &url, None).await?;
    let hash = format!("{:x}", Sha256::digest(&raw));
    let members = zip_members(raw)?;
    let mut voters = Voters::new();
    let mut found = 0;
    for i in 0..n {
        let day = start(year) + chrono::Duration::days(i64::from(i));
        let name = format!("{} Early Vote.xlsx", day.format("%m.%d.%Y"));
        let (_, bytes) = members
            .iter()
            .find(|(name2, _)| name2 == &name)
            .with_context(|| format!("Travis daily workbook not posted: {day}"))?;
        let rows = workbook(bytes.clone())?;
        let (first, headers) = header(&rows, &["VUID", "PCT"])?;
        ensure!(
            rows.iter()
                .take(first)
                .flatten()
                .any(|v| v == "Travis County Early Vote Roster"),
            "wrong Travis roster title"
        );
        ensure!(
            rows.iter()
                .take(first)
                .flatten()
                .filter_map(|v| v.parse::<f64>().ok())
                .any(|serial| date(&serial.to_string()).ok() == Some(day)),
            "Travis filename/date mismatch"
        );
        for row in rows.iter().skip(first + 1) {
            let id = field(row, &headers, "VUID");
            if id.is_empty() {
                continue;
            }
            insert(&mut voters, id, day, field(row, &headers, "PCT"), false)?;
        }
        found += 1;
    }
    ensure!(found == n, "missing Travis day");
    days_from(
        voters,
        r,
        year,
        n,
        &url,
        &hash,
        "County daily Early Vote workbooks; Limited Ballot and Ballot By Mail excluded. Completed four-day roster and vendor graph totals agree; daily rounding/revisions differ by one voter.",
    )
}
async fn montgomery(
    client: &reqwest::Client,
    r: &Reference,
    year: i32,
    n: u32,
) -> Result<Vec<Daily>> {
    let mut voters = Voters::new();
    let mut evidence = Vec::new();
    for i in 0..n {
        let day = start(year) + chrono::Duration::days(i64::from(i));
        let prefix = if year == 2026 {
            "GEN110326"
        } else {
            "GEN110524"
        };
        let url = format!(
            "https://elections.mctx.org/EVHistoryFiles/{prefix}_{}.zip",
            day.format("%m.%d.%Y")
        );
        let raw = download(client, &url, None).await?;
        let hash = format!("{:x}", Sha256::digest(&raw));
        let members = zip_members(raw)?;
        let (_, bytes) = members
            .iter()
            .find(|(name, _)| name.to_lowercase().ends_with(".csv"))
            .context("no Montgomery CSV")?;
        let mut csv = csv::ReaderBuilder::new()
            .trim(csv::Trim::All)
            .from_reader(bytes.as_slice());
        let h = csv.headers()?.clone();
        let idx = |name: &str| {
            h.iter()
                .position(|x| x.trim_start_matches('\u{feff}') == name)
                .with_context(|| format!("missing Montgomery field {name}"))
        };
        let method = idx("VoteType")?;
        let d = idx("DateVoted")?;
        let p = idx("CountyElectionPrecinct")?;
        let id = idx("VUID")?;
        for record in csv.records() {
            let row = record?;
            if &row[method] != "E" {
                continue;
            }
            ensure!(date(&row[d])? == day, "Montgomery daily date mismatch");
            insert(&mut voters, &row[id], day, &row[p], true)?;
        }
        evidence.push((day, url, hash));
    }
    let mut days = days_from(
        voters,
        r,
        year,
        n,
        "",
        "",
        "County ordinary E only; limited and mail excluded. Deduplicated VUID across jurisdictions and dates, assigning earliest appearance. Four-day 2024 unique roster 70,905; graph 70,903 (two-voter discrepancy).",
    )?;
    for (daily, (_, url, hash)) in days.iter_mut().zip(evidence) {
        daily.source = url;
        daily.sha256 = hash;
    }
    Ok(days)
}
fn link(html: &str, needle: &str, base: &str) -> Result<String> {
    let lower = html.to_lowercase();
    for start in lower.match_indices("<a ").map(|(i, _)| i) {
        let end = lower[start..]
            .find("</a>")
            .map(|n| start + n)
            .unwrap_or(html.len());
        let segment = &html[start..end];
        if !segment.to_lowercase().contains(needle) {
            continue;
        }
        if let Some(h) = segment.to_lowercase().find("href=") {
            let value = &segment[h + 5..];
            let quote = value.chars().next().unwrap_or('"');
            let value = &value[1..];
            if let Some(end) = value.find(quote) {
                return Ok(reqwest::Url::parse(base)?
                    .join(&value[..end].replace("&amp;", "&"))?
                    .to_string());
            }
        }
    }
    bail!("county roster link not found on election page")
}
async fn dallas(client: &reqwest::Client, r: &Reference, year: i32, n: u32) -> Result<Vec<Daily>> {
    let page = if year == 2026 {
        "https://www.dallascountyvotes.org/election-results/historical/november-3-2026-general-and-joint-election/"
    } else {
        "https://www.dallascountyvotes.org/election-results/historical/november-5-2024-general-joint-election/"
    };
    let html = download(client, page, None).await?;
    let html = String::from_utf8(html)?;
    let url = link(&html, "in-person early", page)?;
    let raw = download(client, &url, None).await?;
    let hash = format!("{:x}", Sha256::digest(&raw));
    let rows = workbook(raw)?;
    let (first, headers) = header(&rows, &["DATE VOTED", "PRECINCT"])?;
    let mut voters = Voters::new();
    for row in rows.iter().skip(first + 1) {
        let raw = field(row, &headers, "DATE VOTED");
        if raw.is_empty() {
            continue;
        }
        let day = date(raw)?;
        if day < start(year) || day >= start(year) + chrono::Duration::days(i64::from(n)) {
            continue;
        }
        let id = field(row, &headers, "SOS VOTERID");
        let id = if id.is_empty() {
            field(row, &headers, "IDNUMBER")
        } else {
            id
        };
        insert(
            &mut voters,
            id,
            day,
            field(row, &headers, "PRECINCT"),
            false,
        )?;
    }
    days_from(
        voters,
        r,
        year,
        n,
        &url,
        &hash,
        "County cumulative in-person workbook, filtered by DATE VOTED and residence PRECINCT. Unique voter IDs; blanks remain unassigned. 2026 four-day roster is 64 above county location totals; historical days reconcile exactly.",
    )
}
async fn hays(client: &reqwest::Client, r: &Reference, n: u32) -> Result<Vec<Daily>> {
    let url = "https://www.hayscountytx.gov/DocumentCenter/View/5455?bidId=";
    let raw = download(client, url, None).await?;
    let hash = format!("{:x}", Sha256::digest(&raw));
    let members = zip_members(raw)?;
    let (member, bytes) = members
        .iter()
        .find(|(name, _)| name.to_lowercase().ends_with(".csv"))
        .context("Hays ZIP missing CSV")?;
    ensure!(member.contains("20261103"), "wrong Hays election archive");
    let mut csv = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(bytes.as_slice());
    let headers = csv.headers()?.clone();
    let idx = |name: &str| {
        headers
            .iter()
            .position(|h| h.trim_start_matches('\u{feff}') == name)
            .with_context(|| format!("Hays missing field {name}"))
    };
    let id = idx("VUID")?;
    let p = idx("Prec.")?;
    let method = idx("Type")?;
    let d = idx("Date")?;
    let provisional = idx("Prov.")?;
    let mut voters = Voters::new();
    for row in csv.records() {
        let row = row?;
        if &row[method] != "EARLY VOTED" || &row[provisional] != "N" {
            continue;
        }
        let day = date(&row[d])?;
        if day < start(2026) || day >= start(2026) + chrono::Duration::days(i64::from(n)) {
            continue;
        }
        insert(&mut voters, &row[id], day, &row[p], false)?;
    }
    days_from(
        voters,
        r,
        2026,
        n,
        url,
        &hash,
        "County dated residence-precinct roster. EARLY VOTED and Prov. N only; limited and provisional ballots excluded before deduplication. State four-day roster is 179 higher and is not substituted.",
    )
}
async fn ellis(client: &reqwest::Client, r: &Reference, n: u32) -> Result<Vec<Daily>> {
    // The county replaces an undated cumulative workbook. Its newest cutoff
    // cannot reconstruct earlier days; independently dated SOS reports can.
    let mut sources = match ellis_native(client, r).await {
        Ok(values) => values,
        Err(error) => {
            eprintln!("Ellis county cumulative source unavailable: {error:#}");
            Vec::new()
        }
    };
    let mut identities = std::collections::BTreeSet::new();
    for day in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(day));
        match crate::fetch::fetch_state(client, r, date, &mut identities).await {
            Ok(value) => sources.push(value),
            Err(error) => {
                eprintln!("Ellis dated SOS {date}: {error:#}; other observations retained")
            }
        }
    }
    ensure!(
        !sources.is_empty(),
        "No Ellis county or dated SOS observations available"
    );
    Ok(sources)
}
async fn ellis_native(client: &reqwest::Client, r: &Reference) -> Result<Vec<Daily>> {
    let url = "https://www.elliscountytx.gov/DocumentCenter/View/24311/110326-Election-Early-Voting-InPerson-Roster?bidId=";
    let raw = download(client, url, None).await?;
    let hash = format!("{:x}", Sha256::digest(&raw));
    let members = zip_members(raw)?;
    let (name, bytes) = members
        .iter()
        .find(|(name, _)| name.to_lowercase().ends_with(".xlsx"))
        .context("Ellis ZIP missing workbook")?;
    let name_date = name
        .rsplit('_')
        .next()
        .context("Ellis filename date missing")?
        .trim_end_matches(".xlsx");
    let through = NaiveDate::parse_from_str(name_date, "%m%d%y")
        .context("Ellis workbook filename date changed")?;
    ensure!(through.year() == 2026, "wrong Ellis election year");
    // Preserve the workbook's actual cutoff, even if it is later than the
    // requested completed day. Cached exact-cutoff snapshots are merged by the
    // refresh engine; a later cumulative total never reconstructs earlier days.
    days_through(through)?;
    let rows = workbook(bytes.clone())?;
    let (first, headers) = header(&rows, &["PRECINCT", "VUID"])?;
    ensure!(
        rows.iter()
            .take(first)
            .flatten()
            .any(|s| s.contains("November 3, 2026")),
        "wrong Ellis workbook election title"
    );
    let mut voters = Voters::new();
    for row in rows.iter().skip(first + 1) {
        let id = field(row, &headers, "VUID");
        if id.len() != 10 || !id.bytes().all(|b| b.is_ascii_digit()) {
            continue;
        }
        insert(
            &mut voters,
            id,
            through,
            field(row, &headers, "PRECINCT"),
            false,
        )?;
    }
    let mut counts = Counts::new();
    for (_, p) in voters.values() {
        *counts.entry(p.clone()).or_default() += 1;
    }
    ensure!(!counts.is_empty(), "Ellis workbook has no ordinary voters");
    Ok(vec![Daily {
        complete: false,
        county: r.id.clone(),
        date: through,
        counts,
        source: url.into(),
        sha256: hash,
        retrieved_at: Utc::now().to_rfc3339(),
        cumulative: true,
        note: format!(
            "County ordinary in-person cumulative workbook through {through}, dated by filename; no per-voter date column. Earlier precinct cutoffs unavailable. At the initial October 23 audit, four-day total 26,788 matched the official summary; state roster is 11 lower."
        ),
    }])
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cross_day_dedup_keeps_earliest_and_rejects_conflicting_precinct() {
        let mut v = Voters::new();
        insert(&mut v, "x", start(2024), "001", true).unwrap();
        insert(
            &mut v,
            "x",
            start(2024) + chrono::Duration::days(1),
            "1",
            true,
        )
        .unwrap();
        assert_eq!(v.len(), 1);
        assert_eq!(v["x"].0, start(2024));
        assert!(insert(&mut v, "x", start(2024), "2", true).is_err());
    }
    #[test]
    fn excel_and_string_dates() {
        assert_eq!(date("45588").unwrap().to_string(), "2024-10-23");
        assert_eq!(date("10.21.24").unwrap(), start(2024));
    }
    #[test]
    fn travis_discovers_renamed_county_archive_for_the_right_election() {
        let page = "https://votetravis.gov/current-election-information/current-election/";
        let html = "<a href='/wp-content/uploads/G24-Voter-Rosters.zip'>Old</a><a href='/wp-content/uploads/G26-Voter-Rosters-1.zip?version=2&amp;download=1'>Current roster</a>";
        assert_eq!(
            travis_roster_link(html, page, 2026).unwrap(),
            "https://votetravis.gov/wp-content/uploads/G26-Voter-Rosters-1.zip?version=2&download=1"
        );
        assert!(
            travis_roster_link(
                "<a href='https://other.example/G26-Voter-Rosters.zip'>Roster</a>",
                page,
                2026
            )
            .is_err()
        );
        assert!(
            travis_roster_link(
                "<a href='/wp-content/uploads/G24-Voter-Rosters.zip'>Old</a>",
                page,
                2026
            )
            .is_err()
        );
        assert!(
            travis_roster_link(
                "<a href='/wp-content/uploads/G26-Voter-Rosters.html'>Wrong type</a>",
                page,
                2026
            )
            .is_err()
        );
    }

    #[test]
    fn changing_roster_link_is_discovered() {
        let u = link(
            "<a href=\"/files/new.xlsx\">In-Person Early Voter List</a>",
            "in-person early",
            "https://example.gov/election/",
        )
        .unwrap();
        assert_eq!(u, "https://example.gov/files/new.xlsx");
    }
}

/// Harris publishes a dedicated in-person ZIP with one dated CSV per day.
/// Stream members directly into counts; never retain voter rows or personal fields.
fn harris_counts(bytes: &[u8], year: i32, n: u32) -> Result<BTreeMap<NaiveDate, Counts>> {
    ensure!(
        matches!(year, 2024 | 2026) && (1..=12).contains(&n),
        "invalid Harris period"
    );
    let first = start(year);
    let last = first + chrono::Duration::days(i64::from(n - 1));
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes))?;
    let mut days: BTreeMap<NaiveDate, Counts> = BTreeMap::new();
    let mut voters = std::collections::BTreeSet::new();
    let mut county_ids = std::collections::BTreeSet::new();
    for i in 0..archive.len() {
        let member = archive.by_index(i)?;
        if member.is_dir() || !member.name().to_ascii_lowercase().ends_with(".csv") {
            continue;
        }
        let mut reader = csv::ReaderBuilder::new()
            .trim(csv::Trim::All)
            .from_reader(member);
        let headers = reader.headers()?.clone();
        let column = |name: &str| {
            headers
                .iter()
                .position(|h| h.trim_start_matches('\u{feff}') == name)
                .with_context(|| format!("Harris missing {name}"))
        };
        let voter = column("StateVoterID")?;
        let county_id = column("IDNumber")?;
        let precinct = column("Precinct")?;
        let activity = column("ActivityDate")?;
        for row in reader.records() {
            let row = row?;
            let when = NaiveDate::parse_from_str(&row[activity], "%m/%d/%Y")
                .context("Harris activity date changed")?;
            ensure!(
                when >= first && when < first + chrono::Duration::days(12),
                "Harris date outside early-vote calendar"
            );
            ensure!(
                !row[voter].is_empty() && !row[county_id].is_empty(),
                "Harris blank identifier"
            );
            ensure!(
                voters.insert(row[voter].to_string())
                    && county_ids.insert(row[county_id].to_string()),
                "Harris repeated in-person identifier"
            );
            if when > last {
                continue;
            }
            let p = normalize(&row[precinct]);
            *days
                .entry(when)
                .or_default()
                .entry(if p.is_empty() { "UNASSIGNED".into() } else { p })
                .or_default() += 1;
        }
    }
    for offset in 0..n {
        ensure!(
            days.contains_key(&(first + chrono::Duration::days(i64::from(offset)))),
            "Harris requested daily report unavailable"
        );
    }
    Ok(days)
}
async fn harris(client: &reqwest::Client, r: &Reference, year: i32, n: u32) -> Result<Vec<Daily>> {
    let source = if year == 2024 {
        "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_1124.zip"
    } else {
        "https://appfiles.harrisvotes.com/harrisvotes/prd/Reports/Cumulative_EV_ToPost_1126.zip"
    };
    let bytes = download(client, source, None).await?;
    let hash = format!("{:x}", Sha256::digest(&bytes));
    let stamp = chrono::Utc::now().to_rfc3339();
    Ok(harris_counts(&bytes, year, n)?.into_iter().map(|(date, counts)| Daily { complete: false,
        county: r.id.clone(), date, counts, source: source.into(), sha256: hash.clone(), retrieved_at: stamp.clone(), cumulative: false,
        note: "Official Harris County dedicated in-person early-voting ZIP; CSV ActivityDate fixes the date. StateVoterID and county IDNumber are unique within/across archive members. Mail/election-day sources excluded. Native county reports used consistently for both cycles; they differ from SOS aggregates, including the incomplete October 23, 2026 SOS roster. No voter records retained or missing votes allocated.".into(),
    }).collect())
}

#[cfg(test)]
mod harris_tests {
    use super::*;
    use std::io::Write;
    fn zip(csv: &str) -> Vec<u8> {
        let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
        writer
            .start_file("InPerson.csv", zip::write::SimpleFileOptions::default())
            .unwrap();
        writer.write_all(csv.as_bytes()).unwrap();
        writer.finish().unwrap().into_inner()
    }
    #[test]
    fn dated_zip_preserves_residence_and_rejects_missing_or_reused_identity() {
        let header = "StateVoterID,IDNumber,Precinct,ActivityDate\n";
        let bytes = zip(&format!(
            "{header}a,x,0001,10/19/2026\nb,y,0002,10/20/2026\n"
        ));
        let counts = harris_counts(&bytes, 2026, 2).unwrap();
        assert_eq!(counts[&start(2026)]["1"], 1);
        assert!(harris_counts(&bytes, 2026, 3).is_err());
        assert_eq!(harris_counts(&bytes, 2026, 1).unwrap().len(), 1);
        for rows in [
            "a,x,1,10/19/2026\na,y,2,10/20/2026\n",
            "a,x,1,10/19/2026\nb,x,2,10/20/2026\n",
            "a,x,1,11/04/2026\n",
        ] {
            assert!(harris_counts(&zip(&format!("{header}{rows}")), 2026, 2).is_err());
        }
    }
}

fn nueces_roster_link(html: &str, base: &str) -> Result<String> {
    let mut links = Vec::new();
    for chunk in html.split("<a").skip(1) {
        let Some((tag, content)) = chunk.split_once('>') else {
            continue;
        };
        let Some(content) = content.split("</a>").next() else {
            continue;
        };
        let mut plain = String::new();
        let mut inside = false;
        for ch in content.chars() {
            if ch == '<' {
                inside = true;
            } else if ch == '>' {
                inside = false;
            } else if !inside {
                plain.push(ch);
            }
        }
        let plain = plain.to_ascii_lowercase().replace("&nbsp;", " ");
        let plain = plain.split_whitespace().collect::<Vec<_>>().join(" ");
        if plain != "early voting daily roster (in person)" {
            continue;
        }
        let lower = tag.to_ascii_lowercase();
        let Some(start) = lower.find("href=") else {
            continue;
        };
        let value = &tag[start + 5..];
        let quote = value.chars().next().context("empty Nueces roster link")?;
        ensure!(
            quote == '\'' || quote == '"',
            "Nueces roster href format changed"
        );
        let href = value[1..]
            .split(quote)
            .next()
            .context("invalid Nueces link")?;
        let url = reqwest::Url::parse(base)?.join(href)?;
        ensure!(
            url.scheme() == "https" && url.host_str() == Some("www.nuecesco.com"),
            "Nueces roster left official host"
        );
        links.push(url.to_string());
    }
    links.sort();
    links.dedup();
    ensure!(
        links.len() == 1,
        "Nueces in-person roster link is unavailable or ambiguous"
    );
    Ok(links.remove(0))
}
fn nueces_counts(text: &str, n: u32) -> Result<BTreeMap<NaiveDate, Counts>> {
    ensure!((1..=12).contains(&n), "invalid Nueces cutoff");
    let first = start(2026);
    let last = first + chrono::Duration::days(i64::from(n - 1));
    let mut days: BTreeMap<NaiveDate, Counts> = BTreeMap::new();
    let mut seen = std::collections::BTreeSet::new();
    for line in text.lines() {
        let lower = line.to_ascii_lowercase();
        let has_id = line
            .split_whitespace()
            .any(|s| (8..=10).contains(&s.len()) && s.bytes().all(|c| c.is_ascii_digit()));
        let at = lower.rfind("early voted");
        if !has_id {
            let possible_id = line
                .split_whitespace()
                .take(2)
                .any(|s| s.bytes().all(|c| c.is_ascii_digit()));
            ensure!(
                !(at.is_some() && possible_id),
                "Nueces identifier layout changed"
            );
            continue;
        }
        let at = at.context("Nueces voter row type or layout changed")?;
        let mut fields = line[..at].split_whitespace();
        let precinct = fields.next().context("Nueces row has no precinct")?;
        let id = fields.next().context("Nueces row has no identifier")?;
        ensure!(
            (8..=10).contains(&id.len())
                && id.bytes().all(|c| c.is_ascii_digit())
                && fields.next().is_some(),
            "Nueces row identity layout changed"
        );
        ensure!(
            precinct
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'.' || c == b'-'),
            "Nueces precinct format changed"
        );
        let when = NaiveDate::parse_from_str(line[at + "early voted".len()..].trim(), "%m/%d/%Y")
            .context("Nueces vote date changed")?;
        ensure!(
            when >= first && when < first + chrono::Duration::days(12),
            "Nueces date outside current early-voting calendar"
        );
        ensure!(
            seen.insert(id.to_string()),
            "Nueces repeated in-person identifier"
        );
        if when <= last {
            *days
                .entry(when)
                .or_default()
                .entry(normalize(precinct))
                .or_default() += 1;
        }
    }
    for offset in 0..n {
        ensure!(
            days.contains_key(&(first + chrono::Duration::days(i64::from(offset)))),
            "Nueces requested daily report unavailable"
        );
    }
    Ok(days)
}
async fn nueces(client: &reqwest::Client, r: &Reference, n: u32) -> Result<Vec<Daily>> {
    use std::process::Stdio;
    use tokio::io::AsyncWriteExt;
    let page = "https://www.nuecesco.com/county-services/county-clerk/elections-department";
    let html = String::from_utf8(download(client, page, None).await?)
        .context("Nueces page is not UTF-8")?;
    let source = nueces_roster_link(&html, page)?;
    let bytes = download(client, &source, None).await?;
    ensure!(bytes.starts_with(b"%PDF"), "Nueces roster is not PDF");
    let hash = format!("{:x}", Sha256::digest(&bytes));
    let mut child = tokio::process::Command::new("pdftotext")
        .args(["-layout", "-", "-"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .context("pdftotext is required for the Nueces county source")?;
    let mut input = child.stdin.take().unwrap();
    let writer = tokio::spawn(async move { input.write_all(&bytes).await });
    let output = tokio::time::timeout(std::time::Duration::from_secs(90), child.wait_with_output())
        .await??;
    writer.await??;
    ensure!(output.status.success(), "Nueces PDF text extraction failed");
    let text = String::from_utf8(output.stdout).context("Nueces extracted text is not UTF-8")?;
    let stamp = chrono::Utc::now().to_rfc3339();
    Ok(nueces_counts(&text,n)?.into_iter().map(|(date,counts)| Daily { complete: false, county:r.id.clone(),date,counts,source:source.clone(),sha256:hash.clone(),retrieved_at:stamp.clone(),cumulative:false,note:"Official Nueces County dedicated in-person daily roster PDF, discovered from the current county page. Every parsed row is Early Voted with a native date and unique VUID; raw PDF/text remain only in anonymous pipes/memory. All dates use the county source consistently; native precinct labels absent from the 26P proxy remain unassigned. No votes are allocated to close SOS or map discrepancies.".into() }).collect())
}
#[cfg(test)]
mod nueces_tests {
    use super::*;
    #[test]
    fn discovers_only_in_person_link_and_parses_touching_name_type() {
        let html = r#"<a href="/mail">Early Voting Daily Roster (Mail)</a><a href="/home/showpublisheddocument/34763"><span>Early Voting Daily Roster (In Person)</span></a>"#;
        assert!(
            nueces_roster_link(html, "https://www.nuecesco.com/")
                .unwrap()
                .ends_with("/34763")
        );
        let text = "Roster for Early Voted\nPrecinct VUID Name Type Date\n0001 1234567890 EXAMPLE NAMEEarly Voted 10/19/2026\n0002 1234567891 OTHER NAME Early Voted 10/20/2026\n0003 12345678 SHORT ID Early Voted 10/20/2026\n0004 123456789 SHORT ID Early Voted 10/20/2026\n";
        let counts = nueces_counts(text, 2).unwrap();
        assert_eq!(counts[&start(2026)]["1"], 1);
        assert_eq!(counts[&(start(2026) + chrono::Duration::days(1))]["3"], 1);
        assert_eq!(counts[&(start(2026) + chrono::Duration::days(1))]["4"], 1);
        assert!(nueces_counts(text, 3).is_err());
        assert!(
            nueces_counts(
                &format!("{text}0002 1234567890 SAME Early Voted 10/20/2026\n"),
                2
            )
            .is_err()
        );
        assert!(nueces_counts("0001 1234567890 EXAMPLE Mail Voted 10/19/2026", 1).is_err());
        assert!(
            nueces_counts(
                &format!("{text}0005 1234567 SHORT Early Voted 10/20/2026\n"),
                2
            )
            .is_err()
        );
        assert!(
            nueces_counts(
                &format!("{text}0005 UNKNOWN NAME Early Voted 10/20/2026\n"),
                2
            )
            .is_err()
        );
    }
}
