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
  7. Digests are read case-insensitively and verified against the
     bytes. The first dry run (2026-09-12, run 34713900112) found 0
     reachable digests from 55 live tags because `dict(resp.headers)`
     froze header casing and GHCR sends `docker-content-digest` in
     lower case. The original tests missed it by mocking
     fetch_manifest -- the very layer that was broken -- so these
     drive the real parser through a fake HTTP response instead.
  8. Incoherent reachability refuses to delete (exit 2): zero
     reachable digests despite live tags, or any live tag that will
     not resolve. A GC must never act on an incomplete picture.
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
    # A stray human tag. It is a LIVE tag, so walking it makes its
    # digest reachable -- which is the point: any resolvable tag
    # protects its target through rule 1, and a tag that does NOT
    # resolve trips the coherence gate rather than being ignored.
    "experiment-do-not-delete": {}, "sha256:manual": {},
}
_TAG2DIG = {
    "2.5-xl": "sha256:par_idx",
    "2.5-xl-amd64": "sha256:amd_idx",
    "2.5-xl-arm64": "sha256:arm_idx",
    "sha256-par_idx.sig": "sha256:livesig",
    "experiment-do-not-delete": "sha256:manual",
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
        self.mod.delete_version = lambda tok, vid, **kw: self.deleted.append(vid)
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

    def test_stray_human_tag_is_kept(self):
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


class RateLimitTests(unittest.TestCase):
    """A rate-limited pass must not report success.

    On the first full pass (2026-09-13, run 34742398684) 7058 of 14134
    deletions succeeded, 7076 returned 403, and the run still exited 0
    -- a scheduled prune would have looked healthy while leaving half
    the work undone.
    """

    def setUp(self):
        self.mod = _load()
        self.deleted: list[int] = []
        self.mod.registry_token = lambda: "tok"
        self.mod.list_versions = lambda tok: _versions()
        self.mod.walk_reachable = lambda tok, tags: ({"sha256:par_idx"}, [])
        os.environ["GITHUB_TOKEN"] = "x"

    def _run(self, *argv):
        sys.argv = ["prune", *argv]
        return self.mod.main()

    def test_incomplete_pass_exits_nonzero(self):
        def only_first(tok, vid, **kw):
            if self.deleted:
                raise self.mod.RateLimited("rate limited")
            self.deleted.append(vid)
        self.mod.delete_version = only_first
        self.assertEqual(self._run("--grace-days", "14", "--apply"), 1)
        self.assertEqual(len(self.deleted), 1)

    def test_complete_pass_exits_zero(self):
        self.mod.delete_version = lambda tok, vid, **kw: self.deleted.append(vid)
        self.assertEqual(self._run("--grace-days", "14", "--apply"), 0)

    def test_403_is_waited_out_then_succeeds(self):
        import urllib.error

        calls = {"n": 0}
        real = self.mod.delete_version
        slept: list[float] = []
        self.mod.time = type("T", (), {"sleep": staticmethod(lambda s: slept.append(s)),
                                       "time": staticmethod(lambda: 0.0)})()

        class _Op:
            @staticmethod
            def open(req, timeout=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise urllib.error.HTTPError(
                        req.full_url, 403, "Forbidden", {"Retry-After": "7"}, None)
                class R:
                    def __enter__(s): return s
                    def __exit__(s, *a): return False
                    def read(s): return b""
                return R()

        self.mod._OPENER = _Op()
        real("tok", 123, budget=[600.0])
        self.assertEqual(calls["n"], 2)
        self.assertEqual(slept, [7.0])

    def test_403_beyond_budget_raises(self):
        import urllib.error

        class _Op:
            @staticmethod
            def open(req, timeout=None):
                raise urllib.error.HTTPError(
                    req.full_url, 403, "Forbidden", {"Retry-After": "3600"}, None)

        self.mod._OPENER = _Op()
        with self.assertRaises(self.mod.RateLimited):
            self.mod.delete_version("tok", 123, budget=[60.0])


class DigestParsingTests(unittest.TestCase):
    """Drive the real fetch_manifest through a fake HTTP response.

    These mock at the transport, not at fetch_manifest, because
    mocking fetch_manifest is what hid the header-casing bug.
    """

    def setUp(self):
        self.mod = _load()

    def _install_response(self, body: bytes, headers: dict[str, str]):
        import email.message

        msg = email.message.Message()
        for k, v in headers.items():
            msg[k] = v

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return body

            headers = msg

        self.mod._OPENER = type("O", (), {"open": staticmethod(lambda req, timeout=None: _Resp())})()

    def test_digest_read_from_lowercase_header(self):
        body = b'{"schemaVersion":2,"manifests":[]}'
        want = "sha256:" + __import__("hashlib").sha256(body).hexdigest()
        # GHCR's actual casing
        self._install_response(body, {"docker-content-digest": want})
        _doc, digest = self.mod.fetch_manifest("tok", "2.5-xl")
        self.assertEqual(digest, want)

    def test_digest_read_from_titlecase_header(self):
        body = b'{"schemaVersion":2,"manifests":[]}'
        want = "sha256:" + __import__("hashlib").sha256(body).hexdigest()
        self._install_response(body, {"Docker-Content-Digest": want})
        _doc, digest = self.mod.fetch_manifest("tok", "2.5-xl")
        self.assertEqual(digest, want)

    def test_digest_computed_when_header_absent(self):
        body = b'{"schemaVersion":2,"manifests":[]}'
        want = "sha256:" + __import__("hashlib").sha256(body).hexdigest()
        self._install_response(body, {})
        _doc, digest = self.mod.fetch_manifest("tok", "2.5-xl")
        self.assertEqual(digest, want)

    def test_digest_mismatch_is_fatal(self):
        body = b'{"schemaVersion":2,"manifests":[]}'
        self._install_response(body, {"docker-content-digest": "sha256:" + "0" * 64})
        with self.assertRaises(RuntimeError):
            self.mod.fetch_manifest("tok", "2.5-xl")


class CoherenceGateTests(unittest.TestCase):
    """Refuse to delete when the reachability picture is not trustworthy."""

    def setUp(self):
        self.mod = _load()
        self.deleted: list[int] = []
        self.mod.registry_token = lambda: "tok"
        self.mod.list_versions = lambda tok: _versions()
        self.mod.delete_version = lambda tok, vid, **kw: self.deleted.append(vid)
        os.environ["GITHUB_TOKEN"] = "x"

    def _run(self, *argv):
        sys.argv = ["prune", *argv]
        return self.mod.main()

    def test_zero_reachable_refuses(self):
        """The exact production failure: walk returns nothing."""
        self.mod.walk_reachable = lambda tok, tags: (set(), [])
        self.assertEqual(self._run("--grace-days", "14", "--apply"), 2)
        self.assertEqual(self.deleted, [])

    def test_unresolved_tag_refuses(self):
        self.mod.walk_reachable = lambda tok, tags: ({"sha256:par_idx"}, ["2.5-xl-arm64"])
        self.assertEqual(self._run("--grace-days", "14", "--apply"), 2)
        self.assertEqual(self.deleted, [])


if __name__ == "__main__":
    unittest.main()
