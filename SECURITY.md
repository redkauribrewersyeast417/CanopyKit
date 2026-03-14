# Security

## Reporting

Preferred path:

1. Open a private GitHub Security Advisory for this repository if that flow is
   enabled.
2. If advisories are unavailable, contact the maintainer through the repository
   owner's public GitHub profile at `https://github.com/kwalus` before posting
   any exploit details publicly.

Please include:

- affected version or commit
- reproduction steps
- whether secrets, tokens, or live Canopy data were exposed
- whether the issue can be triggered without operator consent

Do not post exploit details in public issues before the maintainer confirms a
safe disclosure path.

## Security principles

CanopyKit is built on these rules:

1. Authorization comes before relevance
2. Subscriptions may narrow work, never widen visibility
3. Actionable work should be explicitly addressed
4. Deterministic code is for closed-world mechanics only
5. Completion must preserve evidence

## Sensitive data

Do not post:

- API keys
- bearer tokens
- secrets from local config files
- raw machine-local credentials

If an agent posts a likely secret, treat it as compromised until rotated.
