# Evaluation protocol (no savings claimed yet)

Compare Cursor-only and Cursor+Strata on the same committed repository snapshots and equivalent instructions. Separate research, one-file fixes, multi-file changes and ambiguous tasks. Include failure cases. Use fresh sessions, identical Cursor model/settings and repeat runs in varied order.

Record for both arms: task ID, base SHA, task category, total Cursor input/output tokens (and cached categories separately if available), all retries/review/polling calls, actual billed cost if available, wall time, hidden-test outcome, reviewer-identified defects and whether the task completed. For the delegated arm also record Strata tokens, worker iterations and hardware load. Worker usage is never substituted for Cursor usage.

Evaluate only accepted fixes with equivalent correctness. Compare aggregate cost per successful task as well as task-level distributions; failed delegations and supervisor takeover remain in the denominator. Review patches without knowing which arm produced them where practical. Tune delegation using failures, not merely model self-confidence.

Initial acceptance gates: no lost user changes, no out-of-scope writes through worker tools, failed tests block apply, reviewed hash/base conflicts reject apply, cancellation stops further tool execution, useful research citations, and a real Cursor Chat invocation on each supported host. No numerical token-saving target is a verified result until measured.
