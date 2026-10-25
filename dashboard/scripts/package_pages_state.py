#!/usr/bin/env python3
"""Package or restore only anonymous aggregate inputs for the public dashboard."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "aggregate-manifest.json"
MAX_BYTES = 1024 ** 3
MAX_FILES = 100_000
CORE_NAMES = (
    "latest", "history", "reference", "demographics", "primary", "statewide",
    "county-reference", "completeness",
)
REQUIRED = {f"dashboard/data/{name}.json" for name in CORE_NAMES}
EXACT = REQUIRED | {
    "sources/multistate/nc/precinct-daily.json",
    "sources/multistate/nc/county-fips-verification.json",
    "sources/multistate/va/precinct-daily.json",
    "sources/multistate/nv/reference-sources.json",
    "sources/multistate/nv/presidential-reference.json",
}
TREES = tuple(f"dashboard/data/{name}/" for name in (
    "cache", "history-cache", "statewide-cache", "maps", "states",
)) + ("sources/multistate/va/precincts/", "sources/multistate/nv/aggregate-cache/")
SENSITIVE_KEYS = {
    "vuid", "ncid", "voterid", "voteridentifier", "voteridentificationnumber",
    "voterregistrationid", "voterregistrationnumber", "ncvoterid", "statevoterid",
    "countyvoterid", "firstname", "middlename", "lastname", "surname", "fname",
    "lname", "dob", "dateofbirth", "birthdate", "birthday", "ssn",
    "socialsecuritynumber", "email", "emailaddress", "phone", "phonenumber",
    "telephone", "mobilephone", "streetaddress", "residentialaddress",
    "mailingaddress", "homeaddress", "driverslicense", "driverslicensenumber",
    "password", "accesstoken", "refreshtoken", "authorization", "apikey",
    "clientsecret", "secretkey", "privatekey", "sessioncookie",
}


def allowed(path):
    """Accept canonical POSIX paths from the explicit aggregate allowlist only."""
    if not isinstance(path, str) or "\\" in path or "\0" in path:
        return False
    parts = PurePosixPath(path)
    if parts.is_absolute() or str(parts) != path or any(p in (".", "..") for p in parts.parts):
        return False
    return path in EXACT or (path.endswith(".json") and any(path.startswith(prefix) for prefix in TREES)) or (path.startswith("dashboard/data/maps/") and path.endswith(".geojson"))


def validate_json(data, path):
    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON value in {path}: {value}")
    try:
        document = json.loads(data, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Invalid aggregate JSON in {path}") from error
    pending = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                if normalized in SENSITIVE_KEYS:
                    raise ValueError(f"Sensitive field {key!r} in {path}")
                pending.append(item)
        elif isinstance(value, list):
            pending.extend(value)
    if path == "dashboard/data/statewide.json":
        counties = document.get("counties") if isinstance(document, dict) else None
        if not isinstance(document, dict) or document.get("schema_version") != 2 or not isinstance(counties, list) or not counties:
            raise ValueError("Mail-capable Texas county aggregates are required; refresh or rebuild statewide inputs")
        for county in counties:
            days = county.get("days") if isinstance(county, dict) else None
            if not isinstance(days, list) or not days or any(not isinstance(day, dict) or not isinstance(day.get("by_method"), dict) or not {"in_person", "mail", "total"}.issubset(day["by_method"]) for day in days):
                raise ValueError("Mail-capable Texas county method series are missing")
    return document


def required_maps(reference):
    """Every supported Texas reference county must retain its linked geometry."""
    if not isinstance(reference, list) or not reference:
        raise ValueError("Texas county reference must be a nonempty list")
    counties = []
    for county in reference:
        county_id = county.get("id") if isinstance(county, dict) else None
        if not isinstance(county_id, str) or not re.fullmatch(r"[a-z0-9_-]+", county_id):
            raise ValueError("Invalid Texas reference county identifier")
        counties.append(county_id)
    if len(set(counties)) != len(counties):
        raise ValueError("Duplicate Texas reference county identifier")
    return {f"dashboard/data/maps/{county}.geojson" for county in counties}


def file_record(path, data):
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def atomic_write(destination, data):
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=".aggregate-", dir=destination.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def source_paths(root):
    paths = {path for path in EXACT if (root / path).is_file()}
    for prefix in TREES:
        paths.update(path.relative_to(root).as_posix() for path in (root / prefix).rglob("*.json") if path.is_file())
    paths.update(path.relative_to(root).as_posix() for path in (root / "dashboard/data/maps").rglob("*.geojson") if path.is_file())
    missing = REQUIRED - paths
    if missing:
        raise ValueError(f"Missing required aggregate files: {', '.join(sorted(missing))}")
    reference = validate_json((root / "dashboard/data/reference.json").read_bytes(), "dashboard/data/reference.json")
    missing_maps = required_maps(reference) - paths
    if missing_maps:
        raise ValueError(f"Missing required county maps: {', '.join(sorted(missing_maps))}")
    if len(paths) > MAX_FILES:
        raise ValueError("Too many aggregate files")
    return sorted(paths)


def package(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = source_paths(root)
    records, total = [], 0
    handle = tempfile.NamedTemporaryFile(prefix=".aggregate-", dir=output.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle, gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path in paths:
                source = root / path
                if not allowed(path) or source.is_symlink() or root not in source.resolve().parents:
                    raise ValueError(f"Unsafe aggregate input: {path}")
                if source.stat().st_size > MAX_BYTES - total:
                    raise ValueError("Aggregate inputs exceed the uncompressed size limit")
                data = source.read_bytes()
                total += len(data)
                if total > MAX_BYTES:
                    raise ValueError("Aggregate inputs exceed the uncompressed size limit")
                validate_json(data, path)
                records.append(file_record(path, data))
                member = tarfile.TarInfo(path)
                member.size, member.mode = len(data), 0o644
                archive.addfile(member, io.BytesIO(data))
            manifest = {"version": 1, "files": records, "total_bytes": total}
            data = (json.dumps(manifest, indent=2) + "\n").encode()
            member = tarfile.TarInfo(MANIFEST)
            member.size, member.mode = len(data), 0o644
            archive.addfile(member, io.BytesIO(data))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    sidecar = output.with_name(output.name.removesuffix(".tar.gz") + ".manifest.json")
    atomic_write(sidecar, data)
    return {"archive": str(output), "manifest": str(sidecar), "files": len(records), "uncompressed_bytes": total, "compressed_bytes": output.stat().st_size}


def inspect_archive(source):
    """Read and validate every member before allowing any destination changes."""
    observed, seen, manifest, total, reference = {}, set(), None, 0, None
    with tarfile.open(source, mode="r:gz") as archive:
        for member in archive:
            path = member.name
            if path in seen or not member.isfile() or (path != MANIFEST and not allowed(path)):
                raise ValueError(f"Unsafe, duplicate or non-aggregate archive member: {path}")
            seen.add(path)
            if len(seen) > MAX_FILES + 1 or member.size < 0 or member.size > MAX_BYTES - total:
                raise ValueError("Archive exceeds the uncompressed size or file limit")
            total += member.size
            data = archive.extractfile(member).read()
            if len(data) != member.size:
                raise ValueError(f"Truncated archive member: {path}")
            if path == MANIFEST:
                if len(data) > 10 * 1024 ** 2:
                    raise ValueError("Aggregate manifest is too large")
                try:
                    manifest = json.loads(data)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise ValueError("Invalid aggregate manifest") from error
            else:
                document = validate_json(data, path)
                if path == "dashboard/data/reference.json":
                    reference = document
                observed[path] = file_record(path, data)
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Missing or unsupported aggregate manifest")
    expected = {}
    for record in manifest["files"]:
        if not isinstance(record, dict) or not allowed(record.get("path")) or record["path"] in expected:
            raise ValueError("Invalid or duplicate manifest path")
        expected[record["path"]] = record
    if expected != observed or not REQUIRED.issubset(expected):
        raise ValueError("Aggregate manifest paths, hashes or sizes do not match archive")
    if required_maps(reference) - expected.keys():
        raise ValueError("Archive is missing required county maps from the Texas reference")
    if manifest.get("total_bytes") != sum(record["bytes"] for record in observed.values()):
        raise ValueError("Aggregate manifest total does not match archive")
    return observed


def safe_destination(root, path):
    destination = root / path
    if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents if parent != root and root in parent.parents):
        raise ValueError(f"Symlink destination rejected: {path}")
    if root not in destination.resolve().parents:
        raise ValueError(f"Destination escapes project root: {path}")
    if destination.exists() and not destination.is_file():
        raise ValueError(f"Destination is not a regular file: {path}")
    return destination


def restore(root, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    records = inspect_archive(source)
    # Validate every destination, including existing directory symlinks, up front.
    destinations = {path: safe_destination(root, path) for path in records}
    with tempfile.TemporaryDirectory(prefix="turnout-aggregate-restore-") as staging:
        staged = {}
        with tarfile.open(source, mode="r:gz") as archive:
            for member in archive:
                if member.name == MANIFEST:
                    continue
                if member.name not in records or not member.isfile() or member.name in staged or member.size != records[member.name]["bytes"]:
                    raise ValueError("Archive changed after validation")
                data = archive.extractfile(member).read()
                if file_record(member.name, data) != records[member.name] or member.name in staged:
                    raise ValueError("Archive changed after validation")
                temporary = Path(staging) / str(len(staged))
                temporary.write_bytes(data)
                staged[member.name] = temporary
        if staged.keys() != records.keys():
            raise ValueError("Archive changed after validation")
        for path, temporary in staged.items():
            atomic_write(destinations[path], temporary.read_bytes())
    return {"restored_files": len(records), "uncompressed_bytes": sum(record["bytes"] for record in records.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--restore", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = package(args.root, args.output) if args.output else restore(args.root, args.restore)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f"Aggregate state rejected: {error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
