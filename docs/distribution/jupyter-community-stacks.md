# Draft: jupyter/docker-stacks "Community Stacks" entry

**Not submitted.** This is the exact content to paste into a PR against
[`jupyter/docker-stacks`](https://github.com/jupyter/docker-stacks),
file `docs/using/selecting.md`, section `## Community Stacks`.

## Why this listing fits

These images are built `FROM quay.io/jupyter/base-notebook`, which is
precisely what that section lists: third-party stacks derived from the
core images. The table's Binder column also works out of the box — the
`latest-xl` stub branch is a Binder-buildable ref, the same mechanism
qubins.org already uses.

## Table row

Insert alphabetically-last (the table is append-ordered, not sorted):

```markdown
| [qiskit]       | [![bb]][qiskit_b]       | Prebuilt, signed **Qiskit** environments (`small` / `xl` / `xxl`, multiple Qiskit minors) on top of the `base-notebook` image |
```

## Link definitions

Append to the link-reference block below the table:

```markdown
[qiskit]: https://github.com/QuBins/qiskit-images
[qiskit_b]: https://mybinder.org/v2/gh/QuBins/qiskit-images/latest-xl
```

## Before submitting

- [ ] **Add a LICENSE.** The repo currently has none, so it is legally
      "all rights reserved". That is a poor look on a list of images
      inviting reuse, and it blocks the Artifact Hub `license` field too.
- [ ] Check the Binder link actually cold-starts (`latest-xl` is ~2-3 GB;
      the warm-up cron keeps it warm, but a reviewer may hit a cold
      backend and judge the image by it).
- [ ] Re-read their contributing guide (`docs/contributing/stacks.md`) —
      it points at a cookiecutter and may expect specific conventions.
