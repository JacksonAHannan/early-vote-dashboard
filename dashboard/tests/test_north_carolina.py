"""Run with python3 -m unittest discover -s dashboard/tests -p test_north_carolina.py."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import json
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/states/north_carolina.py"
SPEC = importlib.util.spec_from_file_location("north_carolina", SCRIPT)
NC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NC)
HEADER = ["county_desc", "ncid", "voter_reg_num", "precinct_desc", "ballot_req_type", "ballot_rtn_dt", "ballot_rtn_status", "race", "ethnicity", "gender", "age", "voter_party_code"]


def row(identity="NC1", date="10/15/2026", status="ACCEPTED", kind="EARLY VOTING", race="WHITE", ethnicity="NOT HISPANIC or NOT LATINO"):
    return ["ALAMANCE", identity, identity, "P1", kind, date, status, race, ethnicity, "F", "65", "DEM"]


class NorthCarolinaTests(unittest.TestCase):
    def test_only_accepted_returned_ballots_and_duplicate_diagnostic(self):
        rows = [HEADER, row(), row(), row("NC2", status="PENDING CURE"), row("NC3", status="ACCEPTED - CURED", kind="MAIL"), row("NC4", date="10/24/2026")]
        daily, precincts, names, validation = NC.aggregate_records(iter(rows), 2026, "2026-10-23")
        self.assertEqual(daily["ALAMANCE", "2026-10-15", "total"]["votes"], 3)
        self.assertEqual(sum(precincts.values()), 3)
        self.assertEqual(validation["duplicate_accepted_records"], 1)
        self.assertEqual(validation["all_accepted_by_method"], {"in_person": 3, "mail": 1})
        self.assertEqual(names, ["ALAMANCE"])

    def test_joint_race_ethnicity_does_not_treat_unknown_as_nonwhite(self):
        index = {name: i for i, name in enumerate(HEADER)}
        self.assertEqual(NC.attributes(row(), index)["white_nonwhite"], "White non-Hispanic")
        self.assertEqual(NC.attributes(row(ethnicity="UNDESIGNATED"), index)["white_nonwhite"], "Undesignated")
        self.assertEqual(NC.attributes(row(race="UNDESIGNATED", ethnicity="UNDESIGNATED"), index)["white_nonwhite"], "Undesignated")
        self.assertEqual(NC.attributes(row(race="BLACK or AFRICAN AMERICAN", ethnicity="UNDESIGNATED"), index)["white_nonwhite"], "Non-white")
        self.assertEqual(NC.attributes(row(ethnicity="HISPANIC or LATINO"), index)["white_nonwhite"], "Non-white")

    def test_daily_and_cumulative_by_method_reconcile(self):
        daily, _, names, _ = NC.aggregate_records(iter([HEADER, row(), row("NC2", date="10/16/2026", kind="MAIL")]), 2026, "2026-10-23")
        rows = NC.observations(daily, names, {"ALAMANCE": "37001"}, 2026, "2026-10-23")
        result = {(r["date"], r["method"], r["measure"]): r for r in rows}
        self.assertEqual(result["2026-10-16", "total", "cumulative"]["votes"], 2)
        self.assertEqual(result["2026-10-16", "in_person", "daily"]["votes"], 0)
        self.assertEqual(result["2026-10-16", "in_person", "daily"]["breakdowns"]["party"]["Democratic"], 0)
        self.assertEqual(result["2026-10-16", "in_person", "daily"]["breakdowns"]["race"]["Asian"], 0)
        self.assertNotIn(("2026-10-17", "total", "daily"), result)
        for item in rows:
            for values in item["breakdowns"].values():
                self.assertEqual(sum(values.values()), item["votes"])

    def test_invalid_accepted_date_and_changed_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid return date"):
            NC.aggregate_records(iter([HEADER, row(date="")]), 2026, "2026-10-23")
        with self.assertRaisesRegex(ValueError, "schema changed"):
            NC.aggregate_records(iter([["county_desc"]]), 2026, "2026-10-23")

    def test_failed_download_retains_prior_successful_observations(self):
        old = [{"year": year, "date": f"{year}-10-17", "county_name": "Alamance", "votes": 20} for year in (2024, 2026)]
        cached = {"observations": old, "counties": [{"id": "37001", "name": "Alamance", "harris": 10, "trump": 20}], "sources": [], "validation": {}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nc.json"
            output.write_text(json.dumps(cached))
            with mock.patch.object(NC, "OUTPUT", output), mock.patch.object(NC, "SOURCES", Path(directory)), mock.patch.object(NC, "fetch", side_effect=OSError("HTTP 502")):
                result = NC.collect("2026-10-23")
                self.assertEqual(result["observations"], old)
                self.assertEqual(len(result["errors"]), 2)
                self.assertEqual(json.loads(output.read_text())["observations"], old)


if __name__ == "__main__":
    unittest.main()
