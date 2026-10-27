//! Native Fort Bend reported residence-precinct observations, with independent coverage caveats.
//! Voter rows remain in memory; only anonymous precinct counts leave this module.
use crate::{Counts, Daily, Reference, fetch::download, normalize, start};
use anyhow::{Context, Result, bail, ensure};
use calamine::{Data, Reader, open_workbook_auto_from_rs};
use chrono::{Duration, NaiveDate, Utc};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Cursor,
    process::Stdio,
};
use tokio::io::AsyncWriteExt;

const PAGE: &str = "https://www.fortbendcountytx.gov/government/departments/elections-voter-registration/early-voting-statistics";

pub fn supports(year: i32) -> bool {
    year == 2026
}

fn text(html: &str) -> String {
    let mut result = String::new();
    let mut inside = false;
    for c in html.chars() {
        match c {
            '<' => inside = true,
            '>' => {
                inside = false;
                result.push(' ');
            }
            _ if !inside => result.push(c),
            _ => (),
        }
    }
    result
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn link(html: &str, label: &str, year: i32, extension: &str) -> Result<String> {
    let mut found = Vec::new();
    for anchor in html.split("<a").skip(1) {
        let Some((attributes, remainder)) = anchor.split_once('>') else {
            continue;
        };
        let Some((content, _)) = remainder.split_once("</a>") else {
            continue;
        };
        let visible = text(content);
        if visible != label
            && visible != format!("{label} [Excel]")
            && visible != format!("{label} [PDF]")
        {
            continue;
        }
        let Some((_, value)) = attributes.split_once("href=") else {
            continue;
        };
        let Some(quote) = value.chars().next() else {
            continue;
        };
        ensure!(
            matches!(quote, '\'' | '"'),
            "Fort Bend unquoted source link"
        );
        let Some((href, _)) = value[1..].split_once(quote) else {
            continue;
        };
        let url = reqwest::Url::parse(PAGE)?.join(&href.replace("&amp;", "&"))?;
        ensure!(
            url.scheme() == "https"
                && url.host_str() == Some("www.fortbendcountytx.gov")
                && url.path().contains(&format!("/statistics/{year}/"))
                && url.path().to_lowercase().ends_with(extension),
            "Fort Bend source link changed election or host"
        );
        found.push(url.to_string());
    }
    ensure!(
        found.len() == 1,
        "Fort Bend source link missing or ambiguous: {label}"
    );
    Ok(found.remove(0))
}

fn value(cell: &Data) -> String {
    match cell {
        Data::Float(n) if n.fract() == 0.0 => format!("{n:.0}"),
        Data::DateTime(n) => n.as_f64().to_string(),
        _ => cell.to_string().trim().to_string(),
    }
}
fn day(value: &str) -> Result<NaiveDate> {
    if let Ok(serial) = value.parse::<f64>() {
        ensure!(
            serial.is_finite() && (40000.0..60000.0).contains(&serial),
            "Fort Bend invalid Excel date"
        );
        return Ok(
            NaiveDate::from_ymd_opt(1899, 12, 30).unwrap() + Duration::days(serial.floor() as i64)
        );
    }
    for format in [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ] {
        if let Ok(d) = NaiveDate::parse_from_str(value, format) {
            return Ok(d);
        }
    }
    bail!("Fort Bend unrecognized check-in date")
}

fn rows_to_counts(rows: &[Vec<String>], year: i32) -> Result<BTreeMap<NaiveDate, Counts>> {
    let required = ["VUID", "Name", "Check-in Date", "Precinct"];
    let (offset, header) = rows
        .iter()
        .take(10)
        .enumerate()
        .find(|(_, row)| required.iter().all(|field| row.iter().any(|s| s == field)))
        .context("Fort Bend roster headers changed")?;
    let indexes: Vec<_> = required
        .iter()
        .map(|field| header.iter().position(|s| s == field).unwrap())
        .collect();
    let mut ids = BTreeSet::new();
    let mut result: BTreeMap<NaiveDate, Counts> = BTreeMap::new();
    for row in rows.iter().skip(offset + 1) {
        if row.iter().all(|s| s.is_empty()) {
            continue;
        }
        let field = |i: usize| row.get(indexes[i]).map(String::as_str).unwrap_or("");
        ensure!(
            (8..=10).contains(&field(0).len()) && field(0).bytes().all(|b| b.is_ascii_digit()),
            "Fort Bend invalid voter identifier"
        );
        ensure!(
            ids.insert(field(0).to_string()),
            "Fort Bend duplicate voter identifier"
        );
        ensure!(!field(1).is_empty(), "Fort Bend blank voter name");
        let date = day(field(2))?;
        ensure!(
            date >= start(year) && date < start(year) + Duration::days(12),
            "Fort Bend roster contains another election date"
        );
        let precinct = normalize(field(3));
        let precinct = if precinct.is_empty() {
            "UNASSIGNED".into()
        } else {
            precinct
        };
        *result.entry(date).or_default().entry(precinct).or_default() += 1;
    }
    ensure!(!ids.is_empty(), "Fort Bend empty voter roster");
    Ok(result)
}

fn control_totals(text: &str, year: i32) -> Result<BTreeMap<NaiveDate, u64>> {
    ensure!(
        text.contains(&format!("November 3, {year} General Election"))
            && text.contains("Early Voting by Personal Appearance"),
        "Fort Bend control election or method changed"
    );
    let sections: Vec<_> = text.match_indices("Grand Totals").collect();
    ensure!(
        sections.len() == 1,
        "Fort Bend control Grand Totals missing or ambiguous"
    );
    let mut totals = BTreeMap::new();
    for line in text[sections[0].0..].lines().skip(1) {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.first() == Some(&"TOTAL") {
            break;
        }
        if fields.len() != 3 {
            continue;
        }
        let Ok(date) = NaiveDate::parse_from_str(fields[1], "%m/%d/%y") else {
            continue;
        };
        let total: u64 = fields[2]
            .replace(',', "")
            .parse()
            .context("Fort Bend invalid daily control")?;
        ensure!(
            date >= start(year) && date < start(year) + Duration::days(12),
            "Fort Bend control dates outside election"
        );
        ensure!(
            totals.insert(date, total).is_none(),
            "Fort Bend duplicate control date"
        );
    }
    ensure!(!totals.is_empty(), "Fort Bend empty daily controls");
    Ok(totals)
}
fn availability_notes(
    roster: &BTreeMap<NaiveDate, Counts>,
    controls: &BTreeMap<NaiveDate, u64>,
    year: i32,
    n: u32,
) -> Result<BTreeMap<NaiveDate, String>> {
    ensure!(
        (1..=12).contains(&n),
        "Fort Bend invalid requested day count"
    );
    let mut notes = BTreeMap::new();
    for i in 0..n {
        let date = start(year) + Duration::days(i64::from(i));
        // A missing date remains unavailable; an existing dated precinct subset
        // is useful even when the whole-county control exposes omitted ballots.
        let Some(counts) = roster.get(&date) else {
            continue;
        };
        let actual: u64 = counts.values().sum();
        ensure!(
            actual > 0,
            "Fort Bend empty dated roster cannot establish a reported zero"
        );
        let daily = if let Some(control) = controls.get(&date) {
            ensure!(
                *control > 0,
                "Fort Bend dated roster conflicts with a zero/future county control on {date}"
            );
            ensure!(
                actual <= *control || actual.abs_diff(*control) <= 1,
                "Fort Bend roster exceeds official in-person daily control on {date}: {actual} records versus {control} ballots"
            );
            format!(
                "Daily roster {actual}; county in-person control {control}; control minus roster {}",
                i128::from(*control) - i128::from(actual)
            )
        } else {
            format!("Daily roster {actual}; independent daily county control unavailable")
        };
        let cumulative: u64 = roster
            .iter()
            .filter(|(day, _)| **day <= date)
            .map(|(_, counts)| counts.values().sum::<u64>())
            .sum();
        let mut cumulative_control = Some(0_u64);
        for j in 0..=i {
            let earlier = start(year) + Duration::days(i64::from(j));
            cumulative_control = cumulative_control
                .zip(controls.get(&earlier))
                .map(|(sum, value)| sum + value);
        }
        let cumulative_note = match cumulative_control {
            Some(control) => {
                ensure!(
                    cumulative <= control || cumulative.abs_diff(control) <= 1,
                    "Fort Bend reported cumulative roster exceeds county control on {date}"
                );
                format!(
                    "Available roster cumulative {cumulative}; county cumulative control {control}; control minus available roster {}",
                    i128::from(control) - i128::from(cumulative)
                )
            }
            None => format!(
                "Available roster cumulative {cumulative}; independent cumulative county control unavailable"
            ),
        };
        notes.insert(date, format!("{daily}. {cumulative_note}. Reported precinct subset; county-wide completion is not established. Missing precincts and dates are not zero and are never allocated."));
    }
    ensure!(
        !notes.is_empty(),
        "Fort Bend roster contains no requested dated observations"
    );
    Ok(notes)
}

async fn pdf_text(bytes: Vec<u8>) -> Result<String> {
    let mut child = tokio::process::Command::new("pdftotext")
        .args(["-layout", "-", "-"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .context("start Fort Bend control PDF decoder")?;
    let mut input = child.stdin.take().unwrap();
    input.write_all(&bytes).await?;
    drop(input);
    let output = tokio::time::timeout(std::time::Duration::from_secs(90), child.wait_with_output())
        .await??;
    ensure!(
        output.status.success(),
        "Fort Bend control PDF decoding failed"
    );
    Ok(String::from_utf8(output.stdout)?)
}

pub async fn collect(
    client: &reqwest::Client,
    r: &Reference,
    year: i32,
    n: u32,
) -> Result<Vec<Daily>> {
    ensure!(
        supports(year) && r.id == "fortbend",
        "Fort Bend native adapter does not support this county/election"
    );
    let html = String::from_utf8(download(client, PAGE, None).await?)?;
    let roster_url = link(&html, "EV", year, ".xlsx")?;
    let control_url = link(
        &html,
        "Early Voting by Personal Appearance Statistics",
        year,
        ".pdf",
    )?;
    let (bytes, control_bytes) = tokio::try_join!(
        download(client, &roster_url, None),
        download(client, &control_url, None)
    )?;
    let roster_sha = format!("{:x}", Sha256::digest(&bytes));
    let control_sha = format!("{:x}", Sha256::digest(&control_bytes));
    let mut book = open_workbook_auto_from_rs(Cursor::new(bytes))?;
    ensure!(
        book.sheet_names().len() == 1,
        "Fort Bend roster worksheet scope changed"
    );
    let range = book
        .worksheet_range_at(0)
        .context("Fort Bend missing worksheet")??;
    let rows: Vec<_> = range
        .rows()
        .map(|row| row.iter().map(value).collect())
        .collect();
    let mut counts = rows_to_counts(&rows, year)?;
    let controls = control_totals(&pdf_text(control_bytes).await?, year)?;
    let notes = availability_notes(&counts, &controls, year, n)?;
    let retrieved = Utc::now().to_rfc3339();
    Ok(notes.into_iter().map(|(date, availability)| Daily {
        allow_daily_difference: None,
            zero_evidence: Vec::new(),
        unavailable_precincts: Vec::new(), complete: false,
        county: r.id.clone(), date, counts: counts.remove(&date).unwrap(),
        source: roster_url.clone(), sha256: roster_sha.clone(), retrieved_at: retrieved.clone(),
        note: format!("Native in-person residence-precinct roster. {availability} Independent personal-appearance report: {control_url} (SHA256 {control_sha}). No mail ballots."),
        cumulative: false,
    }).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn rows() -> Vec<Vec<String>> {
        vec![
            vec!["VUID", "Name", "Check-in Date", "Precinct"]
                .into_iter()
                .map(str::to_string)
                .collect(),
            vec!["12345678", "Synthetic A", "2026-10-19", "001A"]
                .into_iter()
                .map(str::to_string)
                .collect(),
            vec!["2345678901", "Synthetic B", "2026-10-19", ""]
                .into_iter()
                .map(str::to_string)
                .collect(),
        ]
    }
    #[test]
    fn native_dates_ids_and_unassigned_are_preserved() {
        let parsed = rows_to_counts(&rows(), 2026).unwrap();
        let d = start(2026);
        assert_eq!(parsed[&d]["1A"], 1);
        assert_eq!(parsed[&d]["UNASSIGNED"], 1);
        let mut duplicate = rows();
        duplicate.push(duplicate[1].clone());
        assert!(rows_to_counts(&duplicate, 2026).is_err());
        let mut wrong = rows();
        wrong[1][2] = "2024-10-21".into();
        assert!(rows_to_counts(&wrong, 2026).is_err());
    }
    #[test]
    fn reported_subset_survives_with_precise_daily_and_cumulative_gap() {
        let roster = rows_to_counts(&rows(), 2026).unwrap();
        let controls = control_totals("November 3, 2026 General Election\nEarly Voting by Personal Appearance\nGrand Totals\nDATE\nMon 10/19/26 3\nTOTAL 3\n", 2026).unwrap();
        let notes = availability_notes(&roster, &controls, 2026, 2).unwrap();
        assert_eq!(notes.len(), 1); // Missing day two is not an invented zero.
        assert!(
            notes[&start(2026)]
                .contains("Daily roster 2; county in-person control 3; control minus roster 1")
        );
        assert!(notes[&start(2026)].contains("control minus available roster 1"));
        assert!(notes[&start(2026)].contains("completion is not established"));
        assert!(control_totals("November 3, 2026 General Election\nEarly Voting by Mail\nGrand Totals\nMon 10/19/26 2\nTOTAL 2", 2026).is_err());
    }
    #[test]
    fn unexplained_excess_and_future_zero_are_rejected() {
        let mut roster = rows_to_counts(&rows(), 2026).unwrap();
        roster
            .get_mut(&start(2026))
            .unwrap()
            .insert("100".into(), 3);
        assert!(availability_notes(&roster, &BTreeMap::from([(start(2026), 2)]), 2026, 1).is_err());
        assert!(availability_notes(&roster, &BTreeMap::from([(start(2026), 0)]), 2026, 1).is_err());
        let notes = availability_notes(&roster, &BTreeMap::new(), 2026, 1).unwrap();
        assert!(notes[&start(2026)].contains("independent daily county control unavailable"));
    }
    #[test]
    fn links_are_discovered_and_scoped_to_current_county_election() {
        let html = "<a href='/sites/default/files/statistics/2026/EV_1024.xlsx'>EV</a>";
        assert!(
            link(html, "EV", 2026, ".xlsx")
                .unwrap()
                .ends_with("EV_1024.xlsx")
        );
        assert!(link(html, "EV", 2024, ".xlsx").is_err());
        assert!(
            link(
                "<a href='https://example.com/statistics/2026/a.xlsx'>EV</a>",
                "EV",
                2026,
                ".xlsx"
            )
            .is_err()
        );
    }
}
