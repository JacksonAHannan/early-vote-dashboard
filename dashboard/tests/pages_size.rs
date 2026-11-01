//! Opt-in full publication check using restored anonymous release inputs.
use std::path::PathBuf;

#[test]
#[ignore = "requires restored release inputs and a fresh output directory; see sources/pages-size"]
fn retained_publication_fits_hosting_budget() {
    let root =
        PathBuf::from(std::env::var("TURNOUT_PAGES_ROOT").expect("dashboard input directory"));
    let out = PathBuf::from(std::env::var("TURNOUT_PAGES_OUTPUT").expect("fresh output directory"));
    assert!(!out.exists(), "Use a fresh directory for size measurements");
    let started = std::time::Instant::now();
    let summary = texas_turnout::pages::build(&root, &out).unwrap();
    let mut pending = vec![out.clone()];
    let mut bytes = 0;
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(dir).unwrap() {
            let entry = entry.unwrap();
            let kind = entry.file_type().unwrap();
            assert!(!kind.is_symlink(), "Pages must not contain symlinks");
            if kind.is_dir() {
                pending.push(entry.path());
            } else if kind.is_file() {
                bytes += entry.metadata().unwrap().len();
            }
        }
    }
    println!(
        "site_bytes={bytes} elapsed_seconds={:.3} summary={}",
        started.elapsed().as_secs_f64(),
        serde_json::to_string(&summary).unwrap()
    );
    assert!(out.join("index.html").is_file());
    assert!(bytes <= 900_000_000, "Pages output exceeds 900 MB: {bytes}");
}
