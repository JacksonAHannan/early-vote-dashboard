#!/usr/bin/env python3
"""Refresh only previously screened official URLs, aggregating raw CSV in pipes."""
import collections
import base64
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def aggregate(raw):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {"VOTING_METHOD", "PRECINCT", "ID_VOTER"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Official source schema changed")
    counts, methods, seen = collections.Counter(), collections.Counter(), set()
    duplicate_ids = blank_ids = rows = 0
    for row in reader:
        rows += 1
        method = row["VOTING_METHOD"]
        if method not in {"IN-PERSON", "MAIL-IN"}:
            raise ValueError("Unknown voting method")
        methods[method] += 1
        if method == "IN-PERSON":
            identity = row["ID_VOTER"].strip()
            duplicate_ids += identity in seen
            blank_ids += not bool(identity)
            seen.add(identity)
            precinct = row["PRECINCT"].strip().upper().lstrip("0") or "UNASSIGNED"
            counts[precinct] += 1
    return dict(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw), rows=rows,
                headers=reader.fieldnames, counts=dict(sorted(counts.items())),
                methods=dict(methods), duplicate_ids=duplicate_ids, blank_ids=blank_ids)


def refresh(path):
    probes = json.loads(path.read_text())
    for probe in probes:
        probe.pop("error", None)
        probe["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        result = subprocess.run(
            ["uv", "run", "--quiet", "--with", "curl-cffi==0.16.3", "--with", "playwright==1.64.1",
             "python", str(ROOT / "dashboard/scripts/transport.py")],
            input=json.dumps({"url": probe["source"]}).encode(), capture_output=True,
            timeout=145,
        )
        if result.returncode:
            probe["error"] = "Official browser-TLS transport failed; no response body retained"
        else:
            try:
                encoded = json.loads(result.stdout)["upload"].rsplit(",", 1)[-1]
                probe.update(aggregate(base64.b64decode(encoded, validate=True)))
            except (KeyError, TypeError, ValueError):
                probe["error"] = "Official endpoint has no valid daily CSV payload; no response body retained"
        print(json.dumps({k: probe[k] for k in ("county", "date", "sha256", "rows", "error") if k in probe}), flush=True)
        path.write_text(json.dumps(probes, indent=2) + "\n")


if __name__ == "__main__":
    refresh(Path(sys.argv[1]))
