---
name: squad-model
description: Coordinate an authorized work item through PM/planning, design and development using explicit task contracts and Paperclip issues. Use for this repository's squad pilot and task decomposition.
---

# Squad model

Read [the task contract](references/model.md) before decomposing or advancing work.
Read the operator-provided canonical Product Workflow through
`PRODUCT_WORKFLOW_FILE` when available. This bundle owns only this project's
task model; it does not replace global collaboration rules. If that external
document is unavailable, disclose it and use the explicit task contract; do not
claim the canonical process was read.

1. Capture the intake evidence, intended user outcome and exclusions. PM/planning
   proposes the smallest task breakdown; design and development identify their
   deliverables, uncertainty and dependencies. Roles are perspectives, not a
   requirement to launch three agents.
2. Reuse the user's existing authorization. Record task-specific acceptance,
   verification method, allowed changes and execution budget. Only missing or
   materially changed scope needs a new human decision. Proposed criteria are
   not an approval receipt.
3. Give each task an immutable ID. Keep contract revision and content hash
   separate from identity and ordering. Map it to one Paperclip issue UUID.
4. Use Paperclip blocker relations and explicit execution policies. Independent
   tasks can proceed together only when their resource claims do not conflict.
   Until an actual resource lock is verified, the coordinator serializes
   conflicting tasks and records the decision. Do not create a second scheduler.
5. Verify output against the approved revision and record evidence. Process exit
   and an agent's `done` request are not proof. On failure, revise within scope;
   on changed scope, exhausted agreed attempts, or unavailable authority, route
   that task to the named human while unrelated tasks may proceed.
6. After verified completion, recheck successor contracts, blockers and resources.
   After restart, inspect Paperclip run/issue history and external effects before
   replay. Changed criteria require review of affected evidence and successors.

For the installation pilot, use the deterministic process probe only. Paid
models, deployment, messages and recurring runs need their own execution scope.
