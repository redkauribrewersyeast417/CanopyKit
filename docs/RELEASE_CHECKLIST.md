# CanopyKit Release Checklist

Use this before cutting a public release.

## Runtime

- [ ] `pytest -q` passes on current `main`
- [ ] `python -m py_compile canopykit/*.py tests/*.py` passes
- [ ] `git diff --check` is clean
- [ ] `shadow-selftest` returns `full_pass` on at least one real agent
- [ ] daemon pilot completes on at least one real agent without runtime crash
- [ ] daemon pilot leaves operator-readable `run-status.json` and `actions.jsonl`

## Operator evidence

- [ ] one short daemon pilot evidence pack exists
- [ ] one longer daemon pilot evidence pack exists
- [ ] operator acceptance is explicitly posted
- [ ] at least one real addressed channel work item was routed correctly
- [ ] no completion happened without evidence

## Security and safety

- [ ] no secrets are present in docs, examples, or committed artifacts
- [ ] security contact/process is documented
- [ ] addressed-work rules are documented
- [ ] intelligence-preservation rule is documented

## Documentation

- [ ] `README.md` reflects current runtime reality
- [ ] `docs/QUICKSTART.md` is accurate
- [ ] `docs/MESH_DEPLOYMENT.md` is accurate
- [ ] `docs/SHADOW_SELFTEST.md` is accurate
- [ ] `docs/OPERATOR_ACCEPTANCE.md` is accurate
- [ ] `examples/canopykit.config.json` matches the current config surface

## Release posture

- [ ] package version matches in `canopykit/__init__.py` and `pyproject.toml`
- [ ] `CHANGELOG.md` contains a versioned entry for the release being cut
- [ ] release notes doc exists for the current cut
- [ ] CI workflow is green on the release candidate
- [ ] at least one operator run path exists (`docs/QUICKSTART.md` or `docs/SERVICE_RUNBOOK.md`)

## Do not release if

- daemon mode only works through compatibility-mode fallback
- operator evidence is stale
- runtime requires hidden tribal knowledge to configure
- agents still need constant human nudging to avoid stalling
