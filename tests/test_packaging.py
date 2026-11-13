# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for scripts/package_plugin.py: build and validation (plain Python, no QGIS)."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "package_plugin.py")
spec = importlib.util.spec_from_file_location("package_plugin", SCRIPT)
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.version = pp.read_metadata(os.path.join(pp.SOURCE, "metadata.txt"))["version"]

    def build(self):
        return quiet(pp.build_zip, self.folder, self.version)

    def rewrite(self, source, target, drop=(), add=()):
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w") as new:
            for item in old.infolist():
                if item.filename not in drop:
                    new.writestr(item, old.read(item.filename))
            for name, data in add:
                new.writestr(name, data)
        return target

    def test_built_zip_is_valid(self):
        path = self.build()
        self.assertTrue(os.path.basename(path).startswith("contour-flow-"))
        names = quiet(pp.validate_zip, path, self.version)
        self.assertTrue(all(name.startswith("contour_flow/") for name in names))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_collect_skips_caches(self):
        relative = [rel for _path, rel in pp.collect_files()]
        self.assertIn("metadata.txt", relative)
        self.assertFalse(any("__pycache__" in rel or rel.endswith(".pyc") for rel in relative))

    def test_missing_required_file_fails(self):
        bad = self.rewrite(self.build(), os.path.join(self.folder, "bad.zip"), drop=("contour_flow/LICENSE",))
        with self.assertRaises(pp.PackagingError) as caught:
            quiet(pp.validate_zip, bad, self.version)
        self.assertIn("LICENSE", str(caught.exception))

    def test_forbidden_content_fails(self):
        for extra in ("contour_flow/__pycache__/x.cpython-312.pyc", "contour_flow/tests/test_x.py", ".git/config"):
            bad = self.rewrite(self.build(), os.path.join(self.folder, "bad.zip"), add=((extra, b"x"),))
            with self.assertRaises(pp.PackagingError, msg=extra):
                quiet(pp.validate_zip, bad, self.version)

    def test_second_top_level_folder_fails(self):
        bad = self.rewrite(self.build(), os.path.join(self.folder, "bad.zip"), add=(("README.md", b"x"),))
        with self.assertRaises(pp.PackagingError) as caught:
            quiet(pp.validate_zip, bad, self.version)
        self.assertIn("top-level", str(caught.exception))

    def test_version_mismatch_fails(self):
        path = self.build()
        with self.assertRaises(pp.PackagingError):
            quiet(pp.validate_zip, path, "9.9.9")


if __name__ == "__main__":
    unittest.main()
