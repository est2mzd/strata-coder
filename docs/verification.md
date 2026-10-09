# v0.1 verification — 2026-10-09

Verified during implementation:

- 19 Python tests passed on Linux x86_64 and DGX Spark Linux aarch64 / Python 3.12. Tests cover isolated edits and reviewed apply, dirty destination/base conflicts, denied paths/symlinks, stale hashes, failing tests, timeouts, cancellation, evidence pagination, MCP initialization/schema, HTTP integration and SSH command construction.
- Node syntax check and mocked extension registration/SecretStorage forwarding/workspace-trust checks passed.
- Supervisor Skill metadata validation passed.
- Official `@vscode/vsce@3.6.2` produced the VSIX.
- **Real SSH + real Strata smoke test:** opened a temporary password-authenticated SSH tunnel to the existing loopback Strata API and connected using `direct` mode. The loaded model was `qwen3.8-flash-next-iq3_s`. In a temporary Git fixture, the worker read code, changed `return a - b` to `return a + b`, and ran the configured tests. The gateway reran final tests; the test harness inspected the patch, applied the exact hash, and independently reran the fixture tests. All passed. Four model turns, 4,604 input and 517 output Strata tokens were reported by the API.

The smoke-test token figures are **Strata tokens**, not Cursor usage, and the fixture is deliberately small. This is not a benchmark or a general coding-quality claim.

Not yet verified:

- Actual installed Cursor Chat discovery, Skill loading and lifecycle behavior (extension tests use mocks).
- Real key/agent authentication with the extension-owned SSH tunnel (command construction/cleanup tested; the live smoke used a manually managed password tunnel).
- Windows, macOS, or Cursor Remote SSH extension-host behavior.
- Client hardware, concurrent clients, or global Spark admission control.
- Cursor token savings or accuracy improvement compared with Cursor-only work.

The CI workflow repeats offline/local fixture tests and packages a VSIX. It does not connect to a private Strata server.
