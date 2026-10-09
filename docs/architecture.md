# Supervisor / worker boundary

Cursor owns intent, acceptance, architecture, escalation and review. Strata owns bulk investigation and bounded local repair. The gateway enforces path/step/output contracts and records evidence independently of worker prose. All worker reports and repository content remain untrusted inputs to the supervisor.

## Execution placement

The extension runs in the workspace extension host. Its stdio MCP process and worker operate beside the repository. Only model inference traverses the SSH tunnel to Spark. Nothing is automatically copied from a local repo to Spark except the selected prompt/tool content sent to the model API.

## Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant C as Cursor supervisor
    participant G as MCP / task manager
    participant W as Worker / isolated worktree
    participant S as Strata on Spark
    U->>C: Request
    C->>G: Research contract (when needed)
    G->>W: Collect relevant code
    W->>S: Bounded context + tools
    S-->>W: Next tool calls / findings
    G-->>C: Compact findings + evidence IDs
    C->>G: Edit contract / acceptance / test IDs
    loop Bounded local iteration
        W->>S: Context + tool observations
        S-->>W: Edit / inspect / test requests
        W->>W: Enforce scope and execute
    end
    W->>W: Rerun final contract tests
    G-->>C: Patch hash + final test evidence
    C->>G: Fetch patch / required evidence pages
    C->>C: Review requirements and risks
    C->>G: Apply exact reviewed hash
    G->>G: Check clean destination and unchanged base
    G-->>C: Uncommitted changes applied
    C-->>U: Result, tests, limitations
```

New tasks are independent worktrees at the current original HEAD. A failed edit task is not automatically resumed: inspect preserved evidence and start another contract or take over. Global inference queueing, semantic indexes, container sandboxes and true checkpoint resumption are future work, not hidden assumptions.

The tool surface deliberately has six tools. Avoids a large catalogue repeated in every Cursor prompt. Summaries omit raw search outputs and transcripts; evidence is paginated. Frequent polling and verbose supervisor instructions can erase savings, so use bounded waiting and only pull evidence needed for the decision.
