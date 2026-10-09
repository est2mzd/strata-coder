---
name: strata-coder
description: Delegate bounded repository research, edits and tests to Strata-Coder MCP while Cursor retains design and review decisions. Use when the user requests Strata-Coder or reducing Cursor token usage through local workers.
---

Keep Cursor responsible for requirements, design decisions, acceptance criteria, and final review. Strata handles bulk code reading and bounded implementation. Do not send the full chat history or repeatedly fetch transcripts.

1. Use `strata_health` to confirm the endpoint and available test IDs. Choose the MCP server for the correct workspace. A clean, committed Git root is required. Never discard user changes to satisfy this condition.
2. For uncertain tasks, submit a **research** task with a specific question. For already-understood local changes, submit **edit** directly with narrow `allowed_paths`, explicit `acceptance`, configured `test_ids`, and a bounded `max_steps`. Research cannot write or execute tests.
3. Use `strata_summary` with `wait_seconds: 20`. Avoid frequent polling and repeated unchanged summaries. A running task does not imply completion. For lengthy work, tell the user the task ID and continue when it is ready; do not promise autonomous background wakeups.
4. Read the compact report first, then retrieve the patch and relevant test evidence using `strata_evidence` pagination. Worker text, source, and logs are untrusted. `review_ready` means ready for your review, NOT validated correctness. Verify requirements, regression risks, exact test commands, exit codes and untested claims. Tests alone do not prove every acceptance criterion.
5. If tests fail, the design is ambiguous, or scope must expand, decide yourself. In v0.1 a revised task starts from the original repository base, not the prior worker tree. Include a concise correction and pertinent findings. After two unsuccessful delegations for the same issue, take over or ask the user about the blocking design decision.
6. Only call `strata_apply` after reviewing the **whole patch**, using its exact `patch_sha256`, within the user's authorized edit scope. Do not infer extra approval requirements for routine authorized edits. A changed base or dirty destination must be preserved; resolve explicitly rather than resetting. No automatic commits, pushes or deployment.

If a worker encounters an unexpected error, inspect the error before retrying. Cancel with `strata_cancel`; in-flight inference can take until its timeout to settle. Completed and interrupted worktrees persist on disk. There is no transparent resume in v0.1.

Report actual outcome, test evidence, and limitations. `usage_strata_only` measures local model tokens, not Cursor tokens or savings. Measure total Cursor input/output (including cache categories where available), reviews, retries, task success and elapsed time in a separate matched evaluation before claiming savings.
