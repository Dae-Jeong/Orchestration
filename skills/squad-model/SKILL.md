---
name: squad-model
description: Coordinate this repository's squad work through PM, planning, design, development and QA with portable task contracts and evidence-based handoffs.
---

# Squad model

Read [the task contract](references/model.md) before decomposing or advancing work.
The PM owns coordination and role allocation using [the integrated PM flow](references/pm-flow.md).
Read it when accepting intake, assigning executors/models, or advancing a handoff.
Read [current tool bindings](references/execution-tools.md) when operating Paperclip
or Orca. Tool IDs and commands do not define the portable work contract.
For recurring-operation design, read [the bounded review loop](references/review-loop.md);
it is a proposal, not authorization to enable schedules or recurring model calls.
Use [role contracts](references/roles.md) for assignment and completion, and
[the handoff template](references/handoff.md) in the existing named task document.
For design or FE handoff, also read [design tools](references/design-tools.md).
Read the operator-provided canonical Product Workflow through
`PRODUCT_WORKFLOW_FILE` when available. This bundle owns only this project's
task model; it does not replace global collaboration rules. If that external
document is unavailable, disclose it and use the explicit task contract; do not
claim the canonical process was read.
Use the operator's `product-workflow` skill for evidence intake and outcome review;
check its availability in the executor, rather than assuming this session's catalog.

1. Capture the intake evidence, intended user outcome and exclusions. PM/planning
   proposes the smallest task breakdown; design and development identify their
   deliverables, uncertainty and dependencies. Roles are perspectives, not a
   requirement to launch three agents.
2. Reuse the user's existing authorization. Record task-specific acceptance,
   verification method, allowed changes and execution budget. Only missing or
   materially changed scope needs a new human decision. Proposed criteria are
   not an approval receipt.
3. Give each task an immutable ID. Keep contract revision and content hash
   separate from identity and ordering. Keep tool IDs in a separate mapping.
4. Record predecessor relations and review requirements in the selected work system. Independent
   tasks can proceed together only when their resource claims do not conflict.
   Until an actual resource lock is verified, the coordinator serializes
   conflicting tasks and records the decision. Do not create a second scheduler.
5. Verify output against the approved revision and record evidence. Process exit
   and an agent's `done` request are not proof. On failure, revise within scope;
   on changed scope, exhausted agreed attempts, or unavailable authority, route
   that task to the named human while unrelated tasks may proceed.
6. After verified completion, recheck successor contracts, blockers and resources.
   After restart, inspect authoritative attempt history and external effects before
   replay. Changed criteria require review of affected evidence and successors.

The installation pilot uses deterministic probes and bounded read-only tool checks.
Paid models, deployment, messages and recurring runs need their own execution scope.
