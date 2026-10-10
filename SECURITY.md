# Security

QuBins publishes container images that people run in classrooms, on
Raspberry Pis and on mybinder.org, so we take their security seriously.
This page says what we patch, how quickly, and how to tell us about a
problem.

## Reporting a vulnerability

Please report privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Only the
maintainers can see the report. Please don't open a public issue or
pull request for a problem that isn't public yet.

Useful to include: the image tag (or digest), what you found, and how
to reproduce it. We aim to reply within 7 days. QuBins is a small
volunteer project, so there is no bug bounty.

You don't need to report privately when:

- **A CVE is already public and fixed upstream**, but our image still
  ships the old version. The nightly rebuild usually picks it up within
  a day. If it hasn't after a few days, a normal issue is fine.
- **The vulnerability is in Qiskit or another package itself.** Report
  it to that project. If it affects our images, tell us too.
- **It concerns mybinder.org.** Report it to the
  [Binder project](https://mybinder.readthedocs.io/en/latest/about/about.html).

## What we cover

- The images `ghcr.io/qubins/images:*`, and how they are built and
  published (this repository's Dockerfile, requirements and workflows).
- The site [qubins.org](https://qubins.org/), including the `/launch/`
  redirector.

## Supported images

| Tags | Patched? |
|---|---|
| Every `<minor>-<flavor>` listed in [versions.json](https://qubins.org/versions.json), and `latest-*` | Yes. Rebuilt every night. |
| Monthly snapshots, `<minor>-<flavor>-YYYYMMDD` | No. A snapshot is frozen on purpose. Move to the next snapshot for fixes. |
| Retired minors (1.4 and older) | No. Not rebuilt, not patched. |

## How fixes reach the images

- **Nightly rebuild.** Every supported tag is rebuilt from scratch each
  day, with the base image pulled again, so fixes in Ubuntu, Python or
  any pip package flow in without anyone touching the repo.
- **Trivy gate.** Every image is scanned before it is published. Any
  HIGH or CRITICAL finding that has a fix available blocks that image.
  The previous image stays in place: we never publish over a finding
  we could have fixed.
- **When the gate blocks**, a maintainer fixes it by hand, typically
  by raising a version floor, upgrading a system package, or removing
  a file the image doesn't need. Since May 2026 that has happened
  about every eight days.
- **Suppressions** are rare and listed in [`.trivyignore`](.trivyignore).
  Each one gives the reason, usually that the vulnerable code can't be
  reached or that no installable fix exists yet, and is removed once a
  fix exists. One file is skipped by the scan altogether: Ray's vendored
  `ray_dist.jar`, pulled in by qiskit-serverless, which only Ray itself
  can patch (the reason is in the build workflow).

## Checking an image yourself

- Every published tag is signed with cosign (keyless, tied to this
  repository's workflow) and carries SLSA build provenance. See
  [Verifying images](README.md#verifying-images).
- Labels on each image name the commit that built it, its base image
  and digest, and the installed Qiskit and runtime versions. See
  [Image labels](README.md#image-labels).

## Keeping your own credentials safe

The images contain no credentials. On mybinder.org your session runs
on a shared public service, so don't store an IBM Quantum API key
there. In particular, don't call `QiskitRuntimeService.save_account()`
on Binder. Pass the key for the current session only, and revoke it if
you think it leaked.
