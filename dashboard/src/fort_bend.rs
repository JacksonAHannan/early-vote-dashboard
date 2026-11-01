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

#[derive(Default)]
struct NativeRoster {
    counts: BTreeMap<NaiveDate, Counts>,
    reported_rows: BTreeMap<NaiveDate, u64>,
    unavailable_precincts: BTreeMap<NaiveDate, BTreeSet<String>>,
    invalid_rows: BTreeMap<NaiveDate, u64>,
}

fn rows_to_counts(rows: &[Vec<String>], year: i32) -> Result<NativeRoster> {
    let required = ["VUID", "Name", "Check-in Date", "Precinct"];
    let (offset, header) = rows
        .iter()
        .take(10)
        .enumerate()
        .find(|(_, row)| required.iter().all(|field| row.iter().any(|s| s == field)))
        .context("Fort Bend roster headers changed")?;
    ensure!(
        required
            .iter()
            .all(|field| header.iter().filter(|s| *s == field).count() == 1),
        "Fort Bend roster headers ambiguous"
    );
    let indexes: Vec<_> = required
        .iter()
        .map(|field| header.iter().position(|s| s == field).unwrap())
        .collect();
    let mut ids = BTreeSet::new();
    let mut result = NativeRoster::default();
    for row in rows.iter().skip(offset + 1) {
        if row.iter().all(|s| s.is_empty()) {
            continue;
        }
        let field = |i: usize| row.get(indexes[i]).map(String::as_str).unwrap_or("");
        // A date that cannot be located inside this election cannot be safely
        // isolated. Keep schema/date failures fatal even for an invalid identity.
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
        *result.reported_rows.entry(date).or_default() += 1;
        // Share one identity set across the entire workbook. A duplicate can
        // affect a different date/precinct and must never be admitted twice.
        if !field(0).is_empty() {
            ensure!(
                ids.insert(field(0).to_string()),
                "Fort Bend duplicate voter identifier"
            );
        }
        if !(8..=10).contains(&field(0).len())
            || !field(0).bytes().all(|b| b.is_ascii_digit())
            || field(1).is_empty()
        {
            *result.invalid_rows.entry(date).or_default() += 1;
            result
                .unavailable_precincts
                .entry(date)
                .or_default()
                .insert(precinct);
            continue;
        }
        *result
            .counts
            .entry(date)
            .or_default()
            .entry(precinct)
            .or_default() += 1;
    }
    // Remove the complete implicated cell, including valid rows encountered
    // before or after its invalid row. It remains unknown rather than zero.
    for (date, cells) in &result.unavailable_precincts {
        if let Some(counts) = result.counts.get_mut(date) {
            counts.retain(|precinct, _| !cells.contains(precinct));
        }
    }
    ensure!(
        result.counts.values().any(|counts| !counts.is_empty()),
        "Fort Bend empty usable voter roster"
    );
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
    reported_rows: &BTreeMap<NaiveDate, u64>,
    year: i32,
    n: u32,
) -> Result<BTreeMap<NaiveDate, String>> {
    ensure!(
        (1..=12).contains(&n),
        "Fort Bend invalid requested day count"
    );
    let mut notes = BTreeMap::new();
    let mut rejected = Vec::new();
    for i in 0..n {
        let date = start(year) + Duration::days(i64::from(i));
        // A missing date remains unavailable; an existing dated precinct subset
        // is useful even when the whole-county control exposes omitted ballots.
        let Some(counts) = roster.get(&date) else {
            continue;
        };
        let note = (|| -> Result<String> {
            let actual: u64 = counts.values().sum();
            let native_rows = reported_rows.get(&date).copied().unwrap_or(actual);
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
                    native_rows <= *control || native_rows.abs_diff(*control) <= 1,
                    "Fort Bend roster exceeds official in-person daily control on {date}: {native_rows} records versus {control} ballots"
                );
                format!(
                    "Daily roster {actual}; county in-person control {control}; control minus roster {}",
                    i128::from(*control) - i128::from(actual)
                )
            } else {
                format!("Daily roster {actual}; independent daily county control unavailable")
            };
            // Only accepted dates can contribute to available cumulative votes.
            // A rejected older date is unavailable, not zero and not a valid total.
            let cumulative: u64 = actual
                + notes
                    .keys()
                    .map(|day| roster[day].values().sum::<u64>())
                    .sum::<u64>();
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
            Ok(format!(
                "{daily}. {cumulative_note}. Reported precinct subset; county-wide completion is not established. Missing precincts and dates are not zero and are never allocated."
            ))
        })();
        match note {
            Ok(note) => {
                notes.insert(date, note);
            }
            Err(error) => {
                let failure = format!("{date}: {error:#}");
                eprintln!("Fort Bend dated native observation withheld: {failure}");
                rejected.push(failure);
            }
        }
    }
    ensure!(
        !notes.is_empty(),
        "Fort Bend roster contains no valid requested dated observations; {}",
        rejected.join("; ")
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
    let mut roster = rows_to_counts(&rows, year)?;
    let controls = control_totals(&pdf_text(control_bytes).await?, year)?;
    let notes = availability_notes(&roster.counts, &controls, &roster.reported_rows, year, n)?;
    let retrieved = Utc::now().to_rfc3339();
    Ok(notes.into_iter().map(|(date, availability)| {
        let counts = roster.counts.remove(&date).unwrap();
        let unavailable_precincts: Vec<_> = roster.unavailable_precincts
            .remove(&date).unwrap_or_default().into_iter().collect();
        let reported = roster.reported_rows[&date];
        let source_note = format!("Native source rows {reported}; county control minus native source rows {}.",
            controls.get(&date).map(|control| (i128::from(*control) - i128::from(reported)).to_string())
                .unwrap_or_else(|| "unavailable".into()));
        let quarantine = if unavailable_precincts.is_empty() { String::new() } else {
            format!(" Invalid-row quarantine: {} rows with an unusable VUID or name implicate {} complete date/precinct cells on {date}; {} source rows withheld with those cells. Cells remain unavailable, never zero.",
                roster.invalid_rows[&date], unavailable_precincts.len(), reported - counts.values().sum::<u64>())
        };
        Daily {
            allow_daily_difference: None, zero_evidence: Vec::new(),
            unavailable_precincts, complete: false,
            county: r.id.clone(), date, counts,
            source: roster_url.clone(), sha256: roster_sha.clone(), retrieved_at: retrieved.clone(),
            note: format!("Native in-person residence-precinct roster. {source_note}{quarantine} {availability} Independent personal-appearance report: {control_url} (SHA256 {control_sha}). No mail ballots."),
            cumulative: false,
        }
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
        assert_eq!(parsed.counts[&d]["1A"], 1);
        assert_eq!(parsed.counts[&d]["UNASSIGNED"], 1);
        let mut duplicate = rows();
        duplicate.push(duplicate[1].clone());
        assert!(rows_to_counts(&duplicate, 2026).is_err());
        let mut wrong = rows();
        wrong[1][2] = "2024-10-21".into();
        assert!(rows_to_counts(&wrong, 2026).is_err());
    }
    #[test]
    fn blank_identity_withholds_only_its_entire_dated_precinct_cell() {
        let mut source = rows();
        source[2] = vec!["", "Synthetic invalid", "2026-10-30", "002"]
            .into_iter()
            .map(str::to_string)
            .collect();
        source.push(
            vec!["34567890", "Synthetic same cell", "2026-10-30", "002"]
                .into_iter()
                .map(str::to_string)
                .collect(),
        );
        source.push(
            vec!["45678901", "Synthetic unaffected", "2026-10-30", "003"]
                .into_iter()
                .map(str::to_string)
                .collect(),
        );
        let parsed = rows_to_counts(&source, 2026)
            .expect("one blank identity must not reject unaffected dates and cells");
        assert_eq!(parsed.counts[&start(2026)]["1A"], 1);
        let final_day = start(2026) + Duration::days(11);
        assert_eq!(parsed.counts[&final_day]["3"], 1);
        assert!(
            !parsed.counts[&final_day].contains_key("2"),
            "the entire affected precinct cell must remain unavailable"
        );
        assert_eq!(
            parsed.unavailable_precincts[&final_day],
            BTreeSet::from(["2".into()])
        );
        assert_eq!(parsed.reported_rows[&final_day], 3);
        assert_eq!(parsed.invalid_rows[&final_day], 1);
    }

    #[test]
    fn reported_subset_survives_with_precise_daily_and_cumulative_gap() {
        let roster = rows_to_counts(&rows(), 2026).unwrap().counts;
        let controls = control_totals("November 3, 2026 General Election\nEarly Voting by Personal Appearance\nGrand Totals\nDATE\nMon 10/19/26 3\nTOTAL 3\n", 2026).unwrap();
        let notes = availability_notes(&roster, &controls, &BTreeMap::new(), 2026, 2).unwrap();
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
        let mut roster = rows_to_counts(&rows(), 2026).unwrap().counts;
        roster
            .get_mut(&start(2026))
            .unwrap()
            .insert("100".into(), 3);
        assert!(
            availability_notes(
                &roster,
                &BTreeMap::from([(start(2026), 2)]),
                &BTreeMap::new(),
                2026,
                1
            )
            .is_err()
        );
        assert!(
            availability_notes(
                &roster,
                &BTreeMap::from([(start(2026), 0)]),
                &BTreeMap::new(),
                2026,
                1
            )
            .is_err()
        );
        let notes =
            availability_notes(&roster, &BTreeMap::new(), &BTreeMap::new(), 2026, 1).unwrap();
        assert!(notes[&start(2026)].contains("independent daily county control unavailable"));
    }
    #[test]
    fn one_invalid_control_date_does_not_discard_other_native_dates() {
        let first = start(2026);
        let second = first + Duration::days(1);
        let roster = BTreeMap::from([
            (first, Counts::from([("101".to_string(), 5)])),
            (second, Counts::from([("102".to_string(), 7)])),
        ]);
        // An out-of-sync zero on the older date must not block a newly posted
        // valid date; that rejected date contributes no accepted cumulative votes.
        let notes = availability_notes(
            &roster,
            &BTreeMap::from([(first, 0), (second, 10)]),
            &BTreeMap::new(),
            2026,
            2,
        )
        .expect("one conflicted date must not reject the newer usable publication");
        assert_eq!(notes.keys().copied().collect::<Vec<_>>(), vec![second]);
        assert!(notes[&second].contains("Available roster cumulative 7"));
        assert!(notes[&second].contains("county-wide completion is not established"));
        // A bad newest date likewise cannot revoke an earlier validated date.
        let notes = availability_notes(
            &roster,
            &BTreeMap::from([(first, 5), (second, 2)]),
            &BTreeMap::new(),
            2026,
            2,
        )
        .unwrap();
        assert_eq!(notes.keys().copied().collect::<Vec<_>>(), vec![first]);
        // A date's own inconsistent cumulative proof is still withheld.
        let notes = availability_notes(
            &roster,
            &BTreeMap::from([(first, 4), (second, 6)]),
            &BTreeMap::new(),
            2026,
            2,
        )
        .unwrap();
        assert_eq!(notes.keys().copied().collect::<Vec<_>>(), vec![first]);
    }

    #[test]
    fn cell_quarantine_preserves_cross_date_identity_and_election_guards() {
        let mut source = rows();
        // Two different dates may not reuse a nonblank identity, even if one
        // row will be quarantined for another defect.
        let mut reused = source[1].clone();
        reused[1] = String::new();
        reused[2] = "2026-10-30".into();
        source.push(reused);
        assert!(rows_to_counts(&source, 2026).is_err());
        for bad_date in ["", "not a date", "2024-10-21", "2026-10-31"] {
            let mut source = rows();
            source[2][0] = String::new();
            source[2][2] = bad_date.into();
            assert!(rows_to_counts(&source, 2026).is_err());
        }
        let mut ambiguous = rows();
        ambiguous[0].push("VUID".into());
        assert!(rows_to_counts(&ambiguous, 2026).is_err());
    }

    #[test]
    fn invalid_named_or_malformed_identity_cells_are_removed_in_both_row_orders() {
        for invalid in ["", "short", "1234567", "12345678901"] {
            for bad_first in [true, false] {
                let mut source = rows();
                source[2][0] = invalid.into();
                source[2][3] = "001A".into();
                if bad_first {
                    source.swap(1, 2);
                }
                // A different valid cell must survive, while both rows of 1A
                // are withheld regardless of where the invalid row occurs.
                source.push(
                    vec!["34567890", "Synthetic valid", "2026-10-19", "002"]
                        .into_iter()
                        .map(str::to_string)
                        .collect(),
                );
                let parsed = rows_to_counts(&source, 2026).unwrap();
                assert_eq!(parsed.counts[&start(2026)], Counts::from([("2".into(), 1)]));
                assert_eq!(
                    parsed.unavailable_precincts[&start(2026)],
                    BTreeSet::from(["1A".into()])
                );
            }
        }
        let mut source = rows();
        source[1][1] = String::new();
        let parsed = rows_to_counts(&source, 2026).unwrap();
        assert!(!parsed.counts[&start(2026)].contains_key("1A"));
        assert_eq!(parsed.invalid_rows[&start(2026)], 1);
        // If every cell is invalid, no dated zero observation can escape.
        source[2][1] = String::new();
        assert!(rows_to_counts(&source, 2026).is_err());
    }

    #[test]
    fn quarantine_cannot_conceal_an_original_roster_control_excess() {
        let first = start(2026);
        let counts = BTreeMap::from([(first, Counts::from([("101".into(), 1)]))]);
        assert!(
            availability_notes(
                &counts,
                &BTreeMap::from([(first, 3)]),
                &BTreeMap::from([(first, 5)]),
                2026,
                1
            )
            .is_err()
        );
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
