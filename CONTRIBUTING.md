# Contributing

Keep changes narrow and test-backed.

## Preferred contribution shape

Good contributions are:

- one small runtime improvement
- one small test addition
- one documentation correction tied to the current code

Bad contributions are:

- broad architecture drift after implementation exists
- status-only discussion with no diff, test, or decision
- replacing open-world reasoning with brittle regex shortcuts

## Before opening a PR

Run:

```bash
pytest -q
python -m py_compile canopykit/*.py tests/*.py
git diff --check
```

## Scope rules

- keep runtime and docs changes coherent
- do not mix unrelated Canopy changes into this repo
- if blocked, ask for the exact diff or file you need instead of posting only status

## Review standard

The project prefers:

- deterministic mechanics for closed-world problems
- explicit evidence for runtime claims
- operator-readable failure modes
- exact next-owner handoffs for actionable changes
