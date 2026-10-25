#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["curl-cffi==0.16.3"]
# ///
"""Download only official aggregate county summaries; never voter rosters.

uv run dashboard/scripts/build_statewide.py --through 2026-10-23
Use --offline to rebuild from preserved aggregate caches without HTTP requests.
"""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2] / "dashboard"
CURRENT = "https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile"
HISTORICAL = "https://earlyvoting.texas-election.com/Elections/getEVDetails.do"


def atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(value)
    tmp.replace(path)


def integer(value) -> int | None:
    if value is None or str(value).strip() in ("", "-", "—", "N/A", "NA"):
        return None
    text = str(value).strip().replace(",", "")
    assert text.isdigit(), f"Non-count aggregate value: {value!r}"
    return int(text)


class Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.state_id = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row, self.state_id = [], None
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []
        if self.row is not None:
            click = dict(attrs).get("onclick", "")
            match = re.search(r"downloadReport\(['\"](\d+)['\"]\)", click)
            if match:
                self.state_id = int(match[1])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.row, self.state_id))
            self.row = None


def parse_historical(raw: bytes, when: date) -> list[dict]:
    text = raw.decode("utf-8-sig")
    table = Table()
    table.feed(text)
    header = next(row for row, state_id in table.rows if row and row[0] == "County")
    assert header[1:4] == ["Registered Voters", f"# In Person On {when:%m/%d/%Y}", "Cumulative In-Person Voters"]
    rows = [{"state_id": state_id, "name": row[0], "registered": integer(row[1]),
             "votes": integer(row[2]), "cumulative": integer(row[3])}
            for row, state_id in table.rows if state_id is not None]
    total = next(row for row, state_id in table.rows if row and row[0] == "TOTAL")
    for key, column in [("registered", 1), ("votes", 2), ("cumulative", 3)]:
        assert sum(row[key] or 0 for row in rows) == integer(total[column]), (when, key)
    return rows


def fetch(spec: tuple[int, date], offline: bool) -> tuple[dict | None, dict | None]:
    year, when = spec
    path = ROOT / f"data/statewide-cache/{year}/{when}.json"
    cached = json.loads(path.read_text()) if path.exists() else None
    if offline or (year == 2024 and cached):
        assert cached, f"Missing offline aggregate cache {when}"
        return cached, None
    url = CURRENT if year == 2026 else HISTORICAL
    form = None
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome")
        if year == 2026:
            from urllib.parse import urlencode
            url += "?" + urlencode({"type": "EVR_EARLYVOTING", "electionId": 53815,
                                    "electionDate": when.strftime("%m/%d/%Y")})
            response = session.get(url, timeout=90)
            response.raise_for_status()
            transport = response.content
            payload = json.loads(transport)
            raw = base64.b64decode(payload["upload"].split(",")[-1])
            native = json.loads(raw)
            assert native["early_voting_date"] == str(when) and native["election_id"] == 53815
            rows = [{"state_id": int(row["id"]), "name": row["name"],
                     "registered": integer(row.get("registered_voters")),
                     "votes": integer(row.get("in_person_votes_on_date")),
                     "cumulative": integer(row.get("total_in_person_votes_for_election"))}
                    for row in native["turnout_by_county"]]
            updated = native.get("date_updated")
        else:
            session.get("https://earlyvoting.texas-election.com/Elections/getElectionEVDates.do", timeout=45).raise_for_status()
            form = {"idElection": "49664", "selectedDate": f"{when} 00:00:00.0",
                    "pollPlaceIdtown": "", "electionDate": ","}
            response = session.post(url, data=form, timeout=90)
            response.raise_for_status()
            raw = transport = response.content
            rows = parse_historical(raw, when)
            updated = None
        assert len(rows) == 254 and len({row["state_id"] for row in rows}) == 254
        assert {row["state_id"] for row in rows} == set(range(1, 255))
        for row in rows:
            assert row["cumulative"] is None or row["votes"] is None or row["cumulative"] >= row["votes"]
        source = {"year": year, "date": str(when), "url": url,
                  "method": "GET" if form is None else "POST", "form": form,
                  "retrieved_at": datetime.now(timezone.utc).isoformat(),
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "transport_sha256": hashlib.sha256(transport).hexdigest(),
                  "rows": len(rows), "source_updated": updated, "status": "current"}
        cache = {"schema_version": 1, "year": year, "date": str(when), "rows": rows, "source": source}
        response_path = path.with_name(f"{when}.{source['sha256']}.response." + ("json" if year == 2026 else "html"))
        if not response_path.exists():
            atomic(response_path, raw)
        atomic(path, (json.dumps(cache, separators=(",", ":")) + "\n").encode())
        print(f"{when}: {len(rows)} aggregate county rows", flush=True)
        return cache, None
    except Exception as error:
        failure = {"year": year, "date": str(when), "url": url,
                   "error": str(error), "retained_cache": cached is not None}
        if cached:
            cached["source"]["status"] = "cached_after_error"
        print(f"{when}: {type(error).__name__}; retained_cache={cached is not None}", flush=True)
        return cached, failure


def build(caches: list[dict], through: date, errors: list[dict]) -> dict:
    identities = {}
    lookup = {}
    for cache in sorted(caches, key=lambda cache: cache["year"]):
        for row in cache["rows"]:
            identities[row["state_id"]] = row["name"]
            lookup[(cache["year"], cache["date"], row["state_id"])] = row
    counties = []
    for state_id, name in sorted(identities.items()):
        county = {"id": "".join(c for c in name.lower() if c.isascii() and c.isalnum()),
                  "name": {"MCLENNAN": "McLennan", "MCMULLEN": "McMullen", "DEWITT": "DeWitt"}.get(name, name.title()),
                  "state_id": state_id, "days": []}
        for index in range(12):
            dates = {2024: date(2024, 10, 21) + timedelta(days=index),
                     2026: date(2026, 10, 19) + timedelta(days=index)}
            day = {"day": index + 1, "date_2024": str(dates[2024]), "date_2026": str(dates[2026])}
            for year in (2024, 2026):
                row = lookup.get((year, str(dates[year]), state_id))
                if year == 2026 and dates[year] > through:
                    row = None
                    status = "future"
                elif row is None:
                    status = "unavailable"
                elif year == 2026 and row["votes"] == 0:
                    status = "zero_unconfirmed"
                else:
                    status = "reported" if row["votes"] is not None and row["cumulative"] is not None else "partial"
                confirmed = row is not None and status != "zero_unconfirmed"
                day[f"votes_{year}"] = row["votes"] if confirmed else None
                day[f"cumulative_{year}"] = row["cumulative"] if row and (
                    confirmed or (row["cumulative"] is not None and row["cumulative"] > 0)) else None
                day[f"registered_{year}"] = row["registered"] if row else None
                day[f"status_{year}"] = status
            county["days"].append(day)
        counties.append(county)
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "through": str(through), "counties": counties,
            "sources": [cache["source"] for cache in caches], "errors": errors,
            "scope": "Official Texas SOS aggregate in-person summaries. County ordinary-precinct series may have narrower categories and different totals. Current native daily zeros are unconfirmed and remain unavailable; native values are preserved in aggregate caches."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    specs = [(2024, date(2024, 10, 21) + timedelta(days=index)) for index in range(12)]
    specs += [(2026, date(2026, 10, 19) + timedelta(days=index)) for index in range(12)
              if date(2026, 10, 19) + timedelta(days=index) <= args.through]
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda spec: fetch(spec, args.offline), specs))
    caches = [cache for cache, error in results if cache]
    errors = [error for cache, error in results if error]
    data = build(caches, args.through, errors)
    assert len(data["counties"]) == 254, "A complete official county identity source is required"
    atomic(ROOT / "data/statewide.json", (json.dumps(data, separators=(",", ":")) + "\n").encode())
    print(f"Wrote {len(data['counties'])} counties, {len(caches)} aggregate source dates, {len(errors)} errors")


if __name__ == "__main__":
    main()
