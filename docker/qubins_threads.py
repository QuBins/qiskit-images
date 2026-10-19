"""Size thread pools to the container's CPU limit, not the host's.

Loaded at interpreter start by qubins-threads.pth, so it runs before any
library starts a thread pool, in Jupyter and in every kernel alike.

On mybinder a pod sees the node's 48 CPUs (os.cpu_count()) but its
cgroup allows one. Aer, OpenBLAS and OpenMP then each start 48 threads
that spin against each other on that one CPU: a hello-world Estimator
job took 103 s instead of 1.3 s. Aer's default thread count follows
OMP_NUM_THREADS, so capping the usual variables fixes it.

Without a CPU limit (a plain local docker/podman run) nothing is set, so
full threads stay. A variable the user already set is never overridden.
"""

import math
import os

VARS = (
    "OMP_NUM_THREADS",  # OpenMP: Aer's default parallelism, libgomp
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "RAYON_NUM_THREADS",  # Qiskit's Rust parallelism
    "QISKIT_NUM_PROCS",  # Qiskit's multiprocessing (parallel_map)
)


def _cgroup_cpus():
    # cgroup v2: "max 100000" (no limit) or "<quota> <period>".
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
        if quota != "max":
            return math.ceil(int(quota) / int(period))
        return None
    except (OSError, ValueError):
        pass
    # cgroup v1: quota -1 means no limit.
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read())
        if quota > 0 and period > 0:
            return math.ceil(quota / period)
    except (OSError, ValueError):
        pass
    return None


def _limit():
    host = os.cpu_count() or 1
    cpus = [host]
    try:
        cpus.append(len(os.sched_getaffinity(0)))  # docker --cpuset-cpus
    except (AttributeError, OSError):
        pass
    quota = _cgroup_cpus()
    if quota:
        cpus.append(quota)
    n = max(1, min(cpus))
    return n if n < host else None


def apply():
    n = _limit()
    if n is None:
        return
    for var in VARS:
        os.environ.setdefault(var, str(n))


try:
    apply()
except Exception:  # never break interpreter start-up
    pass
