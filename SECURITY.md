# Security

## Reporting

Until a public security process is established, report issues privately to the
project maintainer rather than posting exploit details in public issues.

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
