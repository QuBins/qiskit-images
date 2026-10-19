"""Package lists in build-pages-data.py: reading packages.json from an
image's last layer, the change list, and the history carried over from
the previously deployed file. No network: registry and live-site reads
are stubbed."""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "build-pages-data.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_pages_data", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _layer(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


PK = {"schema_version": 1,
      "python": {"qiskit": "2.5.2", "wrapt": "2.5.0"},
      "apt": {"libssl3t64": "3.5.3-1"}}


class LayerPackages(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.blobs = {}
        self.m._ghcr_get = lambda path, accept, raw=False: self.blobs.get(path)

    def manifest(self, blob: bytes, size: int | None = None) -> dict:
        self.blobs["blobs/sha256:last"] = blob
        return {"layers": [{"digest": "sha256:big", "size": 500_000_000},
                           {"digest": "sha256:last", "size": size or len(blob)}]}

    def test_reads_packages_from_last_layer(self):
        blob = _layer({"opt/": b"", "opt/qubins/packages.json": json.dumps(PK).encode()})
        self.assertEqual(self.m._layer_packages(self.manifest(blob)), PK)

    def test_finds_it_before_a_trailing_empty_layer(self):
        # Real 2.6-xl tail: ..., packages layer, 32-byte empty layer.
        self.blobs["blobs/sha256:pk"] = _layer({"opt/qubins/packages.json": json.dumps(PK).encode()})
        self.blobs["blobs/sha256:empty"] = _layer({})
        manifest = {"layers": [{"digest": "sha256:big", "size": 500_000_000},
                               {"digest": "sha256:pk", "size": 4676},
                               {"digest": "sha256:empty", "size": 32}]}
        self.assertEqual(self.m._layer_packages(manifest), PK)

    def test_old_image_without_the_file(self):
        self.assertIsNone(self.m._layer_packages(self.manifest(_layer({"tmp/x": b"1"}))))

    def test_never_downloads_a_big_last_layer(self):
        blob = _layer({"opt/qubins/packages.json": json.dumps(PK).encode()})
        self.assertIsNone(self.m._layer_packages(self.manifest(blob, size=50_000_000)))

    def test_garbage_and_missing(self):
        self.assertIsNone(self.m._layer_packages(self.manifest(b"not a tar")))
        self.assertIsNone(self.m._layer_packages(None))
        self.assertIsNone(self.m._layer_packages({"layers": []}))


class ChangesAndHistory(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.m.REPO_ROOT = Path(self.tmp.name)
        self.live = None
        self.m._live_packages = lambda tag: self.live

    def tearDown(self):
        self.tmp.cleanup()

    def test_changes(self):
        old = {"python": {"a": "1", "b": "1", "c": "1"}, "apt": {"x": "1"}}
        new = {"python": {"a": "1", "b": "2", "d": "1"}, "apt": {"x": "1"}}
        self.assertEqual(self.m.package_changes(old, new), [
            {"kind": "python", "name": "b", "from": "1", "to": "2"},
            {"kind": "python", "name": "c", "from": "1", "to": None},
            {"kind": "python", "name": "d", "from": None, "to": "1"},
        ])

    def write(self, digest, python):
        cur = {"digest": digest, "amd64": {"python": python, "apt": {}}}
        summary = self.m.write_packages("2.5-xl", {"updated_at": "2026-10-20T04:00:00Z"}, cur)
        out = json.loads((Path(self.tmp.name) / "docs/packages/2.5-xl.json").read_text())
        self.live = out  # what the next deploy will read back
        return summary, out

    def test_first_deploy_has_no_history(self):
        summary, out = self.write("sha256:1", {"wrapt": "2.5.0"})
        self.assertEqual(out["history"], [])
        self.assertEqual(summary, {"url": "packages/2.5-xl.json"})

    def test_new_digest_with_a_version_change_is_recorded(self):
        self.write("sha256:1", {"wrapt": "2.5.0"})
        summary, out = self.write("sha256:2", {"wrapt": "2.5.1"})
        self.assertEqual(len(out["history"]), 1)
        h = out["history"][0]
        self.assertEqual((h["digest"], h["previous_digest"]), ("sha256:2", "sha256:1"))
        self.assertEqual(h["changes"], [{"kind": "python", "name": "wrapt", "from": "2.5.0", "to": "2.5.1"}])
        self.assertEqual(summary["changes"], 1)

    def test_same_digest_or_rebuild_without_changes_keeps_history(self):
        self.write("sha256:1", {"wrapt": "2.5.0"})
        self.write("sha256:2", {"wrapt": "2.5.1"})
        _, out = self.write("sha256:2", {"wrapt": "2.5.1"})   # redeploy, same image
        self.assertEqual(len(out["history"]), 1)
        _, out = self.write("sha256:3", {"wrapt": "2.5.1"})   # new digest, same versions
        self.assertEqual(len(out["history"]), 1)

    def test_history_is_capped(self):
        self.write("sha256:0", {"p": "0"})
        for i in range(1, self.m.PACKAGES_HISTORY + 5):
            _, out = self.write(f"sha256:{i}", {"p": str(i)})
        self.assertEqual(len(out["history"]), self.m.PACKAGES_HISTORY)
        self.assertEqual(out["history"][0]["changes"][0]["to"], str(self.m.PACKAGES_HISTORY + 4))


if __name__ == "__main__":
    unittest.main()
