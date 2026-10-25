//! State-native observations. Matching is independent for every date and measure.
use anyhow::{Context, Result, bail, ensure};
use chrono::{Duration, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

pub const STATES: [(&str, &str, &str); 4] = [
    ("ga", "Georgia", "georgia.py"),
    ("nc", "North Carolina", "north_carolina.py"),
    ("va", "Virginia", "virginia.py"),
    ("nv", "Nevada", "nevada.py"),
];
type Breakdown = BTreeMap<String, BTreeMap<String, u64>>;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Observation {
    pub year: i32,
    pub date: NaiveDate,
    pub county: String,
    #[serde(default)]
    pub county_name: String,
    #[serde(default)]
    pub precinct: Option<String>,
    pub measure: String,
    pub method: String,
    pub votes: u64,
    #[serde(default)]
    pub breakdowns: Breakdown,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Dataset {
    pub id: String,
    pub name: String,
    pub generated_at: String,
    pub through: NaiveDate,
    pub start_dates: BTreeMap<String, NaiveDate>,
    pub observations: Vec<Observation>,
    #[serde(default)]
    pub counties: Vec<Value>,
    #[serde(default)]
    pub sources: Vec<Value>,
    #[serde(default)]
    pub errors: Vec<Value>,
    #[serde(default)]
    pub notes: Vec<String>,
    #[serde(default)]
    pub method_labels: Value,
}

pub fn load(root: &Path, state: &str) -> Result<Dataset> {
    ensure!(STATES.iter().any(|s| s.0 == state), "Unknown state");
    let data: Dataset = serde_json::from_slice(&std::fs::read(
        root.join(format!("data/states/{state}.json")),
    )?)?;
    ensure!(data.id == state, "State identity mismatch");
    let mut seen = BTreeSet::new();
    for r in &data.observations {
        ensure!([2024, 2026].contains(&r.year), "Unexpected election year");
        ensure!(
            r.date.format("%Y").to_string() == r.year.to_string(),
            "Observation year mismatch"
        );
        ensure!(
            ["daily", "cumulative"].contains(&r.measure.as_str()),
            "Unknown measure"
        );
        ensure!(
            ["in_person", "mail", "total"].contains(&r.method.as_str()),
            "Unknown voting method"
        );
        ensure!(
            seen.insert((
                r.year,
                r.date,
                &r.county,
                &r.precinct,
                &r.measure,
                &r.method
            )),
            "Duplicate observation"
        );
    }
    Ok(data)
}

pub fn catalog(root: &Path) -> Value {
    json!({"states": STATES.iter().map(|(id,name,_)| {
        match load(root,id) {
            Ok(data) => json!({"id":id,"name":name,"generated_at":data.generated_at,"through":data.through,
                "observations":data.observations.len(),"counties":data.observations.iter().filter(|o|o.precinct.is_none()&&o.year==2026).map(|o|&o.county).collect::<BTreeSet<_>>().len(),"status":"available"}),
            Err(error) => json!({"id":id,"name":name,"status":"unavailable","error":error.to_string()}),
        }
    }).collect::<Vec<_>>()})
}

#[derive(Default, Deserialize)]
pub struct Query {
    pub date: Option<NaiveDate>,
    pub method: Option<String>,
    pub classification: Option<String>,
    pub metric: Option<String>,
    pub county: Option<String>,
}

struct Index<'a> {
    data: &'a Dataset,
    rows: BTreeMap<(i32, NaiveDate, &'a str, &'a str, &'a str), &'a Observation>,
}
impl<'a> Index<'a> {
    fn new(data: &'a Dataset) -> Self {
        Self {
            data,
            rows: data
                .observations
                .iter()
                .filter(|r| r.precinct.is_none())
                .map(|r| {
                    (
                        (
                            r.year,
                            r.date,
                            r.county.as_str(),
                            r.method.as_str(),
                            r.measure.as_str(),
                        ),
                        r,
                    )
                })
                .collect(),
        }
    }
    fn exact(
        &self,
        year: i32,
        date: NaiveDate,
        county: &str,
        method: &str,
        measure: &str,
    ) -> Option<Observation> {
        self.rows
            .get(&(year, date, county, method, measure))
            .map(|r| (*r).clone())
    }
    fn value(
        &self,
        year: i32,
        date: NaiveDate,
        county: &str,
        method: &str,
        measure: &str,
    ) -> Option<Observation> {
        if year == 2026 && date > self.data.through {
            return None;
        }
        if method == "total" {
            // Native totals can include other categories (Virginia COUNTABLE).
            // The combined view always uses the same two voting methods.
            let b = self.value(year, date, county, "mail", measure)?;
            let mut a = self
                .value(year, date, county, "in_person", measure)
                .or_else(|| {
                    let opening = self.data.start_dates.get(&year.to_string())?;
                    let closing = in_person_end(&self.data.id, year);
                    if date > closing && measure == "cumulative" {
                        // After closing, retain a verified final early-vote count;
                        // an earlier incomplete snapshot cannot stand in for it.
                        let mut final_count =
                            self.value(year, closing, county, "in_person", "cumulative")?;
                        final_count.date = date;
                        return Some(final_count);
                    }
                    if date >= *opening && !(date > closing && measure == "daily") {
                        return None;
                    }
                    // Outside official opening hours, missing daily in-person
                    // activity is a calendar-established zero, not a missing upload.
                    let mut zero = b.clone();
                    zero.votes = 0;
                    for groups in zero.breakdowns.values_mut() {
                        for value in groups.values_mut() {
                            *value = 0;
                        }
                    }
                    Some(zero)
                })?;
            a.votes = a.votes.checked_add(b.votes)?;
            a.breakdowns = add_breakdowns(&a.breakdowns, &b.breakdowns);
            a.method = "total".into();
            return Some(a);
        }
        if let Some(r) = self.exact(year, date, county, method, measure) {
            return Some(r);
        }
        if measure == "daily" {
            let mut a = self.exact(year, date, county, method, "cumulative")?;
            let b = self.exact(year, date - Duration::days(1), county, method, "cumulative")?;
            a.votes = a.votes.checked_sub(b.votes)?;
            a.breakdowns = subtract_breakdowns(&a.breakdowns, &b.breakdowns);
            a.measure = "daily".into();
            return Some(a);
        }
        // Anchor to an actual cumulative snapshot or a source-declared first day.
        let first = *self.data.start_dates.get(&year.to_string())?;
        let mut cursor = date;
        let mut tail = Vec::new();
        while cursor >= first {
            if let Some(mut anchor) = self.exact(year, cursor, county, method, "cumulative") {
                for r in tail.iter().rev() {
                    let r: &Observation = r;
                    anchor.votes = anchor.votes.checked_add(r.votes)?;
                    anchor.breakdowns = add_breakdowns(&anchor.breakdowns, &r.breakdowns);
                }
                anchor.date = date;
                return Some(anchor);
            }
            tail.push(self.exact(year, cursor, county, method, "daily")?);
            cursor -= Duration::days(1);
        }
        let mut total = tail.pop()?;
        for r in tail.iter().rev() {
            total.votes = total.votes.checked_add(r.votes)?;
            total.breakdowns = add_breakdowns(&total.breakdowns, &r.breakdowns);
        }
        total.date = date;
        total.measure = "cumulative".into();
        Some(total)
    }
}

fn add_breakdowns(a: &Breakdown, b: &Breakdown) -> Breakdown {
    a.iter()
        .filter_map(|(dimension, groups)| {
            let other = b.get(dimension)?;
            // Only a dimension published on both observations can be combined.
            Some((
                dimension.clone(),
                groups
                    .iter()
                    .filter_map(|(key, value)| {
                        Some((key.clone(), value.checked_add(*other.get(key)?)?))
                    })
                    .collect(),
            ))
        })
        .collect()
}
fn subtract_breakdowns(a: &Breakdown, b: &Breakdown) -> Breakdown {
    a.iter()
        .filter_map(|(dimension, groups)| {
            let other = b.get(dimension)?;
            let values: Option<BTreeMap<_, _>> = groups
                .iter()
                .filter(|(k, _)| other.contains_key(*k))
                .map(|(k, v)| Some((k.clone(), v.checked_sub(*other.get(k)?)?)))
                .collect();
            Some((dimension.clone(), values?))
        })
        .collect()
}

#[derive(Default, Clone, Debug, Serialize)]
pub struct Day {
    pub date_2026: NaiveDate,
    pub date_2024: NaiveDate,
    pub days_before_election: i64,
    pub future: bool,
    pub daily_2024: Option<u64>,
    pub daily_2026: Option<u64>,
    pub cumulative_2024: Option<u64>,
    pub cumulative_2026: Option<u64>,
    pub reported_daily_2026: Option<u64>,
    pub reported_cumulative_2026: Option<u64>,
    pub daily_members: Vec<String>,
    pub cumulative_members: Vec<String>,
}
fn aligned(date: NaiveDate) -> NaiveDate {
    historical_election() - (current_election() - date)
}
fn canonical(name: &str) -> String {
    name.to_lowercase()
        .replace(" county", "")
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}
fn historical_election() -> NaiveDate {
    NaiveDate::from_ymd_opt(2024, 11, 5).unwrap()
}
fn current_election() -> NaiveDate {
    NaiveDate::from_ymd_opt(2026, 11, 3).unwrap()
}
fn in_person_end(state: &str, year: i32) -> NaiveDate {
    let current = NaiveDate::from_ymd_opt(
        2026,
        10,
        if ["nc", "va"].contains(&state) {
            31
        } else {
            30
        },
    )
    .unwrap();
    if year == 2024 {
        current + (historical_election() - current_election())
    } else {
        current
    }
}

struct Scope<'a> {
    members: &'a [String],
    method: &'a str,
    dimension: Option<(&'a str, &'a str)>,
}
fn series(index: &Index<'_>, dates: &[NaiveDate], scope: Scope<'_>) -> Vec<Day> {
    dates
        .iter()
        .map(|&date| {
            let future = date > index.data.through;
            let mut point = Day {
                date_2026: date,
                date_2024: aligned(date),
                days_before_election: (current_election() - date).num_days(),
                future,
                ..Day::default()
            };
            for measure in ["daily", "cumulative"] {
                let mut old = 0;
                let mut new = 0;
                let mut reported = 0;
                let mut members = Vec::new();
                let mut reported_n = 0;
                for county in scope.members {
                    let a = index.value(2024, aligned(date), county, scope.method, measure);
                    let b = index.value(2026, date, county, scope.method, measure);
                    let amount = |r: &Observation| match scope.dimension {
                        Some((dimension, label)) => r
                            .breakdowns
                            .get(dimension)
                            .and_then(|v| v.get(label))
                            .copied(),
                        None => Some(r.votes),
                    };
                    let a = a.as_ref().and_then(amount);
                    let b = b.as_ref().and_then(amount);
                    if let Some(v) = b {
                        reported += v;
                        reported_n += 1;
                    }
                    if let Some(a) = a
                        && (b.is_some() || future)
                    {
                        old += a;
                        new += b.unwrap_or(0);
                        members.push(county.clone());
                    }
                }
                let a = (!members.is_empty()).then_some(old);
                let b = (!members.is_empty() && !future).then_some(new);
                if measure == "daily" {
                    point.daily_2024 = a;
                    point.daily_2026 = b;
                    point.daily_members = members;
                    point.reported_daily_2026 = (reported_n > 0).then_some(reported);
                } else {
                    point.cumulative_2024 = a;
                    point.cumulative_2026 = b;
                    point.cumulative_members = members;
                    point.reported_cumulative_2026 = (reported_n > 0).then_some(reported);
                }
            }
            point
        })
        .collect()
}

pub fn view(root: &Path, state: &str, query: &Query) -> Result<Value> {
    let data = load(root, state)?;
    let index = Index::new(&data);
    let method = query.method.as_deref().unwrap_or("total");
    ensure!(
        ["in_person", "mail", "total"].contains(&method),
        "Unknown voting method"
    );
    let classification =
        query
            .classification
            .as_deref()
            .unwrap_or(if state == "ga" { "race" } else { "partisan" });
    ensure!(
        [
            "partisan",
            "demographic",
            "party",
            "race",
            "age",
            "sex",
            "ethnicity",
            "white_nonwhite"
        ]
        .contains(&classification),
        "Unknown classification"
    );
    let metric = query.metric.as_deref().unwrap_or("non_white_vap");
    let requested = query.date.unwrap_or(data.through);
    ensure!(
        requested >= NaiveDate::from_ymd_opt(2026, 8, 1).unwrap() && requested < current_election(),
        "Date outside general-election calendar"
    );
    let reference: Value = std::fs::read(root.join(format!("data/states/{state}-reference.json")))
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or(json!({"counties":{},"metrics":[]}));
    let mut metadata = BTreeMap::<String, Value>::new();
    for o in data.observations.iter().filter(|o| o.precinct.is_none()) {
        metadata
            .entry(o.county.clone())
            .or_insert_with(|| json!({"id":o.county,"name":o.county_name}));
    }
    for c in &data.counties {
        if let Some(id) = c["id"].as_str() {
            metadata.insert(id.into(), c.clone());
        }
    }
    for (id, meta) in &mut metadata {
        let refs = reference["counties"].as_object();
        let county = refs.and_then(|refs| {
            refs.get(meta["fips"].as_str().unwrap_or(id)).or_else(|| {
                refs.values().find(|r| {
                    canonical(r["name"].as_str().unwrap_or(""))
                        == canonical(meta["name"].as_str().unwrap_or(""))
                })
            })
        });
        if let Some(r) = county
            && let (Some(m), Some(r)) = (meta.as_object_mut(), r.as_object())
        {
            for key in ["fips", "demographics", "counts", "harris", "trump"] {
                if let Some(v) = r.get(key) {
                    m.entry(key.to_string()).or_insert_with(|| v.clone());
                }
            }
        }
        let h = meta["harris"].as_u64();
        let t = meta["trump"].as_u64();
        meta["harris_share"] = match (h, t) {
            (Some(h), Some(t)) if h + t > 0 => json!(100.0 * h as f64 / (h + t) as f64),
            _ => Value::Null,
        };
    }
    let all: Vec<String> = metadata.keys().cloned().collect();
    if let Some(county) = &query.county {
        ensure!(metadata.contains_key(county), "Unknown county");
    }
    let selected_members: Vec<String> = all
        .iter()
        .filter(|id| query.county.as_ref().is_none_or(|c| c == *id))
        .cloned()
        .collect();
    let start = if method == "in_person" {
        *data
            .start_dates
            .get("2026")
            .context("Missing state calendar")?
    } else {
        data.observations
            .iter()
            .filter(|r| r.method == method || method == "total")
            .map(|r| {
                if r.year == 2024 {
                    current_election() - (historical_election() - r.date)
                } else {
                    r.date
                }
            })
            .min()
            .unwrap_or(data.through)
    };
    ensure!(
        (current_election() - start).num_days() <= 120,
        "State calendar too long"
    );
    let end = if method == "in_person" {
        in_person_end(state, 2026)
    } else {
        current_election() - Duration::days(1)
    };
    let selected = requested.clamp(start, end);
    let dates: Vec<_> = (0..=(end - start).num_days())
        .map(|n| start + Duration::days(n))
        .collect();
    let selected_index = dates.iter().position(|d| *d == selected);
    let mut county_rows = Vec::new();
    for (id, meta) in &metadata {
        let members = [id.clone()];
        let points = series(
            &index,
            &dates,
            Scope {
                members: &members,
                method,
                dimension: None,
            },
        );
        let mut row = meta.clone();
        row["series"] = serde_json::to_value(&points)?;
        row["selected"] = selected_index
            .map(|i| serde_json::to_value(&points[i]).unwrap())
            .unwrap_or(Value::Null);
        county_rows.push(row);
    }
    let mut available = BTreeSet::new();
    for r in &data.observations {
        for dimension in r.breakdowns.keys() {
            available.insert(dimension.clone());
        }
    }
    let mut buckets = Vec::new();
    if classification == "partisan" || classification == "demographic" {
        let labels: Vec<String> = if classification == "partisan" {
            vec![
                "Harris 30+",
                "Harris 15–30",
                "Harris 0–15",
                "Trump 0–15",
                "Trump 15–30",
                "Trump 30+",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect()
        } else {
            vec!["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
                .into_iter()
                .map(str::to_owned)
                .collect()
        };
        for (i, label) in labels.iter().enumerate() {
            let members: Vec<String> = selected_members
                .iter()
                .filter(|id| {
                    let meta = &metadata[*id];
                    if classification == "demographic" {
                        meta["demographics"][metric]
                            .as_f64()
                            .is_some_and(|v| ((v / 20.0).floor() as usize).min(4) == i)
                    } else {
                        meta["harris_share"].as_f64().is_some_and(|v| {
                            if v == 50.0 {
                                return false;
                            }
                            let m = (2.0 * v - 100.0).abs();
                            let band = if m >= 30.0 {
                                0
                            } else if m >= 15.0 {
                                1
                            } else {
                                2
                            };
                            (if v > 50.0 { band } else { 5 - band }) == i
                        })
                    }
                })
                .cloned()
                .collect();
            buckets.push(json!({"label":label,"members":members,"series":series(&index,&dates,Scope{members:&members,method,dimension:None})}));
        }
    } else if available.contains(classification) {
        let labels = data
            .observations
            .iter()
            .filter_map(|r| r.breakdowns.get(classification))
            .flat_map(|r| r.keys().cloned())
            .collect::<BTreeSet<_>>();
        for label in labels {
            buckets.push(json!({"label":label,"series":series(&index,&dates,Scope{members:&selected_members,method,dimension:Some((classification,&label))})}));
        }
    }
    let mut methods = data
        .observations
        .iter()
        .map(|r| r.method.clone())
        .collect::<BTreeSet<_>>();
    if methods.contains("mail") && methods.contains("in_person") {
        methods.insert("total".into());
    }
    let mut method_labels = data.method_labels.clone();
    if !method_labels.is_object() {
        method_labels = json!({});
    }
    method_labels["total"] = json!("Mail + in person");
    let mut notes = data.notes.clone();
    if state == "va" {
        notes.retain(|note| !note.starts_with("COUNTABLE is total"));
        notes.push("Mail + in person sums MAIL_IN and ON_MACHINE. Other native COUNTABLE categories are excluded.".into());
    }
    let mut result = json!({"id":data.id,"name":data.name,"generated_at":data.generated_at,"through":data.through,"date":selected,
        "method":method,"method_labels":method_labels,"classification":classification,"metric":metric,"methods":methods,"breakdowns":available,
        "metrics":reference["metrics"],"census_vintage":reference["vintage"],"reference_sources":reference["sources"],
        "alignment":"Same number of days before Election Day; each date and measure matches only counties reported in both cycles.",
        "election_dates":{"2024":historical_election(),"2026":current_election()},"counties":county_rows,"buckets":buckets,
        "series":series(&index,&dates,Scope{members:&selected_members,method,dimension:None}),
        "precinct_available":data.observations.iter().any(|o|o.precinct.is_some())||root.join(format!("../sources/multistate/{state}/precinct-daily.json")).exists(),
        "sources":data.sources,"errors":data.errors,"notes":notes});
    select_date(&mut result, selected, query.county.as_deref())?;
    Ok(result)
}

/// Reuse the already computed dated series for static publication and live requests.
pub fn select_date(view: &mut Value, requested: NaiveDate, county: Option<&str>) -> Result<()> {
    let dates = view["series"]
        .as_array()
        .context("Missing state calendar")?;
    let first: NaiveDate = dates.first().context("Empty state calendar")?["date_2026"]
        .as_str()
        .context("Missing date")?
        .parse()?;
    let last: NaiveDate = dates.last().unwrap()["date_2026"]
        .as_str()
        .context("Missing date")?
        .parse()?;
    let selected = requested.clamp(first, last);
    view["date"] = json!(selected);
    let classification = view["classification"]
        .as_str()
        .unwrap_or("partisan")
        .to_owned();
    let metric = view["metric"]
        .as_str()
        .unwrap_or("non_white_vap")
        .to_owned();
    let mut points = Vec::new();
    for row in view["counties"]
        .as_array_mut()
        .context("Missing counties")?
    {
        row["selected"] = row["series"]
            .as_array()
            .and_then(|rows| {
                rows.iter()
                    .find(|r| r["date_2026"].as_str() == Some(&selected.to_string()))
            })
            .cloned()
            .unwrap_or(Value::Null);
        if county.is_some_and(|id| row["id"].as_str() != Some(id)) {
            continue;
        }
        let x = if classification == "demographic" {
            row["demographics"][&metric].as_f64()
        } else {
            row["harris_share"].as_f64()
        };
        if let (Some(x), Some(old), Some(new)) = (
            x,
            row["selected"]["cumulative_2024"].as_u64(),
            row["selected"]["cumulative_2026"].as_u64(),
        ) && old > 0
        {
            points.push(json!({"id":row["id"],"name":row["name"],"fips":row["fips"],"x":x,"y":100.0*new as f64/old as f64,"votes_2024":old,"votes_2026":new,"harris_share":row["harris_share"]}));
        }
    }
    view["fit"] = serde_json::to_value(crate::regression::fit(
        &points
            .iter()
            .map(|p| (p["x"].as_f64().unwrap(), p["y"].as_f64().unwrap()))
            .collect::<Vec<_>>(),
    ))?;
    view["points"] = json!(points);
    Ok(())
}

#[derive(Deserialize)]
pub struct PrecinctQuery {
    pub county: String,
    pub date: Option<NaiveDate>,
    pub method: Option<String>,
    pub measure: Option<String>,
}

/// Current-only inspection never implies a cross-cycle precinct correspondence.
pub fn precincts(root: &Path, state: &str, query: &PrecinctQuery) -> Result<Value> {
    let data = load(root, state)?;
    let method = query.method.as_deref().unwrap_or("total");
    let measure = query.measure.as_deref().unwrap_or("cumulative");
    ensure!(
        ["in_person", "mail", "total"].contains(&method),
        "Unknown voting method"
    );
    ensure!(
        ["daily", "cumulative"].contains(&measure),
        "Unknown measure"
    );
    ensure!(
        data.counties
            .iter()
            .any(|c| c["id"].as_str() == Some(query.county.as_str())),
        "Unknown county"
    );
    let parent = root.join(format!("../sources/multistate/{state}"));
    let shard = parent.join(format!("precincts/{}.json", query.county));
    let path = if shard.exists() {
        shard
    } else {
        parent.join("precinct-daily.json")
    };
    let rows = if path.exists() {
        #[derive(Deserialize)]
        struct File {
            observations: Vec<Observation>,
        }
        serde_json::from_slice::<File>(&std::fs::read(path)?)?.observations
    } else {
        data.observations.clone()
    };
    precincts_from(&data, &rows, query)
}

/// Public, anonymous published aggregates only. Keep source loading outside bulk exports.
pub fn precincts_from(
    data: &Dataset,
    observations: &[Observation],
    query: &PrecinctQuery,
) -> Result<Value> {
    let state = data.id.as_str();
    let date = query.date.unwrap_or(data.through);
    let method = query.method.as_deref().unwrap_or("total");
    let measure = query.measure.as_deref().unwrap_or("cumulative");
    ensure!(
        ["in_person", "mail", "total"].contains(&method),
        "Unknown voting method"
    );
    ensure!(
        ["daily", "cumulative"].contains(&measure),
        "Unknown measure"
    );
    ensure!(
        data.counties
            .iter()
            .any(|c| c["id"].as_str() == Some(query.county.as_str())),
        "Unknown county"
    );
    let rows: Vec<_> = observations
        .iter()
        .filter(|r| {
            r.year == 2026
                && r.county == query.county
                && r.precinct.is_some()
                && r.date <= data.through
        })
        .collect();
    let (daily, latest_reported) = if method == "total" {
        let mail_rows: Vec<_> = rows
            .iter()
            .copied()
            .filter(|r| r.method == "mail")
            .collect();
        let early_rows: Vec<_> = rows
            .iter()
            .copied()
            .filter(|r| r.method == "in_person")
            .collect();
        let mail = precinct_measure(&mail_rows, date, measure, data.through);
        let mut early = precinct_measure(&early_rows, date, measure, data.through);
        let opening = data.start_dates.get("2026").copied();
        let closing = in_person_end(state, 2026);
        let final_early = precinct_measure(&early_rows, closing, "cumulative", data.through);
        if date > closing && measure == "cumulative" && early.is_empty() {
            early = final_early.clone();
        }
        let values = mail
            .into_iter()
            .filter_map(|(precinct, votes)| {
                let early_votes = early.get(&precinct).copied().or_else(|| {
                    (opening.is_some_and(|d| date < d) || date > closing && measure == "daily")
                        .then_some(0)
                })?;
                Some((precinct, votes.checked_add(early_votes)?))
            })
            .collect();
        let mut reported = BTreeMap::<(NaiveDate, &str), u8>::new();
        for row in rows
            .iter()
            .filter(|r| r.method == "mail" || r.method == "in_person")
        {
            *reported
                .entry((row.date, row.precinct.as_deref().unwrap()))
                .or_default() |= if row.method == "mail" { 1 } else { 2 };
        }
        let latest = reported
            .into_iter()
            .filter(|((day, precinct), methods)| {
                *methods == 3
                    || *methods == 1
                        && (opening.is_some_and(|d| *day < d)
                            || *day > closing
                                && (measure == "daily" || final_early.contains_key(*precinct)))
            })
            .map(|((day, _), _)| day)
            .max();
        (values, latest)
    } else {
        let selected: Vec<_> = rows.into_iter().filter(|r| r.method == method).collect();
        (
            precinct_measure(&selected, date, measure, data.through),
            selected.iter().map(|r| r.date).max(),
        )
    };
    let rows: Vec<Value> = daily
        .into_iter()
        .map(|(precinct, votes)| json!({"precinct":precinct,"votes":votes}))
        .collect();
    Ok(
        json!({"state":state,"county":query.county,"date":date,"method":method,"measure":measure,"rows":rows,"comparison":false,"latest_reported":latest_reported,
        "scope":"Reported 2026 precinct observations only; cross-cycle precinct boundaries are unverified. Combined values require reported mail and in-person precinct components; outside official in-person dates, daily in-person is known zero; cumulative counts after closing require the verified final in-person total. Cumulative values sum reported records or use the exact published snapshot.","through":data.through}),
    )
}

fn precinct_measure(
    rows: &[&Observation],
    date: NaiveDate,
    measure: &str,
    through: NaiveDate,
) -> BTreeMap<String, u64> {
    let has_date = date <= through && rows.iter().any(|r| r.date == date);
    let mut daily = BTreeMap::<String, u64>::new();
    let mut exact = BTreeMap::<String, u64>::new();
    for row in rows.iter().filter(|r| has_date && r.date <= date) {
        let precinct = row.precinct.as_ref().unwrap();
        if row.measure == "daily" && (measure == "cumulative" || row.date == date) {
            *daily.entry(precinct.clone()).or_default() += row.votes;
        }
        if row.measure == measure && row.date == date {
            *exact.entry(precinct.clone()).or_default() += row.votes;
        }
    }
    if exact.is_empty() { daily } else { exact }
}

pub async fn refresh(root: &Path, through: Option<NaiveDate>) -> Result<()> {
    let mut jobs = tokio::task::JoinSet::new();
    for (id, _, script) in STATES {
        let root = root.to_path_buf();
        let cutoff = through.unwrap_or_else(|| {
            let tz = if id == "nv" {
                chrono_tz::America::Los_Angeles
            } else {
                chrono_tz::America::New_York
            };
            (Utc::now().with_timezone(&tz).date_naive() - Duration::days(1))
                .min(current_election() - Duration::days(1))
        });
        jobs.spawn(async move {
            let mut cmd = tokio::process::Command::new("python3");
            cmd.arg(root.join("scripts/states").join(script))
                .args(["--through", &cutoff.to_string()])
                .kill_on_drop(true);
            let result =
                tokio::time::timeout(std::time::Duration::from_secs(900), cmd.output()).await;
            match result {
                Ok(Ok(output)) if output.status.success() => eprintln!(
                    "{id} refresh: {}",
                    String::from_utf8_lossy(&output.stdout).trim()
                ),
                Ok(Ok(output)) => eprintln!(
                    "{id} refresh failed; retaining available observations: {}",
                    String::from_utf8_lossy(&output.stderr)
                        .chars()
                        .rev()
                        .take(1500)
                        .collect::<String>()
                        .chars()
                        .rev()
                        .collect::<String>()
                ),
                other => {
                    eprintln!("{id} refresh failed; retaining available observations: {other:?}")
                }
            }
        });
    }
    while let Some(result) = jobs.join_next().await {
        result?;
    }
    Ok(())
}

pub fn map(root: &Path, state: &str) -> Result<Value> {
    if !STATES.iter().any(|s| s.0 == state) {
        bail!("Unknown state");
    }
    Ok(serde_json::from_slice(&std::fs::read(
        root.join(format!("data/states/{state}-map.json")),
    )?)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn date(s: &str) -> NaiveDate {
        s.parse().unwrap()
    }
    fn fixture() -> Dataset {
        serde_json::from_value(json!({"id":"ga","name":"Georgia","generated_at":"test","through":"2026-10-23","start_dates":{"2024":"2024-10-21","2026":"2026-10-19"},"observations":[
            {"year":2024,"date":"2024-10-21","county":"a","measure":"daily","method":"in_person","votes":10},
            {"year":2024,"date":"2024-10-22","county":"a","measure":"daily","method":"in_person","votes":20},
            {"year":2024,"date":"2024-10-23","county":"a","measure":"daily","method":"in_person","votes":30},
            {"year":2026,"date":"2026-10-19","county":"a","measure":"daily","method":"in_person","votes":11},
            {"year":2026,"date":"2026-10-20","county":"b","measure":"daily","method":"in_person","votes":500},
            {"year":2026,"date":"2026-10-21","county":"a","measure":"daily","method":"in_person","votes":33}
        ]})).unwrap()
    }
    #[test]
    fn dates_and_measures_match_independently() {
        let data = fixture();
        let index = Index::new(&data);
        let members = vec!["a".into(), "b".into()];
        let out = series(
            &index,
            &[date("2026-10-19"), date("2026-10-20"), date("2026-10-21")],
            Scope {
                members: &members,
                method: "in_person",
                dimension: None,
            },
        );
        assert_eq!(out[0].daily_2026, Some(11));
        assert_eq!(out[0].daily_2024, Some(10));
        assert_eq!(out[1].daily_2026, None);
        assert_eq!(out[1].reported_daily_2026, Some(500));
        assert_eq!(out[2].daily_2026, Some(33));
        assert_eq!(out[2].cumulative_2026, None);
        assert_eq!(out[0].days_before_election, 15);
    }
    #[test]
    fn georgia_defaults_to_statewide_voter_race_without_inventing_unpaired_counts() {
        let folder = std::env::temp_dir().join(format!(
            "turnout-statewide-demographics-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        std::fs::create_dir_all(folder.join("data/states")).unwrap();
        let mut data = fixture();
        for row in &mut data.observations {
            row.breakdowns.insert(
                "race".into(),
                BTreeMap::from([
                    ("White".into(), row.votes / 2),
                    ("Black".into(), row.votes - row.votes / 2),
                ]),
            );
        }
        let mail_zeros = data
            .observations
            .iter()
            .cloned()
            .map(|mut row| {
                row.method = "mail".into();
                row.votes = 0;
                for groups in row.breakdowns.values_mut() {
                    for value in groups.values_mut() {
                        *value = 0;
                    }
                }
                row
            })
            .collect::<Vec<_>>();
        data.observations.extend(mail_zeros);
        std::fs::write(
            folder.join("data/states/ga.json"),
            serde_json::to_vec(&data).unwrap(),
        )
        .unwrap();
        let mut query = Query {
            date: Some(date("2026-10-19")),
            ..Query::default()
        };
        let result = view(&folder, "ga", &query).unwrap();
        assert_eq!(result["classification"], "race");
        assert_eq!(result["method"], "total");
        assert_eq!(result["method_labels"]["total"], "Mail + in person");
        let buckets = result["buckets"].as_array().unwrap();
        assert_eq!(buckets.len(), 2);
        assert_eq!(buckets[0]["label"], "Black");
        assert_eq!(buckets[0]["series"][0]["daily_2024"], 5);
        assert_eq!(buckets[0]["series"][0]["daily_2026"], 6);
        assert_eq!(buckets[0]["series"][0]["daily_members"], json!(["a"]));
        // The next day has only a current observation for B. Keep it as
        // reported, without putting it in the statewide paired comparison.
        assert_eq!(buckets[0]["series"][1]["reported_daily_2026"], 250);
        assert!(buckets[0]["series"][1]["daily_2026"].is_null());
        query.classification = Some("demographic".into());
        assert_eq!(
            view(&folder, "ga", &query).unwrap()["buckets"]
                .as_array()
                .unwrap()
                .len(),
            5
        );
        data.id = "nc".into();
        std::fs::write(
            folder.join("data/states/nc.json"),
            serde_json::to_vec(&data).unwrap(),
        )
        .unwrap();
        query.classification = None;
        assert_eq!(
            view(&folder, "nc", &query).unwrap()["classification"],
            "partisan"
        );
        std::fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    fn cumulative_anchor_recovers_following_dates_and_zero_is_real() {
        let mut data = fixture();
        data.observations.push(Observation {
            year: 2026,
            date: date("2026-10-20"),
            county: "a".into(),
            county_name: "".into(),
            precinct: None,
            measure: "cumulative".into(),
            method: "in_person".into(),
            votes: 25,
            breakdowns: BTreeMap::new(),
        });
        let index = Index::new(&data);
        assert_eq!(
            index
                .value(2026, date("2026-10-21"), "a", "in_person", "cumulative")
                .unwrap()
                .votes,
            58
        );
        assert!(
            index
                .value(2026, date("2026-10-20"), "a", "in_person", "daily")
                .is_none()
        );
        data.observations[3].votes = 0;
        let index = Index::new(&data);
        let members = vec!["a".into()];
        let out = series(
            &index,
            &[date("2026-10-19")],
            Scope {
                members: &members,
                method: "in_person",
                dimension: None,
            },
        );
        assert_eq!(out[0].daily_2026, Some(0));
    }
    #[test]
    fn future_baseline_does_not_create_current_votes() {
        let mut data = fixture();
        data.through = date("2026-10-20");
        let index = Index::new(&data);
        let members = vec!["a".into()];
        let out = series(
            &index,
            &[date("2026-10-21")],
            Scope {
                members: &members,
                method: "in_person",
                dimension: None,
            },
        );
        assert_eq!(out[0].daily_2024, Some(30));
        assert_eq!(out[0].daily_2026, None);
        assert!(out[0].future);
    }
    #[test]
    fn combined_defaults_pair_the_same_two_methods_in_both_cycles() {
        let folder = std::env::temp_dir().join(format!(
            "turnout-combined-default-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        std::fs::create_dir_all(folder.join("data/states")).unwrap();
        for (state, _, _) in STATES {
            let mut data = fixture();
            data.id = state.into();
            let mail = data
                .observations
                .iter()
                .cloned()
                .map(|mut row| {
                    row.method = "mail".into();
                    row.votes = if row.year == 2024 { 3 } else { 5 };
                    row
                })
                .collect::<Vec<_>>();
            data.observations.extend(mail);
            // Native COUNTABLE-like totals must not add other ballot categories.
            let native = data
                .observations
                .iter()
                .filter(|r| r.method == "in_person")
                .cloned()
                .map(|mut row| {
                    row.method = "total".into();
                    row.votes = 999;
                    row
                })
                .collect::<Vec<_>>();
            data.observations.extend(native);
            std::fs::write(
                folder.join(format!("data/states/{state}.json")),
                serde_json::to_vec(&data).unwrap(),
            )
            .unwrap();
            let mut query = Query {
                date: Some(date("2026-10-19")),
                classification: Some("partisan".into()),
                ..Query::default()
            };
            let result = view(&folder, state, &query).unwrap();
            assert_eq!(result["method"], "total");
            assert_eq!(result["series"][0]["cumulative_2024"], 13);
            assert_eq!(result["series"][0]["cumulative_2026"], 16);
            assert_eq!(result["series"][1]["reported_daily_2026"], 505);
            assert!(result["series"][1]["daily_2026"].is_null());
            query.method = Some("in_person".into());
            let early = view(&folder, state, &query).unwrap();
            assert_eq!(early["method"], "in_person");
            assert_eq!(early["series"][0]["cumulative_2024"], 10);
            assert_eq!(early["series"][0]["cumulative_2026"], 11);
            query.method = Some("mail".into());
            let mail = view(&folder, state, &query).unwrap();
            assert_eq!(mail["series"][0]["cumulative_2024"], 3);
            assert_eq!(mail["series"][0]["cumulative_2026"], 5);
        }
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn combined_turnout_retains_preopening_mail_but_not_missing_open_day_methods() {
        let mut data = fixture();
        for (year, day, votes) in [
            (2024, "2024-10-20", 7),
            (2026, "2026-10-18", 9),
            (2026, "2026-10-22", 20),
        ] {
            data.observations.push(serde_json::from_value(json!({"year":year,"date":day,"county":"a","measure":"cumulative","method":"mail","votes":votes,"breakdowns":{"race":{"Black":votes}}})).unwrap());
        }
        let index = Index::new(&data);
        let rows = series(
            &index,
            &[date("2026-10-18")],
            Scope {
                members: &["a".into()],
                method: "total",
                dimension: Some(("race", "Black")),
            },
        );
        assert_eq!(rows[0].cumulative_2024, Some(7));
        assert_eq!(rows[0].cumulative_2026, Some(9));
        assert!(
            index
                .value(2026, date("2026-10-22"), "a", "total", "cumulative")
                .is_none()
        );
    }

    #[test]
    fn combined_mail_after_early_close_requires_the_verified_final_in_person_count() {
        let mut data = fixture();
        data.id = "nv".into();
        data.through = date("2026-11-02");
        for (year, day, method, measure, votes) in [
            (2024, "2024-11-01", "in_person", "cumulative", 100),
            (2026, "2026-10-30", "in_person", "cumulative", 110),
            (2024, "2024-11-03", "mail", "cumulative", 20),
            (2026, "2026-11-01", "mail", "cumulative", 25),
            (2024, "2024-11-03", "mail", "daily", 4),
            (2026, "2026-11-01", "mail", "daily", 5),
        ] {
            data.observations.push(serde_json::from_value(json!({"year":year,"date":day,"county":"a","measure":measure,"method":method,"votes":votes})).unwrap());
        }
        let index = Index::new(&data);
        let out = series(
            &index,
            &[date("2026-11-01")],
            Scope {
                members: &["a".into()],
                method: "total",
                dimension: None,
            },
        );
        assert_eq!(out[0].cumulative_2024, Some(120));
        assert_eq!(out[0].cumulative_2026, Some(135));
        assert_eq!(out[0].daily_2024, Some(4));
        assert_eq!(out[0].daily_2026, Some(5));
        data.observations.retain(|r| {
            !(r.year == 2026 && r.method == "in_person" && r.date == date("2026-10-30"))
        });
        data.observations.push(serde_json::from_value(json!({"year":2026,"date":"2026-10-29","county":"a","measure":"cumulative","method":"in_person","votes":109})).unwrap());
        assert!(
            Index::new(&data)
                .value(2026, date("2026-11-01"), "a", "total", "cumulative")
                .is_none()
        );
    }

    #[test]
    fn combined_precinct_default_requires_both_components_and_ignores_native_extras() {
        let mut data = fixture();
        data.id = "va".into();
        data.counties = vec![json!({"id":"a"})];
        let rows=vec![
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"both","measure":"cumulative","method":"mail","votes":3}),
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"both","measure":"cumulative","method":"in_person","votes":12}),
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"early only","measure":"cumulative","method":"in_person","votes":40}),
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"early only","measure":"cumulative","method":"total","votes":999}),
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"mail only","measure":"cumulative","method":"mail","votes":2}),
            json!({"year":2026,"date":"2026-10-18","county":"a","precinct":"preopening mail","measure":"cumulative","method":"mail","votes":4})
        ].into_iter().map(|v|serde_json::from_value(v).unwrap()).collect::<Vec<_>>();
        let mut query = PrecinctQuery {
            county: "a".into(),
            date: Some(date("2026-10-20")),
            method: None,
            measure: None,
        };
        let combined = precincts_from(&data, &rows, &query).unwrap();
        assert_eq!(combined["method"], "total");
        assert_eq!(combined["rows"], json!([{"precinct":"both","votes":15}]));
        query.method = Some("in_person".into());
        assert_eq!(
            precincts_from(&data, &rows, &query).unwrap()["rows"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        query.method = None;
        query.date = Some(date("2026-10-18"));
        assert_eq!(
            precincts_from(&data, &rows, &query).unwrap()["rows"],
            json!([{"precinct":"preopening mail","votes":4}])
        );
        query.date = Some(date("2026-10-24"));
        assert_eq!(
            precincts_from(&data, &rows, &query).unwrap()["rows"],
            json!([])
        );
    }

    #[test]
    fn a_total_requires_both_voting_methods() {
        let data = fixture();
        let index = Index::new(&data);
        assert!(
            index
                .value(2026, date("2026-10-19"), "a", "total", "daily")
                .is_none()
        );
    }
    #[test]
    fn negative_revisions_do_not_become_daily_votes() {
        let mut data = fixture();
        for (d, n) in [("2026-10-22", 99), ("2026-10-23", 98)] {
            data.observations.push(Observation {
                year: 2026,
                date: date(d),
                county: "a".into(),
                county_name: "".into(),
                precinct: None,
                measure: "cumulative".into(),
                method: "in_person".into(),
                votes: n,
                breakdowns: BTreeMap::new(),
            });
        }
        let index = Index::new(&data);
        assert!(
            index
                .value(2026, date("2026-10-23"), "a", "in_person", "daily")
                .is_none()
        );
        assert_eq!(
            index
                .value(2026, date("2026-10-23"), "a", "in_person", "cumulative")
                .unwrap()
                .votes,
            98
        );
    }
    #[test]
    fn reported_precinct_snapshots_do_not_mix_retired_labels_or_carry_forward() {
        let folder = std::env::temp_dir().join(format!(
            "turnout-precinct-{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        let root = folder.join("dashboard");
        std::fs::create_dir_all(root.join("data/states")).unwrap();
        let mut data = fixture();
        data.counties = vec![json!({"id":"a","name":"A"})];
        for row in [
            json!({"year":2026,"date":"2026-10-19","county":"a","precinct":"retired name","measure":"daily","method":"in_person","votes":7}),
            json!({"year":2026,"date":"2026-10-20","county":"a","precinct":"current name","measure":"cumulative","method":"in_person","votes":12}),
            json!({"year":2024,"date":"2024-10-22","county":"a","precinct":"current name","measure":"cumulative","method":"in_person","votes":999}),
        ] {
            data.observations.push(serde_json::from_value(row).unwrap());
        }
        std::fs::write(
            root.join("data/states/ga.json"),
            serde_json::to_vec(&data).unwrap(),
        )
        .unwrap();
        let mut query = PrecinctQuery {
            county: "a".into(),
            date: Some(date("2026-10-20")),
            method: Some("in_person".into()),
            measure: Some("cumulative".into()),
        };
        let value = precincts(&root, "ga", &query).unwrap();
        assert_eq!(value["comparison"], false);
        assert_eq!(
            value["rows"],
            json!([{"precinct":"current name","votes":12}])
        );
        query.date = Some(date("2026-10-21"));
        let value = precincts(&root, "ga", &query).unwrap();
        assert_eq!(value["rows"], json!([]));
        assert_eq!(value["latest_reported"], "2026-10-20");
        query.county = "../other".into();
        assert!(precincts(&root, "ga", &query).is_err());
        std::fs::remove_dir_all(folder).unwrap();
    }
}
