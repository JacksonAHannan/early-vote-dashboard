//! Categorical place types derived from Census population and NCES locales.
//! Stable codes identify categories, never a numeric regression variable.
use crate::{county_buckets, demographics};
use anyhow::{Result, ensure};
use std::{collections::BTreeMap, path::Path};

pub const METRIC: &str = "place_type";
pub const LABELS: [&str; 6] = [
    "Rural Anglo",
    "Rural Hispanic",
    "Suburban",
    "Exurban",
    "Urban",
    "Other / unclassified",
];
pub fn is_metric(metric: &demographics::Metric) -> bool {
    metric.id == METRIC && metric.unit == "category"
}
pub fn path(root: &Path) -> std::path::PathBuf {
    root.join("places/texas.json")
}
pub fn load(root: &Path) -> Result<demographics::Data> {
    let data: demographics::Data = serde_json::from_slice(&std::fs::read(path(root))?)?;
    ensure!(
        data.schema_version == 1 && data.metrics.len() == 1 && is_metric(&data.metrics[0]),
        "Invalid place reference"
    );
    Ok(data)
}
/// Require a strict population majority. Missing/ambiguous geography is retained
/// in the residual category, while missing or invalid counts are unavailable.
pub fn classify(counts: &BTreeMap<String, f64>) -> Option<usize> {
    let value = |key: &str| {
        counts
            .get(key)
            .copied()
            .filter(|v| v.is_finite() && *v >= 0.0)
    };
    let vap = value("vap")?;
    let city = value("city_vap")?;
    let suburb = value("suburb_vap")?;
    let fringe = value("fringe_vap")?;
    let rural = value("rural_vap")?;
    let unknown = value("unclassified_vap")?;
    let white = value("white_nh_vap")?;
    let hispanic = value("hispanic_vap")?;
    if city + suburb + fringe + rural + unknown != vap
        || white > vap
        || hispanic > vap
        || white + hispanic > vap
    {
        return None;
    }
    Some(if city > vap / 2.0 {
        4
    } else if suburb > vap / 2.0 {
        2
    } else if fringe > vap / 2.0 {
        3
    } else if rural > vap / 2.0 && white > vap / 2.0 {
        0
    } else if rural > vap / 2.0 && hispanic > vap / 2.0 {
        1
    } else {
        5
    })
}
pub fn county_reference(
    reference: &mut county_buckets::Reference,
    data: &demographics::Data,
) -> Result<()> {
    for (id, county) in &mut reference.counties {
        let place = data
            .counties
            .get(id)
            .ok_or_else(|| anyhow::anyhow!("Missing place counts for {id}"))?;
        let counts: BTreeMap<String, Option<f64>> =
            serde_json::from_value(place.assigned_totals.clone())?;
        // Both are the same decennial county population; reject incompatible joins.
        for field in ["population", "vap", "white_nh_vap", "hispanic_vap"] {
            ensure!(
                county.counts.get(field) == counts.get(field),
                "Place/Census county mismatch: {id}/{field}"
            );
        }
        county.counts.extend(counts);
    }
    reference.metrics.extend(data.metrics.iter().cloned());
    reference.sources.extend(data.sources.iter().cloned());
    reference.method.push(' ');
    reference.method.push_str(&data.method);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn counts(
        city: f64,
        suburb: f64,
        fringe: f64,
        rural: f64,
        white: f64,
        hisp: f64,
    ) -> BTreeMap<String, f64> {
        [
            ("vap", 100.0),
            ("city_vap", city),
            ("suburb_vap", suburb),
            ("fringe_vap", fringe),
            ("rural_vap", rural),
            ("unclassified_vap", 0.0),
            ("white_nh_vap", white),
            ("hispanic_vap", hisp),
        ]
        .into_iter()
        .map(|(k, v)| (k.into(), v))
        .collect()
    }
    #[test]
    fn geographic_majorities_and_rural_composition_are_distinct() {
        assert_eq!(classify(&counts(60., 10., 10., 20., 20., 70.)), Some(4));
        assert_eq!(classify(&counts(10., 60., 10., 20., 20., 70.)), Some(2));
        assert_eq!(classify(&counts(10., 10., 60., 20., 20., 70.)), Some(3));
        assert_eq!(classify(&counts(10., 10., 10., 70., 70., 20.)), Some(0));
        assert_eq!(classify(&counts(10., 10., 10., 70., 20., 70.)), Some(1));
    }
    #[test]
    fn ties_and_other_rural_populations_are_not_called_anglo() {
        assert_eq!(classify(&counts(50., 0., 0., 50., 70., 20.)), Some(5));
        assert_eq!(classify(&counts(0., 0., 0., 100., 40., 40.)), Some(5));
        assert_eq!(classify(&counts(0., 0., 0., 100., 50., 50.)), Some(5));
    }
    #[test]
    fn zero_population_is_retained_in_the_residual_place_category() {
        let c = counts(0., 0., 0., 0., 0., 0.)
            .into_keys()
            .map(|k| (k, 0.))
            .collect();
        assert_eq!(classify(&c), Some(5));
    }
    #[test]
    fn incomplete_invalid_and_zero_population_are_explicit() {
        let mut c = counts(0., 0., 0., 100., 70., 20.);
        c.remove("city_vap");
        assert_eq!(classify(&c), None);
        let mut c = counts(0., 0., 0., 90., 70., 20.);
        c.insert("unclassified_vap".into(), 10.);
        assert_eq!(classify(&c), Some(0));
        c.insert("rural_vap".into(), 100.);
        assert_eq!(classify(&c), None);
        let mut c = counts(0., 0., 0., 100., 70., 20.);
        c.insert("vap".into(), 0.);
        assert_eq!(classify(&c), None);
    }
}
