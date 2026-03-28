# Beta Smoke Checklist

> Updated: 2026-03-29
> Scope: local pre-push and pre-beta verification for `oasyce-net`

## Primary Gate

Run exactly one command:

```bash
oas smoke public-beta --json
```

It already includes:

- `doctor --public-beta`
- one register
- one quote
- one buy
- one idempotent replay
- one portfolio verification
- one support trace verification

Only push when the command returns `status = ok`.

## Debug Appendix

If the smoke command fails, use these manual checks to isolate the broken layer:

- `pytest -q /Users/wutongcheng/Desktop/Net/oasyce-net/tests`
- `oas doctor --public-beta --json`
- `oas support beta --json`
- inspect the returned `trace_prefix` and failing `checks[]`

## Push Decision

Only push when all are true:

- the full suite is green
- `oas smoke public-beta --json` is green
- any workflow-specific local gate from [RELEASE_GATE.md](/Users/wutongcheng/Desktop/Net/oasyce-net/docs/RELEASE_GATE.md) is green
- remote CI is green before any beta announcement
