#!/usr/bin/env python3
"""Regression guard for the GHCR prune safety rails.

Deliberately small and dependency-free (stdlib unittest only — no
pytest, no network), matching test_security_invariants.py. Run with:
  python3 -m unittest discover tests

The prune script deletes registry versions irreversibly, and the
obvious implementation of it — "delete every untagged version" — would
destroy live images here, because the image and provenance manifests
inside today's per-arch index are untagged. These tests pin the
behaviors that make it safe, so a future refactor that weakens one
fails CI instead of quietly eating the registry:

  1. Reachability beats tag state: untagged children of a LIVE index
     are kept. This is the footgun the whole design exists for.
  2. Grace period: recently-pushed unreachable versions are kept, so
     an in-flight publish can't be collected mid-run.
  3. A stray human tag on an unreachable digest is kept.
  4. An orphaned cosign .sig (subject gone) IS collected, even though
     it carries a tag — otherwise signatures pin themselves forever.
  5. Dry run is the default and deletes nothing.
  6. The --max-delete floor refuses an oversized pass (exit 2).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "prune-ghcr-versions.py"


def _load():
    spec = importlib.util.spec_from_file_location("prune_ghcr", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NOW = time.time()


def _iso(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * 86400))


# A registry shaped exactly like ours: parent index -> two per-arch
# indexes -> (image manifest + provenance attestation), the last two
# untagged even though they are live.
_REG = {
    "2.5-xl":         {"manifests": [{"digest": "sha256:amd_idx"}, {"digest": "sha256:arm_idx"}]},
    "sha256:par_idx": {"manifests": [{"digest": "sha256:amd_idx"}, {"digest": "sha256:arm_idx"}]},
    "2.5-xl-amd64":   {"manifests": [{"digest": "sha256:amd_img"}, {"digest": "sha256:amd_att"}]},
    "sha256:amd_idx": {"manifests": [{"digest": "sha256:amd_img"}, {"digest": "sha256:amd_att"}]},
    "2.5-xl-arm64":   {"manifests": [{"digest": "sha256:arm_img"}, {"digest": "sha256:arm_att"}]},
    "sha256:arm_idx": {"manifests": [{"digest": "sha256:arm_img"}, {"digest": "sha256:arm_att"}]},
    "sha256:amd_img": {}, "sha256:amd_att": {},
    "sha256:arm_img": {}, "sha256:arm_att": {},
    "sha256-par_idx.sig": {}, "sha256:livesig": {},
}
_TAG2DIG = {
    "2.5-xl": "sha256:par_idx",
    "2.5-xl-amd64": "sha256:amd_idx",
    "2.5-xl-arm64": "sha256:arm_idx",
    "sha256-par_idx.sig": "sha256:livesig",
}

LIVE_UNTAGGED_CHILDREN = {4, 5, 6, 7}


def _versions():
    return [
        # --- today's live generation ---
        {"id": 1, "name": "sha256:par_idx", "updated_at": _iso(0),
         "metadata": {"container": {"tags": ["2.5-xl"]}}},
        {"id": 2, "name": "sha256:amd_idx", "updated_at": _iso(0),
         "metadata": {"container": {"tags": ["2.5-xl-amd64"]}}},
        {"id": 3, "name": "sha256:arm_idx", "updated_at": _iso(0),
         "metadata": {"container": {"tags": ["2.5-xl-arm64"]}}},
        # the footgun: untagged, but children of a live index
        {"id": 4, "name": "sha256:amd_img", "updated_at": _iso(0),
         "metadata": {"container": {"tags": []}}},
        {"id": 5, "name": "sha256:amd_att", "updated_at": _iso(0),
         "metadata": {"container": {"tags": []}}},
        {"id": 6, "name": "sha256:arm_img", "updated_at": _iso(0),
         "metadata": {"container": {"tags": []}}},
        {"id": 7, "name": "sha256:arm_att", "updated_at": _iso(0),
         "metadata": {"container": {"tags": []}}},
        {"id": 8, "name": "sha256:livesig", "updated_at": _iso(0),
         "metadata": {"container": {"tags": ["sha256-par_idx.sig"]}}},
        # --- unreachable, but inside the grace window ---
        {"id": 20, "name": "sha256:old_recent", "updated_at": _iso(3),
         "metadata": {"container": {"tags": []}}},
        # --- genuinely collectable ---
        {"id": 21, "name": "sha256:old_a", "updated_at": _iso(40),
         "metadata": {"container": {"tags": []}}},
        {"id": 22, "name": "sha256:old_b", "updated_at": _iso(90),
         "metadata": {"container": {"tags": []}}},
        {"id": 23, "name": "sha256:deadsig", "updated_at": _iso(60),
         "metadata": {"container": {"tags": ["sha256-vanished.sig"]}}},
        # --- stray human tag on an unreachable digest ---
        {"id": 24, "name": "sha256:manual", "updated_at": _iso(120),
         "metadata": {"container": {"tags": ["experiment-do-not-delete"]}}},
    ]


class PruneSafetyTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.deleted: list[int] = []
        self.mod.registry_token = lambda: "tok"
        self.mod.fetch_manifest = self._fetch
        self.mod.list_versions = lambda tok: _versions()
        self.mod.delete_version = lambda tok, vid: self.deleted.append(vid)
        os.environ["GITHUB_TOKEN"] = "x"

    @staticmethod
    def _fetch(tok, ref):
        doc = _REG.get(ref)
        if doc is None:
            return None, None
        digest = _TAG2DIG.get(ref, ref if ref.startswith("sha256:") else None)
        return doc, digest

    def _run(self, *argv):
        sys.argv = ["prune", *argv]
        return self.mod.main()

    def test_dry_run_is_default_and_deletes_nothing(self):
        self.assertEqual(self._run("--grace-days", "14"), 0)
        self.assertEqual(self.deleted, [])

    def test_collects_only_old_unreachable_and_orphaned_sigs(self):
        self.assertEqual(self._run("--grace-days", "14", "--apply"), 0)
        self.assertEqual(sorted(self.deleted), [21, 22, 23])

    def test_live_untagged_children_are_never_deleted(self):
        """The whole reason this script does not use 'delete untagged'."""
        self._run("--grace-days", "14", "--apply")
        for vid in sorted(LIVE_UNTAGGED_CHILDREN):
            self.assertNotIn(
                vid, self.deleted,
                f"deleted live untagged child {vid} — this would break "
                f"the multi-arch image its parent index points at",
            )

    def test_grace_period_protects_recent_unreachable(self):
        self._run("--grace-days", "14", "--apply")
        self.assertNotIn(20, self.deleted)
        # ...and drops out of protection once it ages past the window
        self.deleted.clear()
        self._run("--grace-days", "1", "--apply")
        self.assertIn(20, self.deleted)

    def test_stray_tag_on_unreachable_digest_is_kept(self):
        self._run("--grace-days", "14", "--apply")
        self.assertNotIn(24, self.deleted)

    def test_live_signature_is_kept(self):
        self._run("--grace-days", "14", "--apply")
        self.assertNotIn(8, self.deleted)

    def test_floor_refuses_oversized_pass(self):
        self.assertEqual(self._run("--grace-days", "14", "--max-delete", "1"), 2)
        self.assertEqual(self.deleted, [])

    def test_limit_caps_a_single_pass(self):
        self._run("--grace-days", "14", "--apply", "--limit", "1")
        self.assertEqual(len(self.deleted), 1)


if __name__ == "__main__":
    unittest.main()
