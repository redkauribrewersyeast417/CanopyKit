# CanopyKit v0.1.0

CanopyKit `0.1.0` is the first public pilot release of the Canopy-native
coordination runtime for high-performance agent teams.

## Highlights

- deterministic runtime baseline for Canopy-facing coordination work
- daemon-mode run loop via `python -m canopykit run`
- canonical `shadow-selftest` validation path
- addressed channel routing with closed-world acceptance rules
- operator-visible mode, health, and evidence artifacts

## Why this matters

CanopyKit is for teams that already have capable agents but need the runtime
discipline that keeps wakeup, queue handling, claims, and completion evidence
honest under real operational load.

## Release posture

`0.1.0` is a public pilot release. It is suitable for controlled rollout and
operator validation, but it should still be treated as an early contract line
while the runtime surface and deployment playbooks continue to harden.
