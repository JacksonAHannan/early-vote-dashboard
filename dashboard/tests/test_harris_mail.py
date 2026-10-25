"""Focused Harris received-mail admission and local-quarantine tests."""
import datetime as dt
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("collect_harris_mail", SCRIPTS / "collect_harris_mail.py")
mail = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mail
SPEC.loader.exec_module(mail)
DAY = dt.date(2026, 10, 19)


def archive(rows):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as stream:
        stream.writestr("BBM.csv", "StateVoterID,IDNumber,Precinct,ActivityDate,Name\r\n" + rows)
    return output.getvalue()


def controls(roster, dates):
    return {(roster.year, when.isoformat(), method, measure): {"count": sum(roster.counts(method, when, measure == "cumulative").values()), "complete": True, "source": {"url": "https://county.example/control", "sha256": "fixture"}} for when in dates for method in ("mail", "in_person") for measure in ("daily", "cumulative")}


class HarrisMailTests(unittest.TestCase):
    def test_exact_record_copies_are_removed_and_correction_explains_raw_control(self):
        roster = mail.Roster(2026)
        row = "s1,c1,0001,10/19/2026,Example\r\n"
        roster.read_zip(archive(row + row), "mail")
        self.assertEqual(roster.statistics["byte_identical_copies_removed"], 1)
        self.assertFalse(roster.quarantine)
        control = controls(roster, [DAY])
        control[(2026, str(DAY), "mail", "cumulative")]["count"] = 2
        result = mail.observation(roster, {"1", "2"}, DAY, 1, "mail", "cumulative", control)
        self.assertEqual(result["counts"], {"1": 1, "2": 0})
        self.assertEqual(result["validation"][0]["reason"], "raw_roster_equals_control_with_proven_exact_copy_correction")

    def test_nonidentical_records_are_never_silently_deduplicated(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,10/19/2026,Example\r\ns1,c1,1,10/19/2026,Changed\r\n"), "mail")
        self.assertEqual(roster.statistics["byte_identical_copies_removed"], 0)
        self.assertEqual(roster.quarantine, {"1": DAY})
        self.assertIn("nonidentical_identity_repeat", roster.reasons["1"])

    def test_ambiguous_precinct_date_preserves_other_precincts_and_earlier_days(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,10/19/2026,A\r\ns1,c1,2,10/20/2026,A\r\ns2,c2,3,10/19/2026,B\r\n"), "mail")
        tomorrow = DAY + dt.timedelta(days=1)
        control = controls(roster, [DAY, tomorrow])
        old = mail.observation(roster, {"1", "2", "3"}, DAY, 1, "mail", "cumulative", control)
        new = mail.observation(roster, {"1", "2", "3"}, tomorrow, 2, "mail", "cumulative", control)
        self.assertEqual(old["counts"], {"1": 1, "2": 0, "3": 1})
        self.assertEqual(new["counts"], {"3": 1})
        self.assertEqual(new["quarantined_precincts"], ["1", "2"])

    def test_surrender_overlap_quarantines_both_affected_precincts_from_overlap_day(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,09/30/2026,A\r\ns2,c2,3,10/19/2026,B\r\n"), "mail")
        roster.read_zip(archive("s1,c1,2,10/20/2026,A\r\n"), "in_person")
        self.assertEqual(roster.quarantine, {"1": DAY + dt.timedelta(days=1), "2": DAY + dt.timedelta(days=1)})
        control = controls(roster, [DAY, DAY + dt.timedelta(days=1)])
        first = mail.observation(roster, {"1", "2", "3"}, DAY, 1, "total", "cumulative", control)
        second = mail.observation(roster, {"1", "2", "3"}, DAY + dt.timedelta(days=1), 2, "total", "cumulative", control)
        self.assertEqual(first["counts"]["1"], 1)
        self.assertEqual(second["counts"], {"3": 1})

    def test_preopening_mail_counts_only_in_cumulative_not_opening_daily(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,09/30/2026,A\r\ns2,c2,1,10/19/2026,B\r\n"), "mail")
        control = controls(roster, [DAY])
        cumulative = mail.observation(roster, {"1"}, DAY, 1, "mail", "cumulative", control)
        daily = mail.observation(roster, {"1"}, DAY, 1, "mail", "daily", control)
        self.assertEqual(cumulative["counts"]["1"], 2)
        self.assertEqual(daily["counts"]["1"], 1)

    def test_missing_or_negative_controls_do_not_create_precinct_zeros(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,10/19/2026,A\r\n"), "mail")
        for control in ({}, {(2026, str(DAY), "mail", "cumulative"): {"count": -1, "complete": True}}):
            result = mail.observation(roster, {"1", "2"}, DAY, 1, "mail", "cumulative", control)
            self.assertFalse(result["complete_roster"])
            self.assertEqual(result["counts"], {})
            self.assertEqual(result["unknown_precincts"], 2)

    def test_unexplained_county_gap_is_not_allocated(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,1,10/19/2026,A\r\n"), "mail")
        control = controls(roster, [DAY])
        control[(2026, str(DAY), "mail", "cumulative")]["count"] = 20
        result = mail.observation(roster, {"1", "2"}, DAY, 1, "mail", "cumulative", control)
        self.assertEqual(result["counts"], {})
        self.assertEqual(result["validation"][0]["reason"], "roster_control_mismatch")

    def test_unknown_precinct_cannot_be_spread_across_known_reference_precincts(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive("s1,c1,,10/19/2026,A\r\n"), "mail")
        result = mail.observation(roster, {"1", "2"}, DAY, 1, "mail", "cumulative", controls(roster, [DAY]))
        self.assertEqual(result["counts"], {})
        self.assertEqual(result["validation"][0]["reason"], "unassigned_precinct_prevents_complete_partition")

    def test_normalization_matches_reference_padding_and_letter_suffixes(self):
        self.assertEqual(mail.normalize("001A"), "1A")
        self.assertEqual(mail.normalize("000A"), "A")
        self.assertEqual(mail.normalize("0000"), "0")
        self.assertEqual(mail.normalize(""), "UNASSIGNED")

    def test_blank_identity_only_excludes_its_precinct_and_never_reaches_audit(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive(",,1,10/19/2026,A\r\nSECRET-STATE,SECRET-COUNTY,2,10/19/2026,B\r\n"), "mail")
        control = controls(roster, [DAY])
        result = mail.observation(roster, {"1", "2", "3"}, DAY, 1, "mail", "cumulative", control)
        self.assertEqual(result["counts"], {"2": 1, "3": 0})
        public = json.dumps(roster.public_audit()) + json.dumps(result)
        self.assertNotIn("SECRET", public)
        self.assertNotIn("fingerprint", public)

    def test_available_county_identifier_preserves_rows_without_state_identifier(self):
        roster = mail.Roster(2026)
        roster.read_zip(archive(",c1,1,10/19/2026,A\r\n"), "mail")
        self.assertFalse(roster.quarantine)
        self.assertEqual(roster.counts("mail", DAY, True), {"1": 1})
        roster.read_zip(archive("s1,c1,2,10/20/2026,A\r\n"), "in_person")
        self.assertEqual(roster.quarantine, {"1": DAY + dt.timedelta(days=1), "2": DAY + dt.timedelta(days=1)})

    def test_content_addressed_historical_cache_is_verified_before_legacy_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "dashboard/data/statewide-cache/2024"
            base.mkdir(parents=True)
            current = b"current official aggregate"
            digest = hashlib.sha256(current).hexdigest()
            (base / f"{DAY}.json").write_text(json.dumps({"source": {"sha256": digest}}))
            (base / f"{DAY}.{digest}.response.html").write_bytes(current)
            (base / f"{DAY}.response.html").write_bytes(b"stale aggregate")
            with patch.object(mail, "ROOT", Path(directory)), patch.object(mail, "fetch") as fetch:
                self.assertEqual(mail.historical_bytes(DAY), current)
                fetch.assert_not_called()

    def test_pdf_opening_mail_cell_is_cumulative_anchor(self):
        fake = b"November 3, 2026\nEarly In-Person Voters: 10 12 0 0 0 0 0 0 0 0 0 0 22\nMail Ballots Received: 8 3 0 0 0 0 0 0 0 0 0 0 11\nTotal Early Voters: 18 15 0 0 0 0 0 0 0 0 0 0 33\n"
        with patch.object(mail.subprocess, "run", return_value=type("Result", (), {"stdout": fake})()):
            control = mail.pdf_controls(b"fixture PDF", DAY + dt.timedelta(days=1))
        self.assertEqual(control[(2026, str(DAY), "mail", "cumulative")]["count"], 8)
        self.assertNotIn((2026, str(DAY), "mail", "daily"), control)
        self.assertEqual(control[(2026, str(DAY + dt.timedelta(days=1)), "mail", "daily")]["count"], 3)

    def test_paired_availability_matches_each_date_and_geographic_group(self):
        observations = [{"year": 2024, "day": 1, "method": "mail", "measure": "cumulative", "counts": {"1": 1, "2": 0}}, {"year": 2026, "day": 1, "method": "mail", "measure": "cumulative", "counts": {"10": 0}}]
        groups = [{"old": ["1"], "new": ["10"]}, {"old": ["2"], "new": ["20"]}]
        self.assertEqual(mail.paired_coverage(observations, groups), [{"day": 1, "method": "mail", "measure": "cumulative", "matched_groups": 1}])

    def test_rejected_refresh_preserves_last_good_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output, audit = Path(directory) / "harris.json", Path(directory) / "audit.json"
            output.write_text('{"last_good":true}\n')
            summary = mail.publish({"accepted": False, "observations": []}, output, audit)
            self.assertEqual(output.read_text(), '{"last_good":true}\n')
            self.assertFalse(summary["last_good_replaced"])
            self.assertTrue((Path(directory) / "harris-candidate.json").is_file())


if __name__ == "__main__":
    unittest.main()
