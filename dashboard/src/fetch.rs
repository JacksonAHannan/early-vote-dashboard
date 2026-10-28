// Official downloads are decoded in memory. Only precinct counts and provenance reach disk.
use crate::*;
use anyhow::{Context, bail};
use base64::Engine;
use sha2::{Digest, Sha256};
use std::{path::Path, process::Stdio};
use tokio::io::AsyncWriteExt;

pub async fn download(
    client: &reqwest::Client,
    url: &str,
    form: Option<&BTreeMap<String, String>>,
) -> Result<Vec<u8>> {
    if let Some(bytes) = native_download(client, url, form).await? {
        return Ok(bytes);
    }
    compatible_download(url, form).await
}

async fn native_download(
    client: &reqwest::Client,
    url: &str,
    form: Option<&BTreeMap<String, String>>,
) -> Result<Option<Vec<u8>>> {
    // Treat receiving headers and reading the complete body as one attempt. A
    // successful status alone must not bypass recovery for a stalled/truncated body.
    for attempt in 0..2 {
        let request = if let Some(fields) = form {
            client.post(url).form(fields)
        } else {
            client.get(url)
        };
        let result: std::result::Result<_, reqwest::Error> = async {
            let response = request.send().await?;
            if matches!(response.status().as_u16(), 202 | 403) {
                return Ok(None);
            }
            let bytes = response.error_for_status()?.bytes().await?;
            Ok(Some(bytes))
        }
        .await;
        match result {
            Ok(Some(bytes)) => return Ok(Some(bytes.to_vec())),
            Ok(None) => break, // Browser challenge: use the compatible transport now.
            Err(error)
                if error.is_status()
                    && !error.status().is_some_and(|s| {
                        s.is_server_error() || s == reqwest::StatusCode::TOO_MANY_REQUESTS
                    }) =>
            {
                bail!("official download HTTP {}", error.status().unwrap());
            }
            Err(_) if attempt == 0 => {
                tokio::time::sleep(std::time::Duration::from_millis(250)).await;
            }
            Err(_) => break,
        }
    }
    Ok(None)
}

async fn compatible_download(
    url: &str,
    form: Option<&BTreeMap<String, String>>,
) -> Result<Vec<u8>> {
    // Some county/state sites require browser TLS. This transport has no data logic.
    let mut child = tokio::process::Command::new("uv")
        .args([
            "run",
            "--quiet",
            "--with",
            "curl-cffi==0.16.3",
            "--with",
            "playwright==1.64.1",
            "python",
        ])
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/transport.py"))
        .stdin(Stdio::piped())
        .kill_on_drop(true)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("start TLS transport; install uv and curl-cffi")?;
    let body = serde_json::to_vec(&serde_json::json!({"url":url,"form":form}))?;
    let mut input = child.stdin.take().unwrap();
    input.write_all(&body).await?;
    drop(input);
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(240),
        child.wait_with_output(),
    )
    .await??;
    ensure!(
        output.status.success(),
        "TLS transport failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(output.stdout)
}

pub fn state_csv(bytes: &[u8]) -> Result<Counts> {
    parse_state(bytes, &mut BTreeSet::new())
}
fn parse_state(bytes: &[u8], across_days: &mut BTreeSet<String>) -> Result<Counts> {
    parse_state_with_ambiguity(bytes, across_days, false, 0)
}
fn parse_state_with_ambiguity(
    bytes: &[u8],
    across_days: &mut BTreeSet<String>,
    tarrant_day_one: bool,
    identical_row_policy: usize,
) -> Result<Counts> {
    let mut reader = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(bytes);
    let headers = reader.headers()?.clone();
    let index = |name: &str| {
        headers
            .iter()
            .position(|h| h.trim_start_matches('\u{feff}') == name)
            .with_context(|| format!("missing roster field {name}"))
    };
    let method = index("VOTING_METHOD")?;
    let precinct = index("PRECINCT")?;
    let id = index("ID_VOTER")?;
    let name = if tarrant_day_one {
        Some(index("VOTER_NAME")?)
    } else {
        None
    };
    let mut identities: BTreeMap<String, (String, String)> = BTreeMap::new();
    let mut conflicts = 0;
    let mut repeated_rows = 0;
    let mut original_rows: BTreeMap<String, csv::StringRecord> = BTreeMap::new();
    let mut voters = BTreeSet::new();
    let mut counts = Counts::new();
    let mut records = 0;
    for row in reader.records() {
        let row = row?;
        records += 1;
        ensure!(
            !row[id].trim().is_empty(),
            "blank voter identifier in state export"
        );
        match &row[method] {
            "IN-PERSON" => {
                if identical_row_policy > 0 {
                    if let Some(original) = original_rows.get(&row[id]) {
                        ensure!(
                            original == &row && repeated_rows < identical_row_policy,
                            "unvalidated repeated in-person row"
                        );
                        repeated_rows += 1;
                        continue;
                    }
                    original_rows.insert(row[id].to_string(), row.clone());
                }
                let p = normalize(&row[precinct]);
                let p = if p.is_empty() { "UNASSIGNED".into() } else { p };
                if let Some(name) = name {
                    ensure!(
                        !row[name].is_empty(),
                        "Tarrant missing voter name for identity validation"
                    );
                    if let Some((prior_name, prior_precinct)) = identities.get_mut(&row[id]) {
                        ensure!(
                            prior_name == &row[name] && *prior_precinct != p && conflicts == 0,
                            "Tarrant identifier ambiguity changed; source review required"
                        );
                        let prior = counts
                            .get_mut(&*prior_precinct)
                            .context("missing original precinct count")?;
                        *prior -= 1;
                        if *prior == 0 {
                            counts.remove(&*prior_precinct);
                        }
                        *counts.entry("UNASSIGNED".into()).or_default() += 1;
                        *prior_precinct = "UNASSIGNED".into();
                        conflicts += 1;
                        continue;
                    }
                    identities.insert(row[id].to_string(), (row[name].to_string(), p.clone()));
                }
                // A surrendered mail ballot can appear beside a valid in-person
                // record. Uniqueness applies to the included voting method.
                ensure!(
                    voters.insert(row[id].to_string()),
                    "duplicate voter identifier in state export"
                );
                ensure!(
                    !across_days.contains(&row[id]),
                    "repeated in-person identifier across state daily exports"
                );
                *counts.entry(p).or_default() += 1;
            }
            "MAIL-IN" => {}
            _ => bail!("unrecognized voting method in state export"),
        }
    }
    ensure!(
        !counts.is_empty(),
        "no in-person records; absence is not confirmed zero turnout"
    );
    ensure!(
        records > 0,
        "empty roster; missing data is not zero turnout"
    );
    // Commit only a fully validated date. A rejected report must not reserve IDs
    // and turn unrelated later dates into false cross-date duplicate failures.
    across_days.extend(voters);
    Ok(counts)
}
pub async fn fetch_state(
    client: &reqwest::Client,
    reference: &Reference,
    date: NaiveDate,
    across_days: &mut BTreeSet<String>,
) -> Result<Daily> {
    // The mature historical aggregate explicitly confirms two King zero days.
    // Current ambiguous zeros never take this path.
    if date >= start(2024)
        && date < start(2024) + chrono::Duration::days(12)
        && let Ok(bytes) =
            std::fs::read(Path::new(env!("CARGO_MANIFEST_DIR")).join("data/statewide.json"))
        && let Ok(data) = serde_json::from_slice::<statewide::Data>(&bytes)
        && let Some(county) = data
            .counties
            .iter()
            .find(|c| c.id == reference.id && c.state_id == reference.state_id)
        && county.days.iter().any(|d| {
            d.date_2024 == date
                && d.by_method
                    .get("in_person")
                    .map(|v| v.votes_2024)
                    .unwrap_or_else(|| {
                        (data.voting_method == "in_person")
                            .then_some(d.votes_2024)
                            .flatten()
                    })
                    == Some(0)
        })
        && let Some(source) = data
            .sources
            .iter()
            .find(|s| s.year == 2024 && s.date == date)
    {
        return Ok(Daily { zero_evidence: Vec::new(), allow_daily_difference: None, unavailable_precincts: Vec::new(), complete: false, county: reference.id.clone(), date, counts: Counts::new(), source: source.url.clone(), sha256: source.sha256.clone(), retrieved_at: source.retrieved_at.clone(), cumulative: false, note: "Official dated Texas SOS historical county aggregate explicitly confirms zero in-person votes. An empty roster alone is never treated as zero; current unconfirmed zeros are excluded.".into() });
    }
    let (url, form) = if date.format("%Y").to_string() == "2024" {
        (
            "https://earlyvoting.texas-election.com/Elections/downloadVoterInfoReport.do"
                .to_string(),
            Some(BTreeMap::from([
                ("idElection".into(), "49664".into()),
                ("selectedDate".into(), format!("{date} 00:00:00.0")),
                ("electionDate".into(), ",".into()),
                ("earlyVoteFlag".into(), "true".into()),
                ("downloadElectionFileCSVFlag".into(), "true".into()),
                ("idTown".into(), reference.state_id.to_string()),
            ])),
        )
    } else {
        (current_state_url(reference, date)?, None)
    };
    let response = download(client, &url, form.as_ref()).await?;
    let csv = if form.is_some() {
        response
    } else {
        ensure!(
            !response.is_empty(),
            "daily state export not yet posted for {date}"
        );
        let json: serde_json::Value =
            serde_json::from_slice(&response).context("state export is not JSON")?;
        let encoded = json["upload"]
            .as_str()
            .context("state export has no upload")?;
        base64::engine::general_purpose::STANDARD
            .decode(encoded.rsplit(',').next().unwrap_or(encoded))
            .context("decode state CSV")?
    };
    let source_sha256 = format!("{:x}", Sha256::digest(&csv));
    let identical_row_policy =
        identical_row_policy(&reference.id, &date.to_string(), &source_sha256);
    let counts = parse_state_with_ambiguity(
        &csv,
        across_days,
        reference.id == "tarrant" && date == start(2024),
        identical_row_policy,
    )?;
    let mut note = state_note(&reference.id, date);
    if matches!(reference.id.as_str(), "houston" | "leon") && identical_row_policy > 0 {
        note.push_str(" A reviewed hash-pinned repeated CSV record is counted once; differing records and additional duplicates still fail validation. Control shortfalls remain unknown rather than inferred zeros.");
    }
    Ok(Daily {
        zero_evidence: Vec::new(),
        allow_daily_difference: None,
        unavailable_precincts: Vec::new(),
        complete: false,
        county: reference.id.clone(),
        date,
        counts,
        source: if form.is_some() {
            format!(
                "{url}?idElection=49664&selectedDate={date}&idTown={}",
                reference.state_id
            )
        } else {
            url
        },
        sha256: source_sha256,
        retrieved_at: Utc::now().to_rfc3339(),
        note,
        cumulative: false,
    })
}
fn identical_row_policy(county: &str, date: &str, sha256: &str) -> usize {
    match (county, date) {
        ("elpaso", "2024-10-22" | "2024-10-23") | ("nacogdoches" | "willacy", "2024-10-21") => 1,
        ("willacy", "2024-10-23") => 2,
        ("houston", "2024-10-25")
            if sha256 == "1b662d55c21f7ee931ad8f089afeac273775d94657695231ca46db52fa78cb03" =>
        {
            1
        }
        ("leon", "2024-10-22")
            if sha256 == "7cdf0400b0924e80d753655102f5b52d2d9bf868cd5a66e5d60e3a64b9662bf1" =>
        {
            1
        }
        _ => 0,
    }
}
/// Private, memory-only identity associations used to recover blank county
/// residence precincts. This type deliberately has no serde/Debug implementation.
pub(crate) struct PrecinctIdentities {
    pub unique: BTreeMap<String, String>,
    pub source: String,
    pub sha256: String,
}

fn unique_precinct_identities(bytes: &[u8]) -> Result<BTreeMap<String, String>> {
    let mut reader = csv::ReaderBuilder::new()
        .trim(csv::Trim::All)
        .from_reader(bytes);
    let headers = reader.headers()?.clone();
    let column = |name: &str| {
        headers
            .iter()
            .position(|h| h.trim_start_matches('\u{feff}') == name)
            .with_context(|| format!("missing identity source field {name}"))
    };
    let method = column("VOTING_METHOD")?;
    let id = column("ID_VOTER")?;
    let precinct = column("PRECINCT")?;
    let mut seen = BTreeSet::new();
    let mut unique = BTreeMap::new();
    let mut records = 0;
    for row in reader.records() {
        let row = row?;
        if &row[method] != "IN-PERSON" {
            continue;
        }
        records += 1;
        let identity = row[id].trim();
        if identity.is_empty() {
            continue;
        }
        if seen.insert(identity.to_string()) {
            unique.insert(identity.to_string(), normalize(&row[precinct]));
        } else {
            // Even byte-identical repeated IDs cannot independently identify a row.
            unique.remove(identity);
        }
    }
    ensure!(records > 0, "identity source has no in-person observations");
    Ok(unique)
}

pub(crate) async fn fetch_precinct_identities(
    client: &reqwest::Client,
    reference: &Reference,
    date: NaiveDate,
) -> Result<PrecinctIdentities> {
    ensure!(
        date.format("%Y").to_string() == "2026",
        "identity recovery requires current election"
    );
    let source = current_state_url(reference, date)?;
    let response = download(client, &source, None).await?;
    let json: serde_json::Value =
        serde_json::from_slice(&response).context("identity source is not JSON")?;
    let encoded = json["upload"]
        .as_str()
        .context("identity source has no upload")?;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(encoded.rsplit(',').next().unwrap_or(encoded))
        .context("decode identity source CSV")?;
    Ok(PrecinctIdentities {
        unique: unique_precinct_identities(&bytes)?,
        source,
        sha256: format!("{:x}", Sha256::digest(&bytes)),
    })
}

fn current_state_url(reference: &Reference, date: NaiveDate) -> Result<String> {
    let mut url = reqwest::Url::parse(
        "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFileByFormat",
    )?;
    url.query_pairs_mut().extend_pairs([
        ("type", "EVR_EARLYVOTING".to_string()),
        ("electionId", "53815".to_string()),
        ("electionDate", date.format("%m/%d/%Y").to_string()),
        ("county", reference.name.to_uppercase()),
        ("countyId", reference.state_id.to_string()),
        ("format", "csv".to_string()),
    ]);
    Ok(url.into())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn failed_state_date_does_not_poison_identity_validation_of_later_dates() {
        for malformed in [
            "ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\nbad,UNKNOWN,2\n",
            "ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\n,IN-PERSON,2\n",
            "ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\nfresh,IN-PERSON,1\n",
            "ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\nprior,IN-PERSON,2\n",
        ] {
            let mut prior = BTreeSet::from(["prior".to_string()]);
            assert!(parse_state(malformed.as_bytes(), &mut prior).is_err());
            assert_eq!(prior, BTreeSet::from(["prior".to_string()]));
            let valid = parse_state(
                b"ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\n",
                &mut prior,
            )
            .unwrap();
            assert_eq!(valid.get("1"), Some(&1));
            assert_eq!(
                prior,
                BTreeSet::from(["prior".to_string(), "fresh".to_string()])
            );
            assert!(
                parse_state(
                    b"ID_VOTER,VOTING_METHOD,PRECINCT\nfresh,IN-PERSON,1\n",
                    &mut prior
                )
                .is_err()
            );
        }
    }

    #[test]
    fn identity_recovery_requires_one_same_date_in_person_row_per_identifier() {
        let rows = b"ID_VOTER,VOTING_METHOD,PRECINCT\na,IN-PERSON,001\nb,IN-PERSON,2\nb,IN-PERSON,2\nb,IN-PERSON,3\na,MAIL,99\nc,IN-PERSON,\n,IN-PERSON,4\n";
        let identities = unique_precinct_identities(rows).unwrap();
        assert_eq!(
            identities,
            BTreeMap::from([("a".into(), "1".into()), ("c".into(), "".into())])
        );
        assert!(
            unique_precinct_identities(b"ID_VOTER,VOTING_METHOD,PRECINCT\na,MAIL,1\n").is_err()
        );
        assert!(unique_precinct_identities(b"ID_VOTER,PRECINCT\na,1\n").is_err());
    }
    async fn mock_downloads(
        responses: Vec<&'static [u8]>,
    ) -> (String, tokio::task::JoinHandle<Vec<String>>) {
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
        };
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let mut requests = Vec::new();
            for response in responses {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut bytes = Vec::new();
                loop {
                    let mut buffer = [0_u8; 2048];
                    let n = stream.read(&mut buffer).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&buffer[..n]);
                    if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                        let headers = String::from_utf8_lossy(&bytes[..end]).to_lowercase();
                        let length = headers
                            .lines()
                            .find_map(|line| line.strip_prefix("content-length:"))
                            .map_or(0, |v| v.trim().parse::<usize>().unwrap());
                        if bytes.len() >= end + 4 + length {
                            break;
                        }
                    }
                }
                requests.push(String::from_utf8(bytes).unwrap());
                stream.write_all(response).await.unwrap();
            }
            requests
        });
        (url, server)
    }

    #[tokio::test]
    async fn truncated_body_retries_preserving_post_fields() {
        let (url, server) = mock_downloads(vec![
            b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\nx",
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood",
        ])
        .await;
        let form = BTreeMap::from([("date".into(), "2026-10-22".into())]);
        assert_eq!(
            download(&reqwest::Client::new(), &url, Some(&form))
                .await
                .unwrap(),
            b"good"
        );
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 2);
        assert!(
            requests
                .iter()
                .all(|r| r.starts_with("POST ") && r.ends_with("date=2026-10-22"))
        );
    }

    #[tokio::test]
    async fn exhausted_body_retries_reach_the_compatible_transport_boundary() {
        let broken: &[u8] = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\nx";
        let (url, server) = mock_downloads(vec![broken, broken]).await;
        assert!(
            native_download(&reqwest::Client::new(), &url, None)
                .await
                .unwrap()
                .is_none()
        );
        assert_eq!(server.await.unwrap().len(), 2);
    }

    #[tokio::test]
    async fn bad_gateway_retries_before_failing_the_county() {
        let (url, server) = mock_downloads(vec![
            b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood",
        ])
        .await;
        assert_eq!(
            download(&reqwest::Client::new(), &url, None)
                .await
                .expect("gateway failures should retry"),
            b"good"
        );
        assert_eq!(server.await.unwrap().len(), 2);
    }

    #[tokio::test]
    async fn rate_limit_retries_before_marking_a_county_unavailable() {
        let (url, server) = mock_downloads(vec![
            b"HTTP/1.1 429 Too Many Requests\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood",
        ])
        .await;
        assert_eq!(
            download(&reqwest::Client::new(), &url, None)
                .await
                .expect("temporary rate limit must not lose a newly posted county date"),
            b"good"
        );
        assert_eq!(server.await.unwrap().len(), 2);
    }

    #[tokio::test]
    async fn exhausted_gateway_errors_reach_the_compatible_transport_boundary() {
        let bad: &[u8] =
            b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
        let (url, server) = mock_downloads(vec![bad, bad]).await;
        assert!(
            native_download(&reqwest::Client::new(), &url, None)
                .await
                .unwrap()
                .is_none()
        );
        assert_eq!(server.await.unwrap().len(), 2);
    }

    #[tokio::test]
    async fn hard_http_errors_are_not_retried_or_sent_to_fallback() {
        let (url, server) = mock_downloads(vec![
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        ])
        .await;
        let error = download(&reqwest::Client::new(), &url, None)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("404"));
        assert_eq!(server.await.unwrap().len(), 1);
    }

    #[tokio::test]
    async fn body_timeout_retries_a_complete_download() {
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
        };
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            for attempt in 0..2 {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut request = [0_u8; 2048];
                let received = stream.read(&mut request).await.unwrap();
                assert!(received > 0);
                if attempt == 0 {
                    // Headers succeed, then the body stalls: the reported Ellis failure.
                    stream
                        .write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\na",
                        )
                        .await
                        .unwrap();
                    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
                } else {
                    stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ngood").await.unwrap();
                }
            }
        });
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_millis(75))
            .build()
            .unwrap();
        let bytes = download(&client, &url, None)
            .await
            .expect("a body timeout must retry rather than mark the county stale immediately");
        assert_eq!(bytes, b"good");
        server.await.unwrap();
    }

    #[test]
    fn quoted_csv_excludes_mail_normalizes_and_keeps_unassigned() {
        let c=state_csv(b"VOTER_NAME,ID_VOTER,VOTING_METHOD,PRECINCT\n\"A, B\",a,IN-PERSON,001\nX,b,MAIL-IN,1\nY,c,IN-PERSON,\n").unwrap();
        assert_eq!(c.get("1"), Some(&1));
        assert_eq!(c.get("UNASSIGNED"), Some(&1));
        assert_eq!(c.values().sum::<u64>(), 2);
    }
    #[test]
    fn duplicate_voters_and_unrecognized_method_fail() {
        assert!(
            state_csv(b"ID_VOTER,VOTING_METHOD,PRECINCT\na,IN-PERSON,1\na,IN-PERSON,1\n").is_err()
        );
        assert!(state_csv(b"ID_VOTER,VOTING_METHOD,PRECINCT\na,UNKNOWN,1\n").is_err());
        assert!(state_csv(b"").is_err());
    }
}

fn state_note(county: &str, date: NaiveDate) -> String {
    let base = "Daily state IN-PERSON roster; mail excluded. Separate limited/provisional flags are not supplied. Date semantics were independently checked during the October 23 source audit.";
    let extra = match county {
        "bell" if date >= start(2026) => {
            " At the initial October 23 audit, four-day state 28,049 versus broader county 28,094; five votes have precinct labels outside the map and stay unassigned."
        }
        "hockley" if date < start(2026) => {
            " Four-day roster 2,684 versus official summary 2,695; 11 missing voters cannot be placed into precincts."
        }
        "madison" if date < start(2026) => {
            " Four-day roster 1,678 versus official summary 1,686; eight missing voters cannot be placed into precincts."
        }
        "madison" => {
            " Four-day state 1,081 versus county daily PDFs 1,086. A single state series is used throughout; county source conflict remains unresolved."
        }
        "elpaso" | "nacogdoches" | "willacy" if date < start(2026) => {
            " October 24 audit found byte-identical repeated in-person rows in El Paso October 22/23, Nacogdoches/Willacy October 21 (one extra each), and Willacy October 23 (two extras). Only those dated files remove identical copies; different rows sharing an ID and all cross-date repeats remain errors. No missing votes are allocated to match county controls."
        }
        "tarrant" if date < start(2026) => {
            " Tarrant's October 21 repeated identical-name identifier with conflicting precincts is counted once in UNASSIGNED; neither residence is guessed. Twelve-day distinct state roster 635,101 versus county graph 635,261; the missing records are not allocated. All other within/across-day in-person identifiers remain strict."
        }
        "tarrant" => {
            " Five-day state residence-precinct roster 246,258 versus county cumulative in-person report 247,668. County six-digit ballot splits are not guessed into map precincts; original state labels and unassigned counts are retained."
        }
        _ => "",
    };
    format!("{base}{extra}")
}

#[cfg(test)]
mod completeness_tests {
    use super::*;
    #[test]
    fn mail_only_is_unavailable_and_repeated_dates_fail() {
        assert!(state_csv(b"ID_VOTER,VOTING_METHOD,PRECINCT\na,MAIL-IN,1\n").is_err());
        let mut seen = BTreeSet::new();
        let csv = b"ID_VOTER,VOTING_METHOD,PRECINCT\na,IN-PERSON,1\n";
        assert!(parse_state(csv, &mut seen).is_ok());
        assert!(parse_state(csv, &mut seen).is_err());
    }
}

#[cfg(test)]
mod expanded_roster_tests {
    use super::*;
    #[test]
    fn current_url_preserves_spaced_official_county_names() {
        let reference: Reference = serde_json::from_value(serde_json::json!({"id":"fortbend","name":"Fort Bend","state_id":79,"groups":[],"exact_pairs":[],"presidential":{},"references":{}})).unwrap();
        let url =
            reqwest::Url::parse(&current_state_url(&reference, start(2026)).unwrap()).unwrap();
        let fields: BTreeMap<_, _> = url.query_pairs().collect();
        assert_eq!(fields["county"], "FORT BEND");
        assert_eq!(fields["countyId"], "79");
        assert_eq!(fields["electionDate"], "10/19/2026");
    }
    #[test]
    fn mail_surrender_does_not_duplicate_the_included_method() {
        let raw = b"ID_VOTER,VOTING_METHOD,PRECINCT\na,MAIL-IN,1\na,IN-PERSON,1\n";
        assert_eq!(state_csv(raw).unwrap()["1"], 1);
        assert!(
            state_csv(b"ID_VOTER,VOTING_METHOD,PRECINCT\na,IN-PERSON,1\na,IN-PERSON,1\n").is_err()
        );
    }
    #[test]
    fn historical_missing_dates_have_only_hash_pinned_exact_duplicate_exceptions() {
        for (county, date, hash) in [
            (
                "houston",
                "2024-10-25",
                "1b662d55c21f7ee931ad8f089afeac273775d94657695231ca46db52fa78cb03",
            ),
            (
                "leon",
                "2024-10-22",
                "7cdf0400b0924e80d753655102f5b52d2d9bf868cd5a66e5d60e3a64b9662bf1",
            ),
        ] {
            assert_eq!(identical_row_policy(county, date, hash), 1);
            assert_eq!(identical_row_policy(county, date, &"a".repeat(64)), 0);
            assert_eq!(identical_row_policy(county, "2024-10-21", hash), 0);
        }
    }
    #[test]
    fn scoped_identical_row_policy_does_not_allow_identifier_collisions() {
        let raw = b"ID_VOTER,VOTER_NAME,VOTING_METHOD,PRECINCT\na,TEST,IN-PERSON,001A\na,TEST,IN-PERSON,001A\n";
        let mut across = BTreeSet::new();
        let counts = parse_state_with_ambiguity(raw, &mut across, false, 1).unwrap();
        assert_eq!(counts["1A"], 1);
        assert!(parse_state_with_ambiguity(raw, &mut across, false, 1).is_err());
        assert!(parse_state_with_ambiguity(b"ID_VOTER,VOTER_NAME,VOTING_METHOD,PRECINCT\na,ONE,IN-PERSON,1\na,TWO,IN-PERSON,1\n", &mut BTreeSet::new(), false, 1).is_err());
    }
    #[test]
    fn tarrant_ambiguity_is_one_person_with_unknown_residence() {
        let raw = b"ID_VOTER,VOTER_NAME,VOTING_METHOD,PRECINCT\na,TEST,IN-PERSON,1001\na,TEST,IN-PERSON,1002\nb,OTHER,IN-PERSON,1001\n";
        let counts = parse_state_with_ambiguity(raw, &mut BTreeSet::new(), true, 0).unwrap();
        assert_eq!(
            counts,
            Counts::from([("1001".into(), 1), ("UNASSIGNED".into(), 1)])
        );
        assert!(parse_state_with_ambiguity(b"ID_VOTER,VOTER_NAME,VOTING_METHOD,PRECINCT\na,ONE,IN-PERSON,1\na,TWO,IN-PERSON,2\n", &mut BTreeSet::new(), true, 0).is_err());
    }
}
