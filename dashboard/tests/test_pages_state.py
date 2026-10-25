"""Anonymous aggregate deployment archive safety and round-trip coverage."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("package_pages_state", Path(__file__).resolve().parents[1] / "scripts/package_pages_state.py")
state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state)


class PagesStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "project"
        for path in state.REQUIRED:
            self.put(path, {"county": "Example", "votes": 100, "sources": [{"url": "https://example.org/data", "sha256": "abc"}]})
        self.put("dashboard/data/reference.json", [{"id": "example", "name": "Example"}])
        self.put("dashboard/data/statewide.json", {"schema_version": 2, "counties": [{"id": "example", "days": [{"by_method": {method: {} for method in ("in_person", "mail", "total")}}]}]})
        self.map_path = "dashboard/data/maps/example.geojson"
        self.put(self.map_path, {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"precinct": "P1"}, "geometry": {"type": "Point", "coordinates": [-97.5, 32.5]}}]})
        self.archive = self.directory / "aggregate-state.tar.gz"

    def put(self, path, document):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document))

    def rewrite(self, edit):
        members = []
        with tarfile.open(self.archive, "r:gz") as archive:
            for member in archive:
                members.append((member, archive.extractfile(member).read() if member.isfile() else None))
        members = edit(members)
        with tarfile.open(self.archive, "w:gz") as archive:
            for member, data in members:
                if data is not None:
                    member.size = len(data)
                archive.addfile(member, io.BytesIO(data) if data is not None else None)

    def assert_rejected_without_writes(self):
        target = self.directory / "restored"
        with self.assertRaises(ValueError):
            state.restore(target, self.archive)
        self.assertFalse(target.exists())

    def test_round_trip_preserves_aggregate_inputs_and_provenance(self):
        extras = ["dashboard/data/states/nc.json", "dashboard/data/maps/example.json", "sources/multistate/nc/precinct-daily.json", "sources/multistate/va/precincts/51001.json", "sources/multistate/nv/aggregate-cache/hash.json"]
        for path in extras:
            self.put(path, {"precinct_id": "P1", "name": "Example", "votes": 2, "notes": "NCID is never published"})
        result = state.package(self.root, self.archive)
        target = self.directory / "restored"
        restored = state.restore(target, self.archive)
        self.assertEqual(restored["restored_files"], len(state.REQUIRED) + len(extras) + 1)
        self.assertEqual(result["uncompressed_bytes"], restored["uncompressed_bytes"])
        self.assertTrue(Path(result["manifest"]).is_file())
        for path in state.REQUIRED | set(extras) | {self.map_path}:
            self.assertEqual((self.root / path).read_bytes(), (target / path).read_bytes())

    def test_logs_snapshots_credentials_and_raw_downloads_are_excluded(self):
        for path in ["dashboard/data/private.log", "dashboard/data/server.pid", "dashboard/data/snapshots/old.json", "dashboard/data/original-hashes.json", "sources/multistate/ga/raw/credentials.json", "sources/multistate/nc/raw-voters.json"]:
            self.put(path, {"voter_id": "DO NOT PUBLISH"})
        state.package(self.root, self.archive)
        self.assertEqual(set(state.inspect_archive(self.archive)), state.REQUIRED | {self.map_path})

    def test_legacy_in_person_cache_cannot_replace_combined_bootstrap(self):
        state.package(self.root, self.archive)
        before = self.archive.read_bytes()
        self.put("dashboard/data/statewide.json", {"schema_version": 1, "counties": []})
        with self.assertRaisesRegex(ValueError, "Mail-capable"):
            state.package(self.root, self.archive)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_legacy_in_person_archive_is_rejected_before_restore_writes(self):
        state.package(self.root, self.archive)
        self.rewrite(lambda members: [(m, json.dumps({"schema_version": 1, "counties": []}).encode() if m.name == "dashboard/data/statewide.json" else data) for m, data in members])
        target = self.directory / "restored"
        with self.assertRaisesRegex(ValueError, "Mail-capable"):
            state.restore(target, self.archive)
        self.assertFalse(target.exists())

    def test_geojson_allowed_only_in_the_maps_tree(self):
        for path in ["dashboard/data/states/private.geojson", "dashboard/data/cache/private.geojson", "sources/multistate/va/precincts/private.geojson"]:
            self.assertFalse(state.allowed(path))
            self.put(path, {"voter_id": "private"})
        state.package(self.root, self.archive)
        records = state.inspect_archive(self.archive)
        self.assertIn(self.map_path, records)
        self.assertFalse(any("private.geojson" in path for path in records))

    def test_missing_reference_county_map_rejects_packaging(self):
        (self.root / self.map_path).unlink()
        with self.assertRaisesRegex(ValueError, "Missing required county maps"):
            state.package(self.root, self.archive)

    def test_legacy_archive_without_geojson_is_rejected_before_restoring(self):
        state.package(self.root, self.archive)
        def remove_maps(members):
            output = []
            for member, data in members:
                if member.name.endswith(".geojson"):
                    continue
                if member.name == state.MANIFEST:
                    manifest = json.loads(data)
                    manifest["files"] = [record for record in manifest["files"] if not record["path"].endswith(".geojson")]
                    manifest["total_bytes"] = sum(record["bytes"] for record in manifest["files"])
                    data = json.dumps(manifest).encode()
                output.append((member, data))
            return output
        self.rewrite(remove_maps)
        self.assert_rejected_without_writes()

    def test_sensitive_fields_are_rejected_recursively_and_normalized(self):
        for key in ["VUID", "ncid", "Voter_ID", "first_name", "last-name", "DOB", "Date Of Birth", "SSN", "Email", "phone", "street_address", "access_token", "api_key"]:
            with self.subTest(key=key):
                self.put("dashboard/data/states/test.json", {"observations": [{key: "private"}]})
                with self.assertRaisesRegex(ValueError, "Sensitive field"):
                    state.package(self.root, self.archive)
                self.assertFalse(self.archive.exists())

    def test_missing_core_input_is_rejected(self):
        (self.root / "dashboard/data/latest.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing required"):
            state.package(self.root, self.archive)

    def test_tampered_payload_is_rejected_before_destination_writes(self):
        state.package(self.root, self.archive)
        self.rewrite(lambda members: [(member, b'{"votes":999}') if member.name == "dashboard/data/latest.json" else (member, data) for member, data in members])
        self.assert_rejected_without_writes()

    def test_path_traversal_and_absolute_paths_are_rejected(self):
        for path in ["../outside.json", "/tmp/outside.json", "dashboard/data/states/../../private.json", "dashboard/data/states/./x.json", "dashboard\\data\\states\\x.json"]:
            with self.subTest(path=path):
                state.package(self.root, self.archive)
                def append(members):
                    member = tarfile.TarInfo(path)
                    return members + [(member, b"{}")]
                self.rewrite(append)
                self.assert_rejected_without_writes()

    def test_archive_symlink_and_duplicate_members_are_rejected(self):
        for kind in ["link", "duplicate"]:
            with self.subTest(kind=kind):
                state.package(self.root, self.archive)
                def append(members):
                    if kind == "duplicate":
                        return members + [members[0]]
                    member = tarfile.TarInfo("dashboard/data/states/link.json")
                    member.type, member.linkname = tarfile.SYMTYPE, "/tmp/private.json"
                    return members + [(member, None)]
                self.rewrite(append)
                self.assert_rejected_without_writes()

    def test_unlisted_member_is_rejected_even_with_allowed_path(self):
        state.package(self.root, self.archive)
        self.rewrite(lambda members: members + [(tarfile.TarInfo("dashboard/data/states/unlisted.json"), b"{}")])
        self.assert_rejected_without_writes()

    def test_destination_symlink_is_rejected_before_overwriting_other_inputs(self):
        state.package(self.root, self.archive)
        target = self.directory / "restored"
        (target / "dashboard/data").mkdir(parents=True)
        sentinel = target / "dashboard/data/latest.json"
        sentinel.write_text("user data")
        elsewhere = self.directory / "elsewhere"
        elsewhere.mkdir()
        (target / "dashboard/data/history.json").symlink_to(elsewhere / "history.json")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            state.restore(target, self.archive)
        self.assertEqual(sentinel.read_text(), "user data")
        self.assertFalse((elsewhere / "history.json").exists())

    def test_input_symlink_outside_root_is_rejected(self):
        outside = self.directory / "outside.json"
        outside.write_text("{}")
        link = self.root / "dashboard/data/states/link.json"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Unsafe aggregate"):
            state.package(self.root, self.archive)

    def test_size_limit_rejects_before_restore_writes(self):
        state.package(self.root, self.archive)
        with patch.object(state, "MAX_BYTES", 10):
            self.assert_rejected_without_writes()

    def test_existing_archive_remains_intact_when_sensitive_input_is_rejected(self):
        state.package(self.root, self.archive)
        previous = self.archive.read_bytes()
        self.put("dashboard/data/states/private.json", {"voter_id": "private"})
        with self.assertRaises(ValueError):
            state.package(self.root, self.archive)
        self.assertEqual(self.archive.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
