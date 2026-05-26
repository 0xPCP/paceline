# Dependency and CVE Audit

Paceline runs a GitHub Actions dependency audit on pushes to `master`, pushes to `post-beta`, pull requests, and manual workflow dispatches.

## What Runs

- Workflow: `.github/workflows/security-audit.yml`
- Tool: `pip-audit`
- Input: `requirements.txt`

The audit fails when a known vulnerable Python package version is present.

## Required Commit Check

Run this before every commit and before every push:

```bash
.venv/bin/pip-audit --cache-dir /tmp/paceline-pip-audit-cache -r requirements.txt
```

If `pip-audit` is not installed in the local virtualenv:

```bash
.venv/bin/python -m pip install pip-audit
```

After pushing, confirm the GitHub Actions job named
`Security Audit / dependency-audit` passes before treating the deployment as
complete.

## Production Notes

- Keep dependency updates small and test them before pushing to `master`.
- Treat a failing audit as a release blocker unless the finding is clearly not exploitable in Paceline.
- If an urgent fix requires accepting a temporary CVE, document the package, CVE, reason, and planned removal date in this file.

## Related Runtime Security Settings

For production rate limiting, set:

```bash
RATELIMIT_STORAGE_URI=redis://:<password>@<host>:6379/0
```

Without Redis, limits are local to each worker and can be bypassed more easily during bursts.
