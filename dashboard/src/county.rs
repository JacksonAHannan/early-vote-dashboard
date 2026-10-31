//! County formats take precedence where they expose ordinary in-person scope.
use crate::{fetch::download, *};
use anyhow::{Context, Result, bail, ensure};
use calamine::{Data, Reader, open_workbook_auto_from_rs};
use chrono::Datelike;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
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
        "%m/%d/%Y %H:%M",
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
        let Some(counts) = days.remove(&day) else {
            continue; // An unposted date cannot invalidate independent posted dates.
        };
        output.push(Daily {
            zero_evidence: Vec::new(),
            allow_daily_difference: None,
            unavailable_precincts: Vec::new(),
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
    ensure!(
        !output.is_empty(),
        "county ordinary roster has no observed dates"
    );
    Ok(output)
}

#[derive(Default)]
struct CountyRoster {
    voters: Voters,
    blank_identifiers: BTreeMap<NaiveDate, BTreeMap<String, u64>>,
}
impl CountyRoster {
    fn record(&mut self, id: &str, day: NaiveDate, precinct: &str, repeat: bool) -> Result<()> {
        if id.trim().is_empty() {
            let precinct = normalize(precinct);
            let precinct = if precinct.is_empty() {
                "UNASSIGNED".into()
            } else {
                precinct
            };
            *self
                .blank_identifiers
                .entry(day)
                .or_default()
                .entry(precinct)
                .or_default() += 1;
            return Ok(());
        }
        insert(&mut self.voters, id, day, precinct, repeat)
    }

    fn days(
        self,
        reference: &Reference,
        year: i32,
        n: u32,
        source: &str,
        sha: &str,
        note: &str,
    ) -> Result<Vec<Daily>> {
        if self.blank_identifiers.is_empty() {
            return days_from(self.voters, reference, year, n, source, sha, note);
        }
        let mut counts_by_day: BTreeMap<NaiveDate, Counts> = BTreeMap::new();
        for (day, precinct) in self.voters.values() {
            *counts_by_day
                .entry(*day)
                .or_default()
                .entry(precinct.clone())
                .or_default() += 1;
        }
        let mut output = Vec::new();
        for offset in 0..n {
            let day = start(year) + chrono::Duration::days(i64::from(offset));
            let bad_cells = self.blank_identifiers.get(&day);
            let mut counts = match counts_by_day.remove(&day) {
                Some(counts) => counts,
                None if bad_cells.is_some() => Counts::new(),
                None => continue,
            };
            let mut scope = note.to_string();
            if let Some(cells) = bad_cells {
                // No invented identities or partial totals for an affected cell.
                // Identified rows remain in the identity map until aggregation,
                // preserving the existing conflict and cross-day repeat checks.
                for precinct in cells.keys() {
                    counts.remove(precinct);
                }
                scope.push_str(&format!(
                    " Blank-identifier quarantine: {} rows with blank identifiers in {} date/precinct cells on {day}; all counts for those cells withheld as unavailable, not zero.",
                    cells.values().sum::<u64>(), cells.len()
                ));
            }
            // An absent day cannot be recertified as a complete zero observation.
            if counts.is_empty() {
                continue;
            }
            output.push(Daily {
                zero_evidence: Vec::new(),
                allow_daily_difference: None,
                unavailable_precincts: bad_cells
                    .map(|cells| cells.keys().cloned().collect())
                    .unwrap_or_default(),
                complete: false,
                county: reference.id.clone(),
                date: day,
                counts,
                source: source.into(),
                sha256: sha.into(),
                retrieved_at: Utc::now().to_rfc3339(),
                note: scope,
                cumulative: false,
            });
        }
        ensure!(
            !output.is_empty(),
            "county ordinary roster has no usable dates after blank-identifier quarantine"
        );
        Ok(output)
    }
}

fn montgomery_rows(bytes: &[u8], day: NaiveDate, roster: &mut CountyRoster) -> Result<()> {
    // Validate a dated file locally; a rejected row must not leave identities or
    // quarantine flags that contaminate the next independently fetched date.
    let mut dated = CountyRoster::default();
    let mut csv = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(bytes);
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
        dated.record(&row[id], day, &row[p], true)?;
    }
    for (id, (_, precinct)) in &dated.voters {
        if let Some((_, old_precinct)) = roster.voters.get(id) {
            ensure!(
                old_precinct == precinct,
                "conflicting duplicate in county roster"
            );
        }
    }
    for (id, (when, precinct)) in dated.voters {
        insert(&mut roster.voters, &id, when, &precinct, true)?;
    }
    for (when, cells) in dated.blank_identifiers {
        for (precinct, count) in cells {
            *roster
                .blank_identifiers
                .entry(when)
                .or_default()
                .entry(precinct)
                .or_default() += count;
        }
    }
    Ok(())
}

fn dallas_rows(rows: &[Vec<String>], year: i32, n: u32) -> Result<CountyRoster> {
    let (first, headers) = header(rows, &["DATE VOTED", "PRECINCT"])?;
    let mut roster = CountyRoster::default();
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
        roster.record(id, day, field(row, &headers, "PRECINCT"), false)?;
    }
    Ok(roster)
}

fn dallas_blank_candidates(
    rows: &[Vec<String>],
    year: i32,
    n: u32,
) -> Result<BTreeMap<NaiveDate, BTreeSet<String>>> {
    let (first, headers) = header(rows, &["DATE VOTED", "PRECINCT", "SOS VOTERID"])?;
    let mut frequencies = BTreeMap::<String, usize>::new();
    let mut candidates = BTreeMap::<NaiveDate, BTreeSet<String>>::new();
    for row in rows.iter().skip(first + 1) {
        let raw = field(row, &headers, "DATE VOTED");
        if raw.is_empty() {
            continue;
        }
        let day = date(raw)?;
        let identity = field(row, &headers, "SOS VOTERID");
        if identity.is_empty() {
            continue;
        }
        // Count every date/known precinct in the workbook, not just candidates.
        *frequencies.entry(identity.into()).or_default() += 1;
        if day >= start(year)
            && day < start(year) + chrono::Duration::days(i64::from(n))
            && normalize(field(row, &headers, "PRECINCT")).is_empty()
        {
            candidates.entry(day).or_default().insert(identity.into());
        }
    }
    for identities in candidates.values_mut() {
        identities.retain(|identity| frequencies.get(identity) == Some(&1));
    }
    candidates.retain(|_, identities| !identities.is_empty());
    Ok(candidates)
}

fn dallas_apply_identities(
    roster: &mut CountyRoster,
    day: NaiveDate,
    candidates: &BTreeSet<String>,
    identities: &BTreeMap<String, String>,
    universe: &BTreeSet<String>,
) -> usize {
    let mut recovered = 0;
    for identity in candidates {
        let Some(target) = identities.get(identity).filter(|p| universe.contains(*p)) else {
            continue;
        };
        let Some((when, precinct)) = roster.voters.get_mut(identity) else {
            continue;
        };
        if *when == day && precinct == "UNASSIGNED" {
            *precinct = target.clone();
            recovered += 1;
        }
    }
    recovered
}

async fn dallas_recover_precincts(
    client: &reqwest::Client,
    reference: &Reference,
    rows: &[Vec<String>],
    roster: &mut CountyRoster,
    year: i32,
    n: u32,
) -> Result<BTreeMap<NaiveDate, (String, String, usize)>> {
    let candidates = dallas_blank_candidates(rows, year, n)?;
    let universe = reference
        .groups
        .iter()
        .flat_map(|g| g.new.iter().cloned())
        .collect();
    let semaphore = std::sync::Arc::new(tokio::sync::Semaphore::new(4));
    let mut jobs = tokio::task::JoinSet::new();
    for (day, identities) in candidates {
        let client = client.clone();
        let reference = reference.clone();
        let semaphore = semaphore.clone();
        jobs.spawn(async move {
            let _permit = semaphore.acquire().await.unwrap();
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(60),
                crate::fetch::fetch_precinct_identities(&client, &reference, day),
            )
            .await;
            (day, identities, result)
        });
    }
    let mut proofs = BTreeMap::new();
    while let Some(result) = jobs.join_next().await {
        // Optional enrichment cannot discard otherwise usable native observations.
        let Ok((day, candidates, Ok(Ok(source)))) = result else {
            continue;
        };
        let recovered =
            dallas_apply_identities(roster, day, &candidates, &source.unique, &universe);
        if recovered > 0 {
            proofs.insert(day, (source.source, source.sha256, recovered));
        }
    }
    Ok(proofs)
}

fn native_series(raw: &[u8], county: &str, through: NaiveDate) -> Result<Vec<Daily>> {
    let values: Vec<Daily> =
        serde_json::from_slice(raw).context("invalid native county aggregate JSON")?;
    let mut dates = BTreeSet::new();
    let mut output = Vec::new();
    for mut day in values {
        ensure!(
            day.county == county,
            "native county aggregate identity mismatch"
        );
        ensure!(
            day.date.year() == 2026
                && day.date >= start(2026)
                && day.date <= through
                && !day.cumulative,
            "native county aggregate date/scope mismatch"
        );
        ensure!(
            dates.insert(day.date),
            "duplicate native county aggregate date"
        );
        ensure!(
            !day.source.trim().is_empty()
                && day.sha256.len() == 64
                && day.sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "native county aggregate provenance missing or invalid"
        );
        day.complete = false;
        day.unavailable_precincts = day
            .unavailable_precincts
            .into_iter()
            .map(|p| {
                let p = normalize(&p);
                if p.is_empty() { "UNASSIGNED".into() } else { p }
            })
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        day.counts
            .retain(|p, _| !day.unavailable_precincts.contains(&normalize(p)));
        if day.counts.is_empty() && !day.unavailable_precincts.is_empty() {
            continue; // Entirely unavailable dates cannot be certified as zeros.
        }
        ensure!(
            day.counts.values().any(|count| *count > 0),
            "empty native county roster is not confirmed zero"
        );
        output.push(day);
    }
    ensure!(
        !output.is_empty(),
        "native county collector returned no usable dated reports"
    );
    output.sort_by_key(|d| d.date);
    Ok(output)
}

async fn native_county(county: &str, n: u32) -> Result<Vec<Daily>> {
    ensure!(
        (1..=12).contains(&n),
        "invalid native county calendar cutoff"
    );
    let through = start(2026) + chrono::Duration::days(i64::from(n - 1));
    let child = tokio::process::Command::new("python3")
        .arg(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(match county {
                "collin" => "scripts/collect_collin.py",
                "panola" => "scripts/collect_panola.py",
                "cameron" | "denton" => "scripts/collect_large_county_refresh.py",
                _ => "scripts/collect_county_native.py",
            }),
        )
        .args(["--county", county, "--through", &through.to_string()])
        .kill_on_drop(true)
        .output();
    let output = tokio::time::timeout(std::time::Duration::from_secs(360), child)
        .await
        .context("native county collection timed out")??;
    ensure!(
        output.status.success(),
        "native county collector failed: {}",
        String::from_utf8_lossy(&output.stderr).trim()
    );
    native_series(&output.stdout, county, through)
}

fn tarrant_anchor(raw: &[u8], reference: &Reference, through: NaiveDate) -> Result<Daily> {
    let mut values: Vec<Daily> = serde_json::from_slice(raw)?;
    ensure!(
        values.len() == 1,
        "Tarrant anchor must have exactly one cutoff"
    );
    let mut anchor = values.remove(0);
    ensure!(
        anchor.county == "tarrant"
            && anchor.county == reference.id
            && anchor.date == through
            && anchor.date.year() == 2026
            && anchor.cumulative
            && anchor.allow_daily_difference == Some(false),
        "Tarrant source is not a cumulative-only exact-cutoff anchor"
    );
    ensure!(
        anchor.source
            == "https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_voting_in_person_report.zip"
            && anchor.sha256.len() == 64
            && anchor.sha256.bytes().all(|b| b.is_ascii_hexdigit())
            && !anchor.note.is_empty(),
        "Tarrant anchor provenance missing"
    );
    anchor.complete = false;
    anchor.zero_evidence.clear();
    anchor.unavailable_precincts.sort();
    anchor.unavailable_precincts.dedup();
    anchor
        .counts
        .retain(|p, _| !anchor.unavailable_precincts.contains(p));
    let universe: BTreeSet<_> = reference.groups.iter().flat_map(|g| g.new.iter()).collect();
    ensure!(
        anchor
            .counts
            .iter()
            .any(|(p, n)| *n > 0 && universe.contains(p)),
        "Tarrant anchor has no verified native precinct counts"
    );
    Ok(anchor)
}

async fn tarrant(client: &reqwest::Client, reference: &Reference, n: u32) -> Result<Vec<Daily>> {
    ensure!((1..=12).contains(&n), "invalid Tarrant cutoff");
    let mut days = Vec::new();
    let mut identities = BTreeSet::new();
    for offset in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(offset));
        // Retain every dated SOS report, independently of optional county anchor availability.
        if let Ok(day) = crate::fetch::fetch_state(client, reference, date, &mut identities).await {
            days.push(day);
        }
    }
    let through = start(2026) + chrono::Duration::days(i64::from(n - 1));
    let child = tokio::process::Command::new("uv")
        .args(["run", "--quiet", "--with", "curl-cffi==0.16.3", "python"])
        .arg(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("scripts/collect_tarrant_anchor.py"),
        )
        .args(["--through", &through.to_string()])
        .kill_on_drop(true)
        .output();
    if let Ok(Ok(output)) = tokio::time::timeout(std::time::Duration::from_secs(180), child).await
        && output.status.success()
        && let Ok(anchor) = tarrant_anchor(&output.stdout, reference, through)
    {
        days.push(anchor);
    }
    ensure!(
        !days.is_empty(),
        "No dated Tarrant SOS sources or verified cumulative anchor"
    );
    Ok(days)
}

// An independent alternative fills only a missing date; it never displaces an
// existing report or borrows observations from another date.
fn fill_missing_dates(values: &mut Vec<Daily>, native: Vec<Daily>) {
    for source in native {
        if !values
            .iter()
            .any(|d| d.date == source.date && !d.cumulative)
        {
            values.push(source);
        }
    }
    values.sort_by_key(|d| (d.date, d.cumulative));
}

fn native_observations(source: &Daily, universe: &BTreeSet<String>) -> usize {
    if source.complete
        && source.unavailable_precincts.is_empty()
        && source
            .counts
            .iter()
            .all(|(p, n)| *n == 0 || universe.contains(p))
    {
        return universe.len();
    }
    source
        .counts
        .keys()
        .filter(|p| universe.contains(*p) && !source.unavailable_precincts.contains(*p))
        .count()
}

fn prefer_more_native_observations(
    values: &mut Vec<Daily>,
    native: Vec<Daily>,
    universe: &BTreeSet<String>,
) {
    for source in native {
        if let Some(index) = values
            .iter()
            .position(|d| d.date == source.date && d.cumulative == source.cumulative)
        {
            if native_observations(&source, universe)
                > native_observations(&values[index], universe)
            {
                values[index] = source;
            }
        } else {
            values.push(source);
        }
    }
    values.sort_by_key(|d| (d.date, d.cumulative));
}

async fn collin(client: &reqwest::Client, reference: &Reference, n: u32) -> Result<Vec<Daily>> {
    let mut values = Vec::new();
    let mut identities = BTreeSet::new();
    for day in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(day));
        if let Ok(source) =
            crate::fetch::fetch_state(client, reference, date, &mut identities).await
        {
            values.push(source);
        }
    }
    let report = crate::quality::Report::load(std::path::Path::new(env!("CARGO_MANIFEST_DIR")))
        .unwrap_or_default();
    values = report.sources("collin", &values);
    match native_county("collin", n).await {
        Ok(native) => {
            let universe = reference
                .groups
                .iter()
                .flat_map(|g| g.new.iter().cloned())
                .collect();
            prefer_more_native_observations(
                &mut values,
                report.sources("collin", &native),
                &universe,
            );
        }
        Err(error) => eprintln!("Collin native date alternative: {error}"),
    }
    ensure!(
        !values.is_empty(),
        "no usable dated Collin in-person reports"
    );
    Ok(values)
}

async fn panola(client: &reqwest::Client, reference: &Reference, n: u32) -> Result<Vec<Daily>> {
    let mut values = Vec::new();
    let mut identities = BTreeSet::new();
    for day in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(day));
        if let Ok(source) =
            crate::fetch::fetch_state(client, reference, date, &mut identities).await
        {
            values.push(source);
        }
    }
    if values.len() < n as usize {
        match native_county("panola", n).await {
            Ok(native) => fill_missing_dates(&mut values, native),
            Err(error) => eprintln!("Panola native missing-date fallback: {error}"),
        }
    }
    ensure!(
        !values.is_empty(),
        "no usable dated Panola in-person reports"
    );
    Ok(values)
}

async fn large_county(
    client: &reqwest::Client,
    reference: &Reference,
    n: u32,
) -> Result<Vec<Daily>> {
    // Replaced county workbooks supply explicit CHECK-IN dates. A failed latest
    // section does not erase valid earlier sections or dated SOS alternatives.
    let mut values = Vec::new();
    let mut identities = BTreeSet::new();
    for day in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(day));
        match crate::fetch::fetch_state(client, reference, date, &mut identities).await {
            Ok(source) => values.push(source),
            Err(error) => eprintln!("{} dated SOS {date}: {error:#}", reference.name),
        }
    }
    let report = crate::quality::Report::load(std::path::Path::new(env!("CARGO_MANIFEST_DIR")))
        .unwrap_or_default();
    values = report.sources(&reference.id, &values);
    match native_county(&reference.id, n).await {
        Ok(native) => {
            let universe = reference
                .groups
                .iter()
                .flat_map(|g| g.new.iter().cloned())
                .collect();
            prefer_more_native_observations(
                &mut values,
                report.sources(&reference.id, &native),
                &universe,
            );
        }
        Err(error) => eprintln!("{} native date alternative: {error:#}", reference.name),
    }
    ensure!(
        !values.is_empty(),
        "no usable dated {} in-person reports",
        reference.name
    );
    Ok(values)
}

async fn native_with_state_fallback(
    client: &reqwest::Client,
    reference: &Reference,
    n: u32,
) -> Result<Vec<Daily>> {
    let mut values = match native_county(&reference.id, n).await {
        Ok(values) => values,
        Err(error) => {
            eprintln!(
                "{} native roster: {error:#}; trying independent dated SOS sources",
                reference.name
            );
            Vec::new()
        }
    };
    let mut identities = BTreeSet::new();
    for offset in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(offset));
        if !values
            .iter()
            .any(|value| value.date == date && !value.cumulative)
        {
            match crate::fetch::fetch_state(client, reference, date, &mut identities).await {
                Ok(value) => fill_missing_dates(&mut values, vec![value]),
                Err(error) => eprintln!("{} dated SOS {date}: {error:#}", reference.name),
            }
        }
    }
    ensure!(
        !values.is_empty(),
        "no usable {} native or dated SOS observations",
        reference.name
    );
    Ok(values)
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
        "tarrant" if year == 2026 => tarrant(client, r, n).await,
        "nueces" if year == 2026 => nueces(client, r, n).await,
        "panola" if year == 2026 => panola(client, r, n).await,
        "collin" if year == 2026 => collin(client, r, n).await,
        "cameron" | "denton" if year == 2026 => large_county(client, r, n).await,
        "fortbend" if crate::fort_bend::supports(year) => {
            crate::fort_bend::collect(client, r, year, n).await
        }
        "montgomery" => montgomery(client, r, year, n).await,
        "hays" if year == 2026 => hays(client, r, n).await,
        "ellis" if year == 2026 => ellis(client, r, n).await,
        "waller" | "washington" | "sanpatricio" if year == 2026 => {
            native_with_state_fallback(client, r, n).await
        }
        _ => bail!("no county adapter"),
    }
}
pub fn has_adapter(id: &str, year: i32) -> bool {
    if id == "fortbend" && crate::fort_bend::supports(year) {
        return true;
    }
    ["travis", "dallas", "montgomery", "harris"].contains(&id)
        || (year == 2026
            && [
                "hays",
                "ellis",
                "nueces",
                "tarrant",
                "waller",
                "washington",
                "sanpatricio",
                "collin",
                "panola",
                "cameron",
                "denton",
            ]
            .contains(&id))
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
    for i in 0..n {
        let day = start(year) + chrono::Duration::days(i64::from(i));
        let name = format!("{} Early Vote.xlsx", day.format("%m.%d.%Y"));
        let Some((_, bytes)) = members.iter().find(|(name2, _)| name2 == &name) else {
            eprintln!("Travis daily workbook not posted: {day}; other dates retained");
            continue;
        };
        let result = workbook(bytes.clone()).and_then(|rows| travis_rows(&rows, day, &mut voters));
        if let Err(error) = result {
            eprintln!("Travis dated workbook {day}: {error:#}; other dates retained");
        }
    }
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

fn travis_rows(rows: &[Vec<String>], day: NaiveDate, voters: &mut Voters) -> Result<()> {
    let (first, headers) = header(rows, &["VUID", "PCT"])?;
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
    let mut dated = Voters::new();
    for row in rows.iter().skip(first + 1) {
        let id = field(row, &headers, "VUID");
        if id.is_empty() {
            continue;
        }
        insert(&mut dated, id, day, field(row, &headers, "PCT"), false)?;
    }
    for (id, (when, precinct)) in &dated {
        if let Some((old_when, old_precinct)) = voters.get(id) {
            ensure!(
                old_when == when && old_precinct == precinct,
                "conflicting duplicate in county roster"
            );
        }
    }
    voters.extend(dated);
    Ok(())
}

async fn montgomery(
    client: &reqwest::Client,
    r: &Reference,
    year: i32,
    n: u32,
) -> Result<Vec<Daily>> {
    let mut roster = CountyRoster::default();
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
        let raw = match download(client, &url, None).await {
            Ok(raw) => raw,
            Err(error) => {
                eprintln!("Montgomery dated source {day}: {error:#}; other dates retained");
                continue;
            }
        };
        let hash = format!("{:x}", Sha256::digest(&raw));
        let parsed = (|| {
            let members = zip_members(raw)?;
            let (_, bytes) = members
                .iter()
                .find(|(name, _)| name.to_lowercase().ends_with(".csv"))
                .context("no Montgomery CSV")?;
            montgomery_rows(bytes, day, &mut roster)
        })();
        match parsed {
            Ok(()) => evidence.push((day, url, hash)),
            Err(error) => {
                eprintln!("Montgomery dated source {day}: {error:#}; other dates retained")
            }
        }
    }
    let mut days = roster.days(
        r,
        year,
        n,
        "",
        "",
        "County ordinary E only; limited and mail excluded. Deduplicated VUID across jurisdictions and dates, assigning earliest appearance. Independent county controls determine completeness; unsupported cells remain unavailable.",
    )?;
    for daily in &mut days {
        let (_, url, hash) = evidence
            .iter()
            .find(|(day, _, _)| *day == daily.date)
            .unwrap();
        daily.source = url.clone();
        daily.sha256 = hash.clone();
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

fn dallas_source_rows(raw: Vec<u8>) -> Result<Vec<Vec<String>>> {
    // The county changed its rotating in-person download from XLSX to CSV on
    // October 29. Both formats must use the same date/identity/quarantine path.
    if raw.starts_with(b"PK\x03\x04") || raw.starts_with(b"\xd0\xcf\x11\xe0") {
        return workbook(raw);
    }
    let mut reader = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(raw.as_slice());
    let columns: Vec<_> = reader
        .headers()?
        .iter()
        .map(|h| h.trim_start_matches('\u{feff}').to_string())
        .collect();
    let expected = [
        "FIRSTNAME",
        "MIDDLENAME",
        "LASTNAME",
        "STREETNUMBER",
        "STREETPREDIR",
        "STREETNAME",
        "STREETTYPE",
        "STREETPOSTDIR",
        "UNIT",
        "CITY",
        "ZIP",
        "PRECINCT",
        "PRECINCT_SUB",
        "BALLOTSTYLE",
        "BALLOT_PARTY",
        "DATE_VOTED",
        "VOTING_UNIT",
        "VOTING_SUBUNIT",
        "SOS_VOTERID",
    ];
    ensure!(
        columns.len() == expected.len()
            && expected
                .iter()
                .all(|name| columns.iter().filter(|h| h.as_str() == *name).count() == 1),
        "Dallas in-person CSV schema changed or invalid response body"
    );
    let selected = ["DATE_VOTED", "PRECINCT", "SOS_VOTERID"]
        .map(|name| columns.iter().position(|h| h == name).unwrap());
    let party = columns.iter().position(|h| h == "BALLOT_PARTY").unwrap();
    // Retain only the three analytical fields in memory; names/addresses never
    // enter the aggregate parser or its optional exact-identity enrichment.
    let mut rows = vec![vec![
        "DATE VOTED".into(),
        "PRECINCT".into(),
        "SOS VOTERID".into(),
    ]];
    for record in reader.records() {
        let record = record?;
        ensure!(
            &record[party] == "NP",
            "Dallas general-election CSV has unexpected ballot-party scope"
        );
        rows.push(selected.iter().map(|i| record[*i].to_string()).collect());
    }
    ensure!(
        rows.len() > 1,
        "Dallas CSV has no ordinary voter observations"
    );
    Ok(rows)
}

fn dallas_csv_roster(
    rows: &[Vec<String>],
    year: i32,
    n: u32,
) -> Result<(CountyRoster, BTreeMap<NaiveDate, BTreeSet<String>>)> {
    let (first, headers) = header(rows, &["DATE VOTED", "PRECINCT", "SOS VOTERID"])?;
    let mut seen = Voters::new();
    let mut quarantine = BTreeMap::<NaiveDate, BTreeSet<String>>::new();
    // A revised native CSV may contradict an earlier date in the same edition.
    // Inspect all dated rows before counting; never arbitrarily keep one side.
    for row in rows.iter().skip(first + 1) {
        let raw_date = field(row, &headers, "DATE VOTED");
        let id = field(row, &headers, "SOS VOTERID");
        if raw_date.is_empty() || id.is_empty() {
            continue;
        }
        let day = date(raw_date)?;
        let p = normalize(field(row, &headers, "PRECINCT"));
        let p = if p.is_empty() { "UNASSIGNED".into() } else { p };
        if let Some((previous_day, previous_precinct)) = seen.get(id) {
            if *previous_day != day || previous_precinct != &p {
                quarantine
                    .entry(*previous_day)
                    .or_default()
                    .insert(previous_precinct.clone());
                quarantine.entry(day).or_default().insert(p);
            }
        } else {
            seen.insert(id.into(), (day, p));
        }
    }
    drop(seen);
    let mut roster = CountyRoster::default();
    for row in rows.iter().skip(first + 1) {
        let raw_date = field(row, &headers, "DATE VOTED");
        if raw_date.is_empty() {
            continue;
        }
        let day = date(raw_date)?;
        if day < start(year) || day >= start(year) + chrono::Duration::days(i64::from(n)) {
            continue;
        }
        let p = normalize(field(row, &headers, "PRECINCT"));
        let p = if p.is_empty() { "UNASSIGNED".into() } else { p };
        if quarantine.get(&day).is_some_and(|cells| cells.contains(&p)) {
            continue;
        }
        roster.record(field(row, &headers, "SOS VOTERID"), day, &p, false)?;
    }
    Ok((roster, quarantine))
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
    let csv_source = !raw.starts_with(b"PK\x03\x04") && !raw.starts_with(b"\xd0\xcf\x11\xe0");
    let rows = dallas_source_rows(raw)?;
    let (mut roster, csv_quarantine) = if csv_source {
        dallas_csv_roster(&rows, year, n)?
    } else {
        (dallas_rows(&rows, year, n)?, BTreeMap::new())
    };
    let proofs = if year == 2026 {
        dallas_recover_precincts(client, r, &rows, &mut roster, year, n)
            .await
            .unwrap_or_default()
    } else {
        BTreeMap::new()
    };
    let mut days = roster.days(
        r,
        year,
        n,
        &url,
        &hash,
        "County cumulative in-person workbook, filtered by DATE VOTED and residence PRECINCT. Unique voter IDs; blanks remain unassigned. Source totals are checked against independently dated county controls; unsupported cells remain unavailable.",
    )?;
    for day in &mut days {
        if let Some(cells) = csv_quarantine.get(&day.date) {
            day.unavailable_precincts.extend(cells.iter().cloned());
            day.unavailable_precincts.sort();
            day.unavailable_precincts.dedup();
            day.counts.retain(|p, _| !cells.contains(p));
            day.note.push_str(&format!(" Conflicting-ID quarantine: {} complete date/precinct cells withheld on {} because a native CSV identity disagrees with another date or residence precinct in this edition. Both sides of each conflict remain unavailable, never zero.", cells.len(), day.date));
        }
        if let Some((source, sos_hash, recovered)) = proofs.get(&day.date) {
            let manifest = serde_json::json!({"method":"unique-exact-voter-identity-precinct-enrichment-v1",
                "native_sha256":hash,"same_date_sos_sha256":sos_hash});
            day.sha256 = format!("{:x}", Sha256::digest(serde_json::to_vec(&manifest)?));
            day.note.push_str(&format!(" Exact-identity precinct recovery: {recovered} blank native residence precincts resolved using globally unique native SOS VOTERID and one unique same-date in-person SOS ID_VOTER with a known native residence precinct. Known native precincts, vote dates, total rows and quarantine rules are preserved. Native source {url} SHA256 {hash}; same-date identity source {source} SHA256 {sos_hash}. Derived SHA256 hashes the canonical input-hash/method manifest. No voter identities retained."));
        }
    }
    Ok(days)
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
        zero_evidence: Vec::new(),
        allow_daily_difference: None,
        unavailable_precincts: Vec::new(),
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

    fn native_report() -> serde_json::Value {
        serde_json::json!({
            "county":"waller", "date":"2026-10-19", "counts":{"1":9,"2":10},
            "source":"https://official.example/roster.pdf", "sha256":"a".repeat(64),
            "retrieved_at":"2026-10-26T00:00:00Z", "note":"County roster", "complete":true,
            "cumulative":false, "unavailable_precincts":["001"]
        })
    }

    #[test]
    fn dated_source_choice_preserves_stronger_state_dates_and_does_not_pool_labels() {
        let mut state: Daily = serde_json::from_value(native_report()).unwrap();
        state.counts = Counts::from([("1".into(), 10), ("2".into(), 20)]);
        state.unavailable_precincts.clear();
        state.complete = false;
        let universe = BTreeSet::from(["1".into(), "2".into(), "3".into()]);
        let mut first = state.clone();
        first.counts.remove("2");
        let mut second = state.clone();
        second.date += chrono::Duration::days(1);
        second.counts = Counts::from([("1".into(), 1)]);
        let mut better = second.clone();
        better.counts = Counts::from([("2".into(), 25), ("3".into(), 30)]);
        let mut values = vec![state.clone(), second];
        prefer_more_native_observations(&mut values, vec![first, better.clone()], &universe);
        assert_eq!(values[0].counts, state.counts);
        assert_eq!(values[1].counts, better.counts);
        assert!(!values[1].counts.contains_key("1"));
        let mut completed = state.clone();
        completed.complete = true;
        assert_eq!(native_observations(&completed, &universe), 3);
        completed.counts.insert("FOREIGN".into(), 1);
        assert_eq!(native_observations(&completed, &universe), 2);
        completed.unavailable_precincts.push("1".into());
        assert_eq!(native_observations(&completed, &universe), 1);
    }

    #[test]
    fn native_fallback_fills_only_the_missing_dated_state_observation() {
        let mut state: Daily = serde_json::from_value(native_report()).unwrap();
        state.county = "panola".into();
        state.source = "https://state.example/dated-report".into();
        state.counts = Counts::from([("1".into(), 42)]);
        state.unavailable_precincts.clear();
        state.complete = false;
        let mut redundant = state.clone();
        redundant.counts.insert("1".into(), 999);
        redundant.source = "https://county.example/different-report".into();
        let mut missing = redundant.clone();
        missing.date = start(2026) + chrono::Duration::days(1);
        missing.unavailable_precincts = vec!["2".into()];
        let mut values = vec![state.clone()];
        fill_missing_dates(&mut values, vec![missing.clone(), redundant]);
        assert_eq!(values.len(), 2);
        assert_eq!(values[0].source, state.source);
        assert_eq!(values[0].counts, state.counts);
        assert_eq!(values[1].date, missing.date);
        assert_eq!(values[1].unavailable_precincts, vec!["2"]);
        assert!(!values[1].complete);
        assert!(
            !values
                .iter()
                .any(|d| d.date == start(2026) + chrono::Duration::days(2))
        );
    }

    #[test]
    fn native_bridge_keeps_partial_dates_and_honors_unknown_cells() {
        let first = native_report();
        let mut third = first.clone();
        third["date"] = "2026-10-21".into();
        third["unavailable_precincts"] = serde_json::json!([]);
        let raw = serde_json::to_vec(&vec![third, first]).unwrap();
        let days = native_series(&raw, "waller", start(2026) + chrono::Duration::days(2)).unwrap();
        assert_eq!(days.len(), 2);
        assert_eq!(days[0].date, start(2026));
        assert_eq!(days[0].counts, Counts::from([("2".into(), 10)]));
        assert_eq!(days[0].unavailable_precincts, vec!["1"]);
        assert!(days.iter().all(|d| !d.complete));
        assert!(days[1].counts.contains_key("1"));
        for county in ["waller", "washington", "sanpatricio"] {
            assert!(has_adapter(county, 2026));
            assert!(!has_adapter(county, 2024));
        }
    }

    #[test]
    fn native_bridge_rejects_foreign_scope_invalid_schema_and_missing_provenance() {
        let cutoff = start(2026) + chrono::Duration::days(6);
        for (field, value) in [
            ("county", serde_json::json!("washington")),
            ("date", serde_json::json!("2024-10-21")),
            ("date", serde_json::json!("2026-10-18")),
            ("date", serde_json::json!("2026-10-26")),
            ("cumulative", serde_json::json!(true)),
            ("source", serde_json::json!(" ")),
            ("sha256", serde_json::json!("bad")),
            ("sha256", serde_json::json!("z".repeat(64))),
            ("counts", serde_json::json!({"1":-1})),
        ] {
            let mut report = native_report();
            report[field] = value;
            let raw = serde_json::to_vec(&vec![report]).unwrap();
            assert!(
                native_series(&raw, "waller", cutoff).is_err(),
                "accepted invalid {field}"
            );
        }
        for raw in [b"invalid JSON".as_slice(), b"{}", b"[]"] {
            assert!(native_series(raw, "waller", cutoff).is_err());
        }
        let duplicated = serde_json::to_vec(&vec![native_report(), native_report()]).unwrap();
        assert!(native_series(&duplicated, "waller", cutoff).is_err());
    }

    #[test]
    fn native_bridge_does_not_publish_empty_or_fully_quarantined_dates_as_zero() {
        let mut empty = native_report();
        empty["counts"] = serde_json::json!({});
        let raw = serde_json::to_vec(&vec![empty.clone()]).unwrap();
        assert!(native_series(&raw, "waller", start(2026)).is_err());
        let mut valid = native_report();
        valid["date"] = "2026-10-20".into();
        let raw = serde_json::to_vec(&vec![empty.clone(), valid]).unwrap();
        let days = native_series(&raw, "waller", start(2026) + chrono::Duration::days(1)).unwrap();
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, start(2026) + chrono::Duration::days(1));
        empty["unavailable_precincts"] = serde_json::json!([]);
        let raw = serde_json::to_vec(&vec![empty]).unwrap();
        assert!(native_series(&raw, "waller", start(2026)).is_err());
    }

    fn roster_reference() -> Reference {
        serde_json::from_value(serde_json::json!({
            "id":"test", "name":"Test", "state_id":1, "groups":[],
            "exact_pairs":[], "presidential":{}, "references":{}
        }))
        .unwrap()
    }

    #[test]
    fn partial_native_workbook_retains_observed_dates_when_latest_not_posted() {
        let first = start(2026);
        let mut voters = Voters::new();
        insert(&mut voters, "valid-first", first, "001", false).unwrap();
        insert(
            &mut voters,
            "valid-third",
            first + chrono::Duration::days(2),
            "002",
            false,
        )
        .unwrap();
        let days = days_from(
            voters,
            &roster_reference(),
            2026,
            4,
            "official",
            "hash",
            "Scope.",
        )
        .unwrap();
        assert_eq!(
            days.iter().map(|d| d.date).collect::<Vec<_>>(),
            vec![first, first + chrono::Duration::days(2)]
        );
        assert!(days.iter().all(|d| !d.complete && !d.cumulative));
        assert!(
            days_from(
                Voters::new(),
                &roster_reference(),
                2026,
                4,
                "official",
                "hash",
                "Scope."
            )
            .is_err()
        );
        let mut roster = CountyRoster::default();
        roster.record("valid-first", first, "001", false).unwrap();
        roster
            .record("blank-affected", first, "002", false)
            .unwrap();
        roster.record("", first, "002", false).unwrap();
        let days = roster
            .days(&roster_reference(), 2026, 4, "official", "hash", "Scope.")
            .unwrap();
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].counts, Counts::from([("1".into(), 1)]));
        assert_eq!(days[0].unavailable_precincts, vec!["2"]);
    }

    #[test]
    fn montgomery_failed_date_cannot_poison_later_refresh_identity_or_quarantine() {
        let first = start(2026);
        let mut roster = CountyRoster::default();
        roster.record("earlier", first, "001", true).unwrap();
        let failed = b"VoteType,DateVoted,CountyElectionPrecinct,VUID\nE,10/20/2026,002,fresh\nE,10/20/2026,003,\nE,wrong-date,004,bad\n";
        assert!(montgomery_rows(failed, first + chrono::Duration::days(1), &mut roster).is_err());
        assert_eq!(roster.voters.len(), 1);
        assert!(roster.blank_identifiers.is_empty());
        montgomery_rows(
            b"VoteType,DateVoted,CountyElectionPrecinct,VUID\nE,10/21/2026,005,fresh\n",
            first + chrono::Duration::days(2),
            &mut roster,
        )
        .unwrap();
        assert_eq!(
            roster.voters["fresh"],
            (first + chrono::Duration::days(2), "5".into())
        );
    }

    #[test]
    fn travis_dated_workbook_validation_commits_only_successful_dates() {
        let first = start(2026);
        let make_rows = |when: NaiveDate, values: &[(&str, &str)]| {
            let serial = (when - NaiveDate::from_ymd_opt(1899, 12, 30).unwrap()).num_days();
            let mut rows = vec![
                vec!["Travis County Early Vote Roster".to_string()],
                vec![serial.to_string()],
                vec!["VUID".into(), "PCT".into()],
            ];
            rows.extend(
                values
                    .iter()
                    .map(|(id, p)| vec![id.to_string(), p.to_string()]),
            );
            rows
        };
        let mut voters = Voters::new();
        travis_rows(&make_rows(first, &[("earlier", "001")]), first, &mut voters).unwrap();
        let second = first + chrono::Duration::days(1);
        let failed = make_rows(second, &[("fresh", "002"), ("earlier", "001")]);
        assert!(travis_rows(&failed, second, &mut voters).is_err());
        assert_eq!(voters.len(), 1);
        let third = first + chrono::Duration::days(2);
        travis_rows(&make_rows(third, &[("fresh", "003")]), third, &mut voters).unwrap();
        let days = days_from(
            voters,
            &roster_reference(),
            2026,
            4,
            "official",
            "hash",
            "scope",
        )
        .unwrap();
        assert_eq!(days.len(), 2);
        assert_eq!(days[1].counts, Counts::from([("3".into(), 1)]));
    }

    #[test]
    fn tarrant_anchor_parser_requires_exact_cutoff_and_disables_daily_difference() {
        let mut reference = roster_reference();
        reference.id = "tarrant".into();
        reference.groups = vec![crate::Group {
            old: vec!["1".into()],
            new: vec!["1".into()],
        }];
        let through = start(2026) + chrono::Duration::days(7);
        let report = serde_json::json!({"county":"tarrant","date":through,"counts":{"1":10},
            "source":"https://www.tarrantcountytx.gov/content/dam/main/elections/2026/1126/ev_reports/Early_voting_in_person_report.zip",
            "sha256":"a".repeat(64),"retrieved_at":"2026-10-27T09:50:00Z","cumulative":true,
            "complete":true,"allow_daily_difference":false,"note":"Exact dated independent cutoff proof."});
        let parse = |value: &serde_json::Value| {
            tarrant_anchor(
                &serde_json::to_vec(&vec![value]).unwrap(),
                &reference,
                through,
            )
        };
        let valid = parse(&report).unwrap();
        assert!(!valid.complete);
        assert_eq!(valid.allow_daily_difference, Some(false));
        for (field, value) in [
            ("allow_daily_difference", serde_json::Value::Null),
            ("allow_daily_difference", true.into()),
            ("cumulative", false.into()),
            ("date", "2026-10-25".into()),
            ("source", "https://example.com".into()),
        ] {
            let mut invalid = report.clone();
            invalid[field] = value;
            assert!(parse(&invalid).is_err(), "{field}");
        }
    }

    #[test]
    fn montgomery_blank_ids_quarantine_only_the_affected_date_and_precinct() {
        let mut roster = CountyRoster::default();
        montgomery_rows(
            b"VoteType,DateVoted,CountyElectionPrecinct,VUID\nE,10/19/2026,001,a\nE,10/19/2026,002,b\nE,10/19/2026,002,b\nE,10/19/2026,1,\nE,10/19/2026,001,\nL,10/19/2026,002,\n",
            start(2026),
            &mut roster,
        )
        .unwrap();
        montgomery_rows(
            b"VoteType,DateVoted,CountyElectionPrecinct,VUID\nE,10/20/2026,002,b\nE,10/20/2026,001,c\n",
            start(2026) + chrono::Duration::days(1),
            &mut roster,
        )
        .unwrap();
        let days = roster
            .days(&roster_reference(), 2026, 2, "official", "hash", "Scope.")
            .unwrap();
        assert_eq!(days.len(), 2);
        assert_eq!(days[0].counts, Counts::from([("2".into(), 1)]));
        assert!(!days[0].counts.contains_key("1"));
        assert_eq!(days[0].unavailable_precincts, vec!["1"]);
        assert!(days[0].note.contains("2 rows with blank identifiers"));
        assert!(days[0].note.contains("1 date/precinct cells"));
        assert_eq!(days[1].counts, Counts::from([("1".into(), 1)]));
        assert!(!days[0].complete && !days[1].complete);
    }

    #[test]
    fn dallas_blank_ids_quarantine_full_cell_and_keep_other_dates() {
        let rows: Vec<Vec<String>> = [
            ["DATE VOTED", "PRECINCT", "SOS VOTERID", "IDNUMBER"],
            ["10/19/2026", "001", "a", ""],
            ["10/19/2026", "1", "", ""],
            ["10/19/2026", "002", "", "b"],
            ["10/19/2026", "002", "", "b"],
            ["10/20/2026", "001", "c", ""],
            ["10/21/2026", "002", "", ""],
        ]
        .into_iter()
        .map(|row| row.into_iter().map(String::from).collect())
        .collect();
        let days = dallas_rows(&rows, 2026, 2)
            .unwrap()
            .days(&roster_reference(), 2026, 2, "official", "hash", "Scope.")
            .unwrap();
        assert_eq!(days[0].counts, Counts::from([("2".into(), 1)]));
        assert!(!days[0].counts.contains_key("1"));
        assert_eq!(days[0].unavailable_precincts, vec!["1"]);
        assert!(days[0].note.contains("1 rows with blank identifiers"));
        assert_eq!(days[1].counts, Counts::from([("1".into(), 1)]));
        assert!(!days[1].note.contains("blank identifiers"));
    }

    #[test]
    fn dallas_rotating_native_csv_reuses_date_identity_and_quarantine_rules() {
        let raw = b"\xef\xbb\xbfFIRSTNAME,MIDDLENAME,LASTNAME,STREETNUMBER,STREETPREDIR,STREETNAME,STREETTYPE,STREETPOSTDIR,UNIT,CITY,ZIP,PRECINCT,PRECINCT_SUB,BALLOTSTYLE,BALLOT_PARTY,DATE_VOTED,VOTING_UNIT,VOTING_SUBUNIT,SOS_VOTERID\nSynthetic,,Person,,,,,,,,,001,,,NP,10/19/2026 7:01,,,1000000001\nSynthetic,,Blank,,,,,,,,,001,,,NP,10/19/2026,,,\nSynthetic,,Good,,,,,,,,,002,,,NP,10/19/2026,,,1000000002\nSynthetic,,Recover,,,,,,,,,,,,NP,10/20/2026,,,1000000003\nSynthetic,,Future,,,,,,,,,003,,,NP,10/30/2026,,,1000000004\n";
        let rows = dallas_source_rows(raw.to_vec()).unwrap();
        assert_eq!(rows[0], vec!["DATE VOTED", "PRECINCT", "SOS VOTERID"]);
        assert!(rows.iter().all(|r| r.len() == 3));
        let days = dallas_rows(&rows, 2026, 2)
            .unwrap()
            .days(&roster_reference(), 2026, 2, "official", "hash", "scope")
            .unwrap();
        assert_eq!(days[0].counts, Counts::from([("2".into(), 1)]));
        assert_eq!(days[0].unavailable_precincts, vec!["1"]);
        assert_eq!(days[1].counts, Counts::from([("UNASSIGNED".into(), 1)]));
        assert_eq!(
            dallas_blank_candidates(&rows, 2026, 2).unwrap(),
            BTreeMap::from([(
                start(2026) + chrono::Duration::days(1),
                BTreeSet::from(["1000000003".into()])
            )])
        );
    }

    #[test]
    fn dallas_source_rejects_html_partial_csv_and_foreign_schema() {
        for raw in [
            b"<html>Challenge</html>".as_slice(),
            b"DATE_VOTED,PRECINCT\n10/19/2026,1\n",
            b"FIRSTNAME,DATE_VOTED,PRECINCT,SOS_VOTERID\nSynthetic,10/19/2026,1,1000000001\n",
        ] {
            assert!(dallas_source_rows(raw.to_vec()).is_err());
        }
    }

    #[test]
    fn dallas_csv_requires_general_election_ballot_party_scope() {
        let csv = "FIRSTNAME,MIDDLENAME,LASTNAME,STREETNUMBER,STREETPREDIR,STREETNAME,STREETTYPE,STREETPOSTDIR,UNIT,CITY,ZIP,PRECINCT,PRECINCT_SUB,BALLOTSTYLE,BALLOT_PARTY,DATE_VOTED,VOTING_UNIT,VOTING_SUBUNIT,SOS_VOTERID\nSynthetic,,Person,,,,,,,,,001,,,NP,10/19/2026 7:01,,,1000000001\n";
        assert!(dallas_source_rows(csv.as_bytes().to_vec()).is_ok());
        for party in ["DEM", "REP", ""] {
            assert!(
                dallas_source_rows(csv.replace(",NP,", &format!(",{party},")).into_bytes())
                    .is_err()
            );
        }
    }

    #[test]
    fn dallas_csv_conflict_quarantines_both_whole_cells_without_weakening_workbooks() {
        let rows: Vec<Vec<String>> = [
            ["DATE VOTED", "PRECINCT", "SOS VOTERID"],
            ["10/21/2026 7:01", "4079", "1000000001"],
            ["10/21/2026 7:02", "4079", "1000000002"],
            ["10/21/2026 7:03", "4080", "1000000003"],
            ["10/28/2026 7:01", "3081", "1000000001"],
            ["10/28/2026 7:02", "3081", "1000000004"],
            ["10/28/2026 7:03", "3082", "1000000005"],
        ]
        .into_iter()
        .map(|row| row.into_iter().map(String::from).collect())
        .collect();
        assert!(dallas_rows(&rows, 2026, 11).is_err());
        let (roster, quarantine) = dallas_csv_roster(&rows, 2026, 11).unwrap();
        let third = start(2026) + chrono::Duration::days(2);
        let tenth = start(2026) + chrono::Duration::days(9);
        assert_eq!(
            quarantine,
            BTreeMap::from([
                (third, BTreeSet::from(["4079".into()])),
                (tenth, BTreeSet::from(["3081".into()]))
            ])
        );
        let days = roster
            .days(&roster_reference(), 2026, 11, "official", "hash", "scope")
            .unwrap();
        assert_eq!(days.len(), 2);
        assert_eq!(days[0].counts, Counts::from([("4080".into(), 1)]));
        assert_eq!(days[1].counts, Counts::from([("3082".into(), 1)]));
    }

    #[test]
    fn dallas_exact_identity_recovers_only_blank_precincts_in_real_roster_parser() {
        let rows: Vec<Vec<String>> = [
            ["DATE VOTED", "PRECINCT", "SOS VOTERID", "IDNUMBER"],
            ["10/19/2026", "001", "known", ""],
            ["10/19/2026", "", "recover", ""],
            ["10/19/2026", "", "foreign", ""],
            ["10/19/2026", "", "reused", ""],
            ["10/20/2026", "002", "reused", ""],
            ["10/19/2026", "003", "quarantined", ""],
            ["10/19/2026", "003", "", ""],
        ]
        .into_iter()
        .map(|row| row.into_iter().map(String::from).collect())
        .collect();
        // The known conflicting cross-day ID remains a hard native parser error.
        assert!(dallas_rows(&rows, 2026, 2).is_err());
        let candidates = dallas_blank_candidates(&rows, 2026, 1).unwrap();
        assert!(!candidates[&start(2026)].contains("reused"));
        let mut roster = dallas_rows(&rows[..5], 2026, 1).unwrap();
        let universe = BTreeSet::from(["1".into(), "2".into(), "3".into()]);
        let identities = BTreeMap::from([
            ("recover".into(), "2".into()),
            ("known".into(), "2".into()),
            ("foreign".into(), "UNKNOWN".into()),
        ]);
        assert_eq!(
            dallas_apply_identities(
                &mut roster,
                start(2026),
                &candidates[&start(2026)],
                &identities,
                &universe
            ),
            1
        );
        let days = roster
            .days(&roster_reference(), 2026, 1, "official", "hash", "Scope.")
            .unwrap();
        assert_eq!(
            days[0].counts,
            Counts::from([("1".into(), 1), ("2".into(), 1), ("UNASSIGNED".into(), 2)])
        );
        assert!(!days[0].complete);
    }

    #[test]
    fn dallas_enrichment_preserves_native_quarantine_and_unavailable_sos_counts() {
        let rows: Vec<Vec<String>> = [
            ["DATE VOTED", "PRECINCT", "SOS VOTERID", "IDNUMBER"],
            ["10/19/2026", "001", "known", ""],
            ["10/19/2026", "", "recover", ""],
            ["10/19/2026", "003", "quarantined", ""],
            ["10/19/2026", "003", "", ""],
        ]
        .into_iter()
        .map(|row| row.into_iter().map(String::from).collect())
        .collect();
        let candidates = dallas_blank_candidates(&rows, 2026, 1).unwrap();
        let universe = BTreeSet::from(["1".into(), "3".into()]);
        for identities in [
            BTreeMap::new(),
            BTreeMap::from([("recover".into(), "3".into())]),
        ] {
            let mut roster = dallas_rows(&rows, 2026, 1).unwrap();
            let assigned = dallas_apply_identities(
                &mut roster,
                start(2026),
                &candidates[&start(2026)],
                &identities,
                &universe,
            );
            let days = roster
                .days(&roster_reference(), 2026, 1, "official", "hash", "Scope.")
                .unwrap();
            assert_eq!(days[0].counts.get("1"), Some(&1));
            assert!(!days[0].counts.contains_key("3"));
            assert_eq!(days[0].unavailable_precincts, vec!["3"]);
            assert_eq!(
                days[0].counts.get("UNASSIGNED").copied().unwrap_or(0),
                u64::from(assigned == 0)
            );
        }
    }

    #[test]
    fn blank_only_dates_are_unavailable_and_never_reported_as_zero() {
        let mut roster = CountyRoster::default();
        roster.record("a", start(2026), "001", true).unwrap();
        roster.record("", start(2026), "001", true).unwrap();
        roster
            .record("b", start(2026) + chrono::Duration::days(1), "002", true)
            .unwrap();
        let days = roster
            .days(&roster_reference(), 2026, 2, "official", "hash", "Scope.")
            .unwrap();
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, start(2026) + chrono::Duration::days(1));
        assert!(!days[0].counts.is_empty());
        let mut only_blank = CountyRoster::default();
        only_blank.record("", start(2026), "001", false).unwrap();
        assert!(
            only_blank
                .days(&roster_reference(), 2026, 1, "official", "hash", "Scope.")
                .is_err()
        );
    }

    #[test]
    fn quarantining_blank_ids_does_not_relax_real_identity_conflicts() {
        let mut roster = CountyRoster::default();
        roster.record("a", start(2026), "001", true).unwrap();
        roster.record("", start(2026), "001", true).unwrap();
        assert!(roster.record("a", start(2026), "002", true).is_err());
        let mut strict = Voters::new();
        assert!(insert(&mut strict, "", start(2026), "001", true).is_err());
        let mut dallas = CountyRoster::default();
        dallas.record("a", start(2026), "001", false).unwrap();
        assert!(
            dallas
                .record("a", start(2026) + chrono::Duration::days(1), "001", false)
                .is_err()
        );
    }

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
    Ok(harris_counts(&bytes, year, n)?.into_iter().map(|(date, counts)| Daily { zero_evidence: Vec::new(), allow_daily_difference: None, unavailable_precincts: Vec::new(), complete: false,
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
fn nueces_counts(text: &str, n: u32) -> Result<CountyRoster> {
    ensure!((1..=12).contains(&n), "invalid Nueces cutoff");
    let first = start(2026);
    let last = first + chrono::Duration::days(i64::from(n - 1));
    let mut roster = CountyRoster::default();
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
            if at.is_none() || !possible_id {
                continue;
            }
        }
        let at = at.context("Nueces voter row type or layout changed")?;
        let mut fields = line[..at].split_whitespace();
        let precinct = fields.next().context("Nueces row has no precinct")?;
        let id = fields.next().context("Nueces row has no identifier")?;
        ensure!(
            !id.is_empty() && id.bytes().all(|c| c.is_ascii_digit()) && fields.next().is_some(),
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
            // A numeric ID outside the verified VUID layout is not a new
            // identity rule. Quarantine its exact date/precinct cell, retaining
            // all other observed cells through the shared roster mechanism.
            let verified_id = if (8..=10).contains(&id.len()) { id } else { "" };
            roster.record(verified_id, when, precinct, false)?;
        }
    }
    Ok(roster)
}
async fn nueces_native(client: &reqwest::Client, r: &Reference, n: u32) -> Result<Vec<Daily>> {
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
    nueces_counts(&text, n)?.days(r, 2026, n, &source, &hash,
        "Official Nueces County dedicated in-person daily roster PDF, rediscovered from the current county page. Every included row is Early Voted with an exact native date and unique verified 8–10 digit VUID. Numeric identifiers outside that layout are treated as unavailable identities and their entire date/precinct cell is quarantined; no identifier is padded or shortened. Raw PDF/text remain only in anonymous pipes/memory. Missing dates remain unavailable; native precinct labels absent from the 26P proxy remain unassigned. No votes are allocated to close SOS or map discrepancies.")
}

async fn nueces(client: &reqwest::Client, r: &Reference, n: u32) -> Result<Vec<Daily>> {
    let mut values = match nueces_native(client, r, n).await {
        Ok(values) => values,
        Err(error) => {
            eprintln!("Nueces native roster: {error:#}; trying independent dated SOS sources");
            Vec::new()
        }
    };
    let mut identities = BTreeSet::new();
    for offset in 0..n {
        let date = start(2026) + chrono::Duration::days(i64::from(offset));
        if !values.iter().any(|value| value.date == date) {
            match crate::fetch::fetch_state(client, r, date, &mut identities).await {
                Ok(value) => values.push(value),
                Err(error) => eprintln!("Nueces dated SOS {date}: {error:#}"),
            }
        }
    }
    ensure!(
        !values.is_empty(),
        "no usable Nueces native or dated SOS observations"
    );
    values.sort_by_key(|value| value.date);
    Ok(values)
}
#[cfg(test)]
mod nueces_tests {
    use super::*;
    fn dated(text: &str, n: u32) -> Result<Vec<Daily>> {
        let reference = serde_json::from_value(serde_json::json!({
            "id":"nueces", "name":"Nueces", "state_id":178, "groups":[],
            "exact_pairs":[], "presidential":{}, "references":{}
        }))?;
        nueces_counts(text, n)?.days(&reference, 2026, n, "official", "hash", "Scope.")
    }
    #[test]
    fn short_numeric_identity_and_unposted_date_do_not_reject_other_observations() {
        let text = "0001 1234567890 EXAMPLE Early Voted 10/19/2026\n0002 1234567 SHORT Early Voted 10/20/2026\n0002 1234567891 SAME CELL Early Voted 10/20/2026\n0003 1234567892 VALID Early Voted 10/20/2026\n";
        assert!(
            nueces_counts(text, 3).is_ok(),
            "one unusable identity cell and one unposted date must not discard independent observations"
        );
        let days = dated(text, 3).unwrap();
        assert_eq!(days.len(), 2);
        assert_eq!(days[0].counts, Counts::from([("1".into(), 1)]));
        assert_eq!(days[1].counts, Counts::from([("3".into(), 1)]));
        assert_eq!(days[1].unavailable_precincts, vec!["2"]);
        assert!(days.iter().all(|day| !day.complete && !day.cumulative));
    }
    #[test]
    fn discovers_only_in_person_link_and_parses_touching_name_type() {
        let html = r#"<a href="/mail">Early Voting Daily Roster (Mail)</a><a href="/home/showpublisheddocument/34763"><span>Early Voting Daily Roster (In Person)</span></a>"#;
        assert!(
            nueces_roster_link(html, "https://www.nuecesco.com/")
                .unwrap()
                .ends_with("/34763")
        );
        let text = "Roster for Early Voted\nPrecinct VUID Name Type Date\n0001 1234567890 EXAMPLE NAMEEarly Voted 10/19/2026\n0002 1234567891 OTHER NAME Early Voted 10/20/2026\n0003 12345678 SHORT ID Early Voted 10/20/2026\n0004 123456789 SHORT ID Early Voted 10/20/2026\n";
        let counts = dated(text, 2).unwrap();
        assert_eq!(counts[0].counts["1"], 1);
        assert_eq!(counts[1].counts["3"], 1);
        assert_eq!(counts[1].counts["4"], 1);
        assert_eq!(dated(text, 3).unwrap().len(), 2);
        assert!(
            nueces_counts(
                &format!("{text}0002 1234567890 SAME Early Voted 10/20/2026\n"),
                2
            )
            .is_err()
        );
        assert!(nueces_counts("0001 1234567890 EXAMPLE Mail Voted 10/19/2026", 1).is_err());
        let quarantined = dated(
            &format!("{text}0005 1234567 SHORT Early Voted 10/20/2026\n"),
            2,
        )
        .unwrap();
        assert_eq!(quarantined[1].unavailable_precincts, vec!["5"]);
        assert!(!quarantined[1].counts.contains_key("5"));
        assert!(
            nueces_counts(
                &format!("{text}0005 UNKNOWN NAME Early Voted 10/20/2026\n"),
                2
            )
            .is_err()
        );
    }
}
