import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class CountyMethodologyTests(unittest.TestCase):
    def test_every_assigned_county_has_exactly_one_row(self):
        screen = module("screen")
        actual = screen.screen()
        expected = json.loads((screen.ROOT / "analysis/county-methodology/h_r-counties.json").read_text())
        self.assertEqual(sorted(c["county"] for c in actual["counties"]), sorted(expected))
        self.assertEqual(actual["county_count"], 107)

    def test_source_partition_conserves_counts(self):
        for county in module("screen").screen()["counties"]:
            for source in county.get("source_count_audit", []):
                self.assertEqual(source["roster_total"], source["native_positive_total"] + source["unknown_positive_total"])

    def test_no_alias_from_a_foreign_or_ambiguous_target(self):
        helper = module("hunt_identity")
        pairs = [dict(sos_label="101-", native_prefix_candidate="101", rows=100),
                 dict(sos_label="101-", native_prefix_candidate="FOREIGN", rows=1),
                 dict(sos_label="102-", native_prefix_candidate="102", rows=5)]
        self.assertEqual(helper.all_targets(pairs, {"101", "102"}), {"102-": "102"})

    def test_mail_only_download_does_not_fabricate_inperson_zeros(self):
        result = module("probe_state").aggregate(b"VOTER_NAME,ID_VOTER,VOTING_METHOD,PRECINCT\nSynthetic,1,MAIL-IN,101\n")
        self.assertEqual(result["counts"], {})
        self.assertEqual(result["methods"], {"MAIL-IN": 1})

    def test_csv_keeps_unknown_labels_and_flags_duplicate_id(self):
        result = module("probe_state").aggregate(b"VOTER_NAME,ID_VOTER,VOTING_METHOD,PRECINCT\nSynthetic,1,IN-PERSON,0101-\nSynthetic,1,IN-PERSON,999\n")
        self.assertEqual(result["counts"], {"101-": 1, "999": 1})
        self.assertEqual(result["duplicate_ids"], 1)

    def test_changed_pdf_never_reuses_reviewed_panel_layout(self):
        with self.assertRaisesRegex(ValueError, "revised"):
            module("hunt_identity").county_identities(b"different public edition")


if __name__ == "__main__":
    unittest.main()
