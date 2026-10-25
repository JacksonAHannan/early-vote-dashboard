//! Descriptive, unweighted OLS on the same geographic cohorts as the bucket table.
use crate::{GroupResult, Snapshot};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct Fit {
    pub intercept: f64,
    /// Turnout percentage points per percentage point of Harris two-party share.
    pub slope: f64,
    pub r_squared: Option<f64>,
    pub x_min: f64,
    pub x_max: f64,
}
#[derive(Serialize)]
pub struct Regression {
    pub county: String,
    pub day: u32,
    pub cohort: String,
    pub n: usize,
    pub omitted_zero_baseline: usize,
    pub fit: Option<Fit>,
}

pub fn xy(group: &GroupResult) -> Option<(f64, f64)> {
    let presidential = group.harris as f64 + group.trump as f64;
    if !group.available || group.votes_2024 == 0 || presidential == 0.0 {
        return None;
    }
    Some((
        100.0 * group.harris as f64 / presidential,
        100.0 * group.votes_2026 as f64 / group.votes_2024 as f64,
    ))
}
pub fn fit(points: &[(f64, f64)]) -> Option<Fit> {
    if points.len() < 2 || points.iter().any(|(x, y)| !x.is_finite() || !y.is_finite()) {
        return None;
    }
    let x_min = points.iter().map(|(x, _)| *x).fold(f64::INFINITY, f64::min);
    let x_max = points
        .iter()
        .map(|(x, _)| *x)
        .fold(f64::NEG_INFINITY, f64::max);
    if x_min == x_max {
        return None;
    }
    if points.iter().all(|(_, y)| *y == points[0].1) {
        return Some(Fit {
            intercept: points[0].1,
            slope: 0.0,
            r_squared: None,
            x_min,
            x_max,
        });
    }
    let n = points.len() as f64;
    let mean_x = points.iter().map(|(x, _)| x).sum::<f64>() / n;
    let mean_y = points.iter().map(|(_, y)| y).sum::<f64>() / n;
    let sxx = points
        .iter()
        .map(|(x, _)| (x - mean_x).powi(2))
        .sum::<f64>();
    if sxx <= 0.0 {
        return None;
    }
    let sxy = points
        .iter()
        .map(|(x, y)| (x - mean_x) * (y - mean_y))
        .sum::<f64>();
    let slope = sxy / sxx;
    let intercept = mean_y - slope * mean_x;
    let sst = points
        .iter()
        .map(|(_, y)| (y - mean_y).powi(2))
        .sum::<f64>();
    let sse = points
        .iter()
        .map(|(x, y)| (y - intercept - slope * x).powi(2))
        .sum::<f64>();
    Some(Fit {
        intercept,
        slope,
        r_squared: if sst > 0.0 {
            Some((1.0 - sse / sst).clamp(0.0, 1.0))
        } else {
            None
        },
        x_min,
        x_max,
    })
}
pub fn summaries(snapshot: &Snapshot) -> Vec<Regression> {
    let scopes: Vec<_> = std::iter::once("all")
        .chain(snapshot.counties.iter().map(|c| c.id.as_str()))
        .collect();
    let mut output = Vec::new();
    for day in 1..=snapshot.days {
        for cohort in ["matched", "unchanged"] {
            for scope in &scopes {
                let groups: Vec<_> = snapshot
                    .counties
                    .iter()
                    .filter(|c| *scope == "all" || c.id == *scope)
                    .filter_map(|c| c.periods.iter().find(|p| p.day == day))
                    .flat_map(|p| &p.groups)
                    .filter(|g| {
                        if !g.available {
                            return false;
                        }
                        if cohort == "unchanged" {
                            g.unchanged
                        } else {
                            g.bucket.is_some()
                        }
                    })
                    .collect();
                let points: Vec<_> = groups.iter().filter_map(|g| xy(g)).collect();
                output.push(Regression {
                    county: scope.to_string(),
                    day,
                    cohort: cohort.into(),
                    n: points.len(),
                    omitted_zero_baseline: groups.iter().filter(|g| g.votes_2024 == 0).count(),
                    fit: fit(&points),
                });
            }
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_noisy_ols_fit() {
        let f = fit(&[(0.0, 1.0), (1.0, 2.0), (2.0, 2.0)]).unwrap();
        assert!((f.intercept - 7.0 / 6.0).abs() < 1e-12);
        assert!((f.slope - 0.5).abs() < 1e-12);
        assert!((f.r_squared.unwrap() - 0.75).abs() < 1e-12);
        assert_eq!((f.x_min, f.x_max), (0.0, 2.0));
    }
    #[test]
    fn insufficient_or_constant_predictor_has_no_fit() {
        assert!(fit(&[]).is_none());
        assert!(fit(&[(50.0, 100.0)]).is_none());
        assert!(fit(&[(50.0, 70.0), (50.0, 100.0)]).is_none());
        assert!(fit(&[(f64::NAN, 1.0), (1.0, 2.0)]).is_none());
        assert!(fit(&[(0.1, 1.0), (0.1, 2.0), (0.1, 3.0)]).is_none());
    }
    #[test]
    fn constant_response_has_undefined_r_squared() {
        let f = fit(&[(0.0, 100.0), (100.0, 100.0)]).unwrap();
        assert_eq!(f.slope, 0.0);
        assert_eq!(f.intercept, 100.0);
        assert!(f.r_squared.is_none());
        let f = fit(&[(0.0, 0.1), (50.0, 0.1), (100.0, 0.1)]).unwrap();
        assert_eq!(f.slope, 0.0);
        assert_eq!(f.intercept, 0.1);
        assert!(f.r_squared.is_none());
    }
    #[test]
    fn zero_baseline_is_excluded_but_zero_current_is_valid() {
        let mut g = GroupResult {
            available: true,
            old: vec![],
            new: vec![],
            votes_2024: 0,
            votes_2026: 8,
            bucket: Some(0),
            unchanged: true,
            reason: String::new(),
            harris: 60,
            trump: 40,
        };
        assert!(xy(&g).is_none());
        g.votes_2024 = 10;
        g.votes_2026 = 0;
        assert_eq!(xy(&g), Some((60.0, 0.0)));
        g.votes_2026 = 48;
        assert_eq!(xy(&g), Some((60.0, 480.0)));
    }
}
