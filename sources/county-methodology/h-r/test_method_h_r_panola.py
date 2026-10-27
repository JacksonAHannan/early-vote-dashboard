import datetime as dt
import importlib.util
from pathlib import Path
import unittest


def collector():
    path = Path(__file__).resolve().parents[3]/"dashboard/scripts/collect_panola.py"
    spec = importlib.util.spec_from_file_location("collect_panola", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(identity="1000000001", label="S 2.1", method="EV EV", day="20261020", election="53815"):
    return f"DPanola   183{identity}    {election}   SYNTHETIC\n19000101\n{method} {day} 08:00 15096\n2    {label}\n"


def document(*records):
    return "HPanola   183VRH 20261020170551\n" + "".join(records) + f"TPanola   183{len(records)}\n"


class PanolaTests(unittest.TestCase):
    def test_printed_vrh_recovers_split_label_without_truncating(self):
        m = collector()
        self.assertEqual(m.parse_panola(document(record()), dt.date(2026, 10, 20)), [("1000000001", "S2.1")])

    def test_real_pdf_page_break_is_a_record_boundary(self):
        text = document(record().rstrip() + "\f" + record(identity="1000000002", label="P8"))
        self.assertEqual(len(collector().parse_panola(text, dt.date(2026, 10, 20))), 2)

    def test_first_batch_trailer_excludes_overlapping_print_fragment(self):
        text = document(record()) + "19000101\nEV EV 20261020 08:00 15096\n2 S2.1\nTPanola 1831\n"
        self.assertEqual(collector().parse_panola(text, dt.date(2026, 10, 20)), [("1000000001", "S2.1")])

    def test_blank_and_short_ids_are_retained_as_unavailable_rows(self):
        for identity in ["", "123456789"]:
            with self.subTest(identity_length=len(identity)):
                rows = collector().parse_panola(document(record(), record(identity=identity, label="P8")), dt.date(2026, 10, 20))
                self.assertEqual(rows[-1], ("", "P8"))

    def test_wrong_date_election_scope_and_truncated_rows_rejected(self):
        m = collector()
        for text in [document(record(day="20261021")), document(record(election="99999")),
                     document(record(method="EV AV")), document(record()).rsplit("2    S", 1)[0]]:
            with self.subTest(text_shape=len(text)), self.assertRaises(ValueError):
                m.parse_panola(text, dt.date(2026, 10, 20))

    def test_no_records_never_becomes_confirmed_zero(self):
        with self.assertRaises(ValueError):
            collector().parse_panola(document(), dt.date(2026, 10, 20))

    def test_split_label_targets_consider_foreign_and_duplicate_id(self):
        m = collector()
        native = {dt.date(2026, 10, 19): {"rows": [("1000000001", "S2.1"), ("1000000002", "S2.1")]}}
        state = {dt.date(2026, 10, 19): [("1000000001", "2"), ("1000000002", "FOREIGN")]}
        aliases, _, _ = m.prove_aliases(native, state, {"2"})
        self.assertEqual(aliases, {})
        state[dt.date(2026, 10, 19)] = [("1000000001", "2"), ("1000000001", "2")]
        aliases, _, _ = m.prove_aliases(native, state, {"2"})
        self.assertEqual(aliases, {})

    def test_one_bad_day_does_not_discard_independent_good_day(self):
        m = collector()
        files, errors = m.collect_files({dt.date(2026, 10, 20): "good", dt.date(2026, 10, 21): "bad"},
                                        lambda url: document(record()).encode() if url == "good" else b"bad",
                                        lambda raw: raw.decode())
        self.assertEqual(set(files), {dt.date(2026, 10, 20)})
        self.assertEqual(set(errors), {"2026-10-21"})

    def test_native_batch_count_must_reconcile_unique_and_blank_ids(self):
        m = collector()
        text = document(record()).replace("TPanola   1831", "TPanola   1832")
        files, errors = m.collect_files({dt.date(2026, 10, 20): "source"}, lambda _: text.encode(), lambda raw: raw.decode())
        self.assertEqual(files, {})
        self.assertIn("2026-10-20", errors)


if __name__ == "__main__":
    unittest.main()
