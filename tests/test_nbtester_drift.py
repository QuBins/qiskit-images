#!/usr/bin/env python3
"""Regression guard for the nb-tester drift check.

Dependency-free stdlib unittest, matching the other test modules, and
no network: upstream is always supplied from a fixture string.

The behaviours pinned here are the ones that decide whether the weekly
report is signal or noise. Both were got wrong on the first pass and
only showed up when the script was run against the real upstream file:

  1. `-r` includes must be followed. The xl set keeps its scientific
     stack in ../_xl-base.txt while upstream pins those same packages
     directly, so not following the include reported seven packages as
     missing that are in fact installed.
  2. "we leave it to pip" is policy, not drift. _xl-base.txt states
     scientific-stack packages stay unpinned; upstream pinning them
     must not trip the report.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check-nbtester-drift.py"


def _load():
    spec = importlib.util.spec_from_file_location("drift", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_canon_normalises_pep503(self):
        self.assertEqual(self.m.canon("qiskit_addon_slc"), "qiskit-addon-slc")
        self.assertEqual(self.m.canon("Qiskit.Addon_SLC"), "qiskit-addon-slc")

    def test_parses_specifiers_extras_and_markers(self):
        got = self.m.parse_requirements(
            "qiskit[all]~=2.5.2\n"
            "gem-suite~=0.2.0; platform_machine == \"x86_64\"\n"
            "# a comment\n"
            "\n"
            "pandas\n"
        )
        self.assertEqual(got["qiskit"], "~=2.5.2")
        self.assertEqual(got["gem-suite"], "~=0.2.0")
        self.assertEqual(got["pandas"], "")

    def test_direct_url_requirement(self):
        got = self.m.parse_requirements(
            "qiskit-device-benchmarking @ git+https://example.invalid/x.git@abc\n")
        self.assertEqual(got["qiskit-device-benchmarking"], "@url")

    def test_follows_r_includes_relative_to_the_including_file(self):
        """The bug that produced seven false 'missing' entries."""
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "versions").mkdir()
            (root / "versions" / "_base.txt").write_text("scipy\nplotly\n", encoding="utf-8")
            sub = root / "versions" / "2.5-xl"
            sub.mkdir()
            f = sub / "requirements.txt"
            f.write_text("-r ../_base.txt\nqiskit[all]~=2.5.2\n", encoding="utf-8")
            got = self.m.parse_requirements(f.read_text(encoding="utf-8"), f)
        self.assertIn("scipy", got)
        self.assertIn("plotly", got)
        self.assertIn("qiskit", got)

    def test_include_ignored_when_no_base_given(self):
        got = self.m.parse_requirements("-r ../_base.txt\nqiskit~=2.5\n")
        self.assertEqual(set(got), {"qiskit"})


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_unpinned_by_policy_is_not_drift(self):
        ours = {"scipy": "", "qiskit": "~=2.5.2"}
        theirs = {"scipy": "~=1.17.1", "qiskit": "~=2.5.2"}
        r = self.m.compare(ours, theirs)
        self.assertEqual(r["unpinned"], [("scipy", "~=1.17.1")])
        self.assertEqual(r["differing"], [])
        self.assertEqual(r["missing"], [])

    def test_real_version_difference_is_drift(self):
        r = self.m.compare({"qiskit-ibm-runtime": "~=0.47.0"},
                           {"qiskit-ibm-runtime": "~=0.49.0"})
        self.assertEqual(r["differing"],
                         [("qiskit-ibm-runtime", "~=0.47.0", "~=0.49.0")])

    def test_missing_upstream_package_is_drift(self):
        r = self.m.compare({}, {"qrmi": "~=0.25.1"})
        self.assertEqual(r["missing"], [("qrmi", "~=0.25.1")])

    def test_documented_exceptions_are_skipped_both_ways(self):
        ours = {"mthree": "~=1.0", "qiskit-experiments": "~=0.14.2"}
        theirs = {"mthree": "~=3.0.0", "qiskit-experiments": "~=0.14.1"}
        r = self.m.compare(ours, theirs)
        self.assertEqual(r["differing"], [])
        self.assertEqual(r["extra"], [])

    def test_ours_only_extras_are_not_reported(self):
        r = self.m.compare({"nbgitpuller": "", "pylatexenc": ""}, {})
        self.assertEqual(r["extra"], [])

    def test_genuinely_extra_package_is_reported(self):
        r = self.m.compare({"something-new": "~=1.0"}, {})
        self.assertEqual(r["extra"], [("something-new", "~=1.0")])

    def test_every_exception_carries_a_reason(self):
        for table in (self.m.EXCEPTIONS, self.m.OURS_ONLY, self.m.NOT_SHIPPED):
            for name, why in table.items():
                self.assertTrue(why.strip(), f"{name} has no documented reason")


if __name__ == "__main__":
    unittest.main()
