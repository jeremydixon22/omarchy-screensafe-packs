import contextlib
import datetime
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("catalog", Path(__file__).resolve().parents[1] / "scripts/catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def entry(pid, **changes):
    return dict({
        "id": pid, "name": pid.title(), "author": "Maker", "contact": "https://github.com/maker",
        "repository": "https://github.com/maker/pack", "path": ".", "commit": "a" * 40,
        "license": "MIT", "preview": "preview.png", "description": "A screensaver.",
        "format": 1, "added": datetime.date(2026, 10, 16), "provenance": "Drawn by the maker.",
    }, **changes)


class PackSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "base.toml"

    def write_base(self, entries):
        blocks = []
        for e in entries:
            fields = [f"{k} = {v.isoformat() if isinstance(v, datetime.date) else json.dumps(v)}" for k, v in e.items()]
            blocks.append("[[pack]]\n" + "\n".join(fields))
        self.base.write_text("\n\n".join(blocks), encoding="utf-8")

    def selected(self, current):
        return [e["id"] for e in catalog.changed_packs(current, self.base)]

    def test_addition_skips_unchanged_existing_pack(self):
        self.write_base([entry("old")])
        self.assertEqual(self.selected([entry("new"), entry("old")]), ["new"])

    def test_changed_commit_is_verified(self):
        self.write_base([entry("pack")])
        self.assertEqual(self.selected([entry("pack", commit="b" * 40)]), ["pack"])

    def test_metadata_changes_are_verified(self):
        self.write_base([entry("pack")])
        for changes in [{"repository": "https://github.com/maker/other"}, {"path": "screensafe"},
                        {"preview": "new.png"}, {"license": "CC0-1.0"}, {"provenance": "New attribution."}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.selected([entry("pack", **changes)]), ["pack"])

    def test_removed_pack_is_not_fetched(self):
        self.write_base([entry("gone"), entry("kept")])
        self.assertEqual(self.selected([entry("kept")]), [])

    def test_reordering_does_not_recheck(self):
        self.write_base([entry("a"), entry("b")])
        self.assertEqual(self.selected([entry("b"), entry("a")]), [])

    def test_empty_catalog_selects_every_addition(self):
        self.write_base([])
        self.assertEqual(self.selected([entry("a"), entry("b")]), ["a", "b"])

    def test_missing_or_invalid_base_fails_closed(self):
        with self.assertRaises(catalog.Problem):
            self.selected([entry("new")])
        for contents in ["[", "pack = true", "pack = ['bad']", "[pack]\nid = 'bad'", "unknown = 1"]:
            with self.subTest(contents=contents):
                self.base.write_text(contents)
                with self.assertRaises(catalog.Problem):
                    self.selected([entry("new")])

    def test_invalid_or_duplicate_base_entries_fail_closed(self):
        for entries in [[{"id": "incomplete"}], [entry("a"), entry("a")]]:
            with self.subTest(entries=entries):
                self.write_base(entries)
                with self.assertRaises(catalog.Problem):
                    self.selected([entry("new")])

    def run_verify(self, entries, args):
        with (patch.object(catalog, "load", return_value=(entries, [])),
              patch.object(catalog, "renderer", return_value="renderer") as renderer,
              patch.object(catalog, "verify", return_value=(["passed"], ["screensafe.toml"])) as verify,
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            status = catalog.main(["catalog.py", "verify"] + args)
        return status, renderer, verify

    def test_empty_delta_never_fetches_renderer_or_packs(self):
        self.write_base([entry("unchanged")])
        status, renderer, verify = self.run_verify([entry("unchanged")], ["--changed-from", str(self.base)])
        self.assertEqual(status, 0)
        renderer.assert_not_called()
        verify.assert_not_called()

    def test_cli_verifies_only_changed_entries(self):
        self.write_base([entry("old")])
        status, renderer, verify = self.run_verify([entry("new"), entry("old")], ["--changed-from", str(self.base)])
        self.assertEqual(status, 0)
        self.assertEqual([call.args[0]["id"] for call in verify.call_args_list], ["new"])

    def test_full_and_explicit_id_modes_keep_working(self):
        for args, expected in [([], ["a", "b"]), (["b"], ["b"])]:
            with self.subTest(args=args):
                status, renderer, verify = self.run_verify([entry("a"), entry("b")], args)
                self.assertEqual(status, 0)
                self.assertEqual([call.args[0]["id"] for call in verify.call_args_list], expected)

    def test_invalid_base_never_runs_verification(self):
        status, renderer, verify = self.run_verify([entry("a")], ["--changed-from", str(self.base)])
        self.assertEqual(status, 1)
        renderer.assert_not_called()
        verify.assert_not_called()

    def test_missing_base_argument_fails(self):
        status, renderer, verify = self.run_verify([entry("a")], ["--changed-from"])
        self.assertEqual(status, 2)
        renderer.assert_not_called()
        verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
