"""Precompile site-packages to bytecode, reproducibly (QuBins, doQumentation request 2026-10-19).

Run at the end of each pip layer in the Dockerfile. pip installs with
--no-compile, because pip's own timestamp-based .pyc files embed source
mtimes and would differ on every build. Without any .pyc, though, every
fresh Binder pod compiles qiskit & co. from source on first import, which
made doQumentation's hello-world take minutes on mybinder.

This writes CHECKED_HASH .pyc files instead: they hold a hash of the
source, not its mtime, so they are byte-identical across builds, and
Python still re-validates the source on import, so a later
`%pip install` can never leave stale bytecode in use.

Only .py files whose cached .pyc is missing or stale are compiled, so
each layer gets exactly the bytecode for the files it installed. It runs
single-process in sorted order, and the Dockerfile sets PYTHONHASHSEED=0
for it; parallel compileall (-j) was measured not to be reproducible.
"""
import importlib.util
import os
import py_compile
import sys
import sysconfig
import warnings

MODE = py_compile.PycInvalidationMode.CHECKED_HASH


def stale(src: str, pyc: str) -> bool:
    try:
        with open(pyc, "rb") as f:
            header = f.read(16)
    except OSError:
        return True
    if len(header) < 16 or header[:4] != importlib.util.MAGIC_NUMBER:
        return True
    flags = int.from_bytes(header[4:8], "little")
    with open(src, "rb") as f:
        data = f.read()
    if flags & 0b1:  # hash-based: compare the source hash
        return header[8:16] != importlib.util.source_hash(data)
    st = os.stat(src)  # timestamp-based (from the base image)
    return (int.from_bytes(header[8:12], "little") != (int(st.st_mtime) & 0xFFFFFFFF)
            or int.from_bytes(header[12:16], "little") != (st.st_size & 0xFFFFFFFF))


def main() -> int:
    # Third-party files (test fixtures, old notebooks' helpers) raise
    # SyntaxWarnings by the dozen; they'd only flood the build log.
    warnings.simplefilter("ignore")
    root = sysconfig.get_paths()["purelib"]
    done = failed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            src = os.path.join(dirpath, name)
            pyc = importlib.util.cache_from_source(src)
            if not stale(src, pyc):
                continue
            try:
                py_compile.compile(src, cfile=pyc, doraise=True, invalidation_mode=MODE)
                done += 1
            except (py_compile.PyCompileError, SyntaxError, ValueError, OSError):
                failed += 1  # e.g. Python-2-only test fixtures; skipping is harmless
    print(f"compile-pyc: {done} compiled, {failed} skipped, under {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
